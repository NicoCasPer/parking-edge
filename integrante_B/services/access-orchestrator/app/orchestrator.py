"""
orchestrator.py — Lógica central de decisión de acceso.

Responsabilidad:
  Consumir eventos del bus MQTT, consultar la base de datos y emitir
  la decisión de acceso correcta según la tabla de decisión del blueprint:

    Evento MQTT recibido     Condición BD               Acción
    ─────────────────────────────────────────────────────────────────────
    plate_read               whitelist activa         → ACCESS_GRANTED  (whitelist)
    plate_read               pago registrado hoy      → ACCESS_GRANTED  (payment_approved)
    plate_read               sin registro             → ACCESS_DENIED   (unknown_plate)
    plate_unreadable         cualquiera               → assisted_mode   (operador)
    ─────────────────────────────────────────────────────────────────────

  Adicionalmente, por cada evento procesado:
    - Inserta un registro en la BD vía database.insert_event()
    - Publica barrier_command (OPEN) cuando el acceso es concedido

Interfaz de base de datos (implementada por Integrante A en database.py):
    database.get_whitelist(plate: str) -> Optional[dict]
        Retorna el registro si la placa está en whitelist con valid_until > now().
        Retorna None si no existe o está expirada.

    database.check_payment(plate: str) -> Optional[dict]
        Retorna el registro de pago si existe un pago APPROVED para hoy.
        Retorna None si no hay pago vigente.

    database.insert_event(event: dict) -> None
        Inserta un evento de acceso en la tabla de auditoría.

Inyección de dependencias:
  El orquestador recibe la BD como argumento del constructor para que
  los tests puedan usar una BD en memoria sin tocar archivos reales.
"""

import logging
from typing import Any, Callable, Dict, Optional, Protocol

from services.common.event_bus import EventBus
from services.common.event_models import Topics
from services.access_orchestrator.app.policies import Policies

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocolo de base de datos — define el contrato que database.py debe cumplir
# ---------------------------------------------------------------------------

class DatabaseProtocol(Protocol):
    """
    Interfaz mínima que el orquestador necesita de la BD del Integrante A.
    Permite mockear la BD en tests sin importar database.py real.
    """
    def get_whitelist(self, plate: str) -> Optional[Dict[str, Any]]: ...
    def check_payment(self, plate: str) -> Optional[Dict[str, Any]]: ...
    def insert_event(self, event: Dict[str, Any]) -> None: ...


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Consume eventos del bus MQTT y emite decisiones de acceso.
    Un servicio instancia uno y lo mantiene vivo bajo systemd.
    """

    def __init__(
        self,
        event_bus: EventBus,
        database:  DatabaseProtocol,
        policies:  Optional[Policies] = None,
    ) -> None:
        """
        Args:
            event_bus: Instancia ya conectada del EventBus compartido.
            database:  Implementación de DatabaseProtocol (database.py del Integrante A).
            policies:  Configuración de operación. Si None, carga desde policies.yaml.
        """
        self.bus      = event_bus
        self.db       = database
        self.policies = policies or Policies.load()

        # Suscribir eventos que el orquestador debe procesar
        self.bus.subscribe(Topics.PLATE_READ,       self._on_plate_read)
        self.bus.subscribe(Topics.PLATE_UNREADABLE, self._on_plate_unreadable)

        logger.info(
            "Orchestrator initialized | mode=%s confidence_min=%.2f",
            self.policies.default_mode, self.policies.confidence_min,
        )

    # -----------------------------------------------------------------------
    # Handlers de eventos MQTT
    # -----------------------------------------------------------------------

    def _on_plate_read(self, envelope: Dict[str, Any]) -> None:
        """
        Procesa un evento plate_read exitoso.

        Flujo de decisión:
            1. ¿Placa en whitelist activa?    → GRANTED (whitelist)
            2. ¿Pago registrado hoy?          → GRANTED (payment_approved)
            3. Sin registro                   → DENIED  (unknown_plate)
        """
        trace_id = envelope.get("trace_id", "unknown")
        payload  = envelope.get("payload", {})
        plate    = payload.get("plate", "")
        lane_id  = payload.get("lane_id", "ENTRADA-1")

        if not plate:
            logger.warning("plate_read received with empty plate | trace_id=%s", trace_id)
            return

        logger.info(
            "Processing plate_read | plate=%s lane=%s trace_id=%s",
            plate, lane_id, trace_id,
        )

        # --- Rama 1: whitelist ---
        whitelist_entry = self._safe_db_call(
            lambda: self.db.get_whitelist(plate),
            context=f"get_whitelist({plate})",
        )
        if whitelist_entry is not None:
            self._grant_access(plate, "whitelist", lane_id, trace_id)
            self._record_event(plate, "ACCESS_GRANTED", "whitelist", lane_id, trace_id)
            return

        # --- Rama 2: pago ---
        payment_entry = self._safe_db_call(
            lambda: self.db.check_payment(plate),
            context=f"check_payment({plate})",
        )
        if payment_entry is not None:
            self._grant_access(plate, "payment_approved", lane_id, trace_id)
            self._record_event(plate, "ACCESS_GRANTED", "payment_approved", lane_id, trace_id)
            return

        # --- Rama 3: sin registro ---
        self._deny_access(plate, "unknown_plate", lane_id, trace_id)
        self._record_event(plate, "ACCESS_DENIED", "unknown_plate", lane_id, trace_id)

    def _on_plate_unreadable(self, envelope: Dict[str, Any]) -> None:
        """
        Procesa un evento plate_unreadable.
        Activa el modo asistido para que un operador intervenga desde el dashboard.
        """
        trace_id = envelope.get("trace_id", "unknown")
        payload  = envelope.get("payload", {})
        reason   = payload.get("reason", "unknown")
        lane_id  = payload.get("lane_id", "ENTRADA-1")

        logger.warning(
            "Plate unreadable → activating assisted mode | reason=%s lane=%s trace_id=%s",
            reason, lane_id, trace_id,
        )

        self.bus.publish(
            topic=Topics.ASSISTED_MODE,
            payload={
                "reason":            reason,
                "lane_id":           lane_id,
                "timeout_s":         self.policies.assisted_timeout_s,
                "raw_text":          payload.get("raw_text", ""),
                "evidence_id":       payload.get("evidence_id", ""),
            },
            event_type="assisted_mode",
            trace_id=trace_id,
        )

        self._record_event(
            plate="UNREADABLE", decision="ASSISTED",
            reason=reason, lane_id=lane_id, trace_id=trace_id,
        )

    # -----------------------------------------------------------------------
    # Acciones de decisión
    # -----------------------------------------------------------------------

    def _grant_access(
        self, plate: str, reason: str, lane_id: str, trace_id: str
    ) -> None:
        """Publica access_granted y el comando de apertura de barrera."""
        logger.info(
            "ACCESS GRANTED | plate=%s reason=%s lane=%s trace_id=%s",
            plate, reason, lane_id, trace_id,
        )

        # Notificar decisión (consumido por dashboard y connectivity-service)
        self.bus.publish(
            topic=Topics.ACCESS_GRANTED,
            payload={
                "plate":    plate,
                "decision": "ACCESS_GRANTED",
                "reason":   reason,
                "lane_id":  lane_id,
            },
            event_type="access_granted",
            trace_id=trace_id,
        )

        # Ordenar apertura física de la barrera al hardware-controller
        self.bus.publish(
            topic=Topics.BARRIER_COMMAND,
            payload={
                "action":   "OPEN",
                "source":   "orchestrator",
                "lane_id":  lane_id,
            },
            event_type="barrier_command",
            trace_id=trace_id,
        )

    def _deny_access(
        self, plate: str, reason: str, lane_id: str, trace_id: str
    ) -> None:
        """Publica access_denied. La barrera permanece cerrada (sin comando al M4)."""
        logger.info(
            "ACCESS DENIED | plate=%s reason=%s lane=%s trace_id=%s",
            plate, reason, lane_id, trace_id,
        )

        self.bus.publish(
            topic=Topics.ACCESS_DENIED,
            payload={
                "plate":    plate,
                "decision": "ACCESS_DENIED",
                "reason":   reason,
                "lane_id":  lane_id,
            },
            event_type="access_denied",
            trace_id=trace_id,
        )

    # -----------------------------------------------------------------------
    # Auditoría en BD
    # -----------------------------------------------------------------------

    def _record_event(
        self,
        plate:    str,
        decision: str,
        reason:   str,
        lane_id:  str,
        trace_id: str,
    ) -> None:
        """Inserta el evento de acceso en la BD para auditoría."""
        event = {
            "trace_id": trace_id,
            "plate":    plate,
            "decision": decision,
            "reason":   reason,
            "lane_id":  lane_id,
        }
        self._safe_db_call(
            lambda: self.db.insert_event(event),
            context="insert_event",
        )

    # -----------------------------------------------------------------------
    # Utilidades
    # -----------------------------------------------------------------------

    def _safe_db_call(self, fn: Callable, context: str) -> Any:
        """
        Ejecuta una llamada a la BD capturando cualquier excepción.

        Si la BD falla, el orquestador aplica la política por defecto
        (FAIL_CLOSED) en vez de lanzar la excepción al caller.

        Returns:
            El resultado de fn() o None si hubo error.
        """
        try:
            return fn()
        except Exception as exc:
            logger.error(
                "Database error in '%s': %s | policy=%s",
                context, exc, self.policies.default_mode,
            )
            return None
