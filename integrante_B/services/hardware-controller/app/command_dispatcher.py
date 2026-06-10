"""
command_dispatcher.py — Traductor de eventos MQTT a comandos RPMsg para el M4.

Responsabilidad:
  Suscribirse a los eventos de decisión del orquestador en el bus MQTT y
  traducirlos al comando físico correspondiente que debe ejecutar el M4:

    access_granted  →  OPEN   (abrir barrera)
    access_denied   →  (sin acción física; solo log y confirmación)
    barrier_command →  OPEN | CLOSE | STOP  (comandos directos del orquestador)

  También recibe las respuestas del M4 vía RPMsg y las publica de vuelta
  al bus MQTT como eventos barrier_opened, barrier_closed o hardware_fault.

Flujo completo:
    MQTT access_granted
          ↓
    CommandDispatcher.on_access_decision()
          ↓
    RPMsgClient.send_command("OPEN", trace_id)
          ↓
    M4 ejecuta apertura física
          ↓
    RPMsgClient recibe "OPEN:OK:<trace_id>"
          ↓
    CommandDispatcher._on_m4_response()
          ↓
    MQTT barrier_opened (publicado al bus)
"""

import logging
from typing import Any, Dict

from services.common.event_bus import EventBus
from services.common.event_models import Topics
from services.hardware_controller.app.rpmsg_client import RPMsgClient

logger = logging.getLogger(__name__)

# Acciones RPMsg que el firmware M4 entiende (acordadas con Integrante A)
_ACTION_OPEN  = "OPEN"
_ACTION_CLOSE = "CLOSE"
_ACTION_STOP  = "STOP"

# Tópico MQTT interno para comandos directos de barrera desde el orquestador
_BARRIER_COMMAND_TOPIC = Topics.BARRIER_COMMAND


class CommandDispatcher:
    """
    Puente entre el bus MQTT y el firmware del M4.

    Suscribe los tópicos relevantes del bus, despacha comandos al M4
    y publica los eventos de confirmación de vuelta al bus.
    """

    def __init__(self, event_bus: EventBus, rpmsg_client: RPMsgClient) -> None:
        """
        Args:
            event_bus:     Instancia ya conectada del EventBus compartido.
            rpmsg_client:  Instancia ya abierta del RPMsgClient.
        """
        self.bus    = event_bus
        self.rpmsg  = rpmsg_client

        # Registrar callback para respuestas asíncronas del M4
        self.rpmsg.set_message_callback(self._on_m4_response)

        # Suscribir tópicos MQTT relevantes
        self.bus.subscribe(Topics.ACCESS_GRANTED,  self._on_access_granted)
        self.bus.subscribe(Topics.ACCESS_DENIED,   self._on_access_denied)
        self.bus.subscribe(_BARRIER_COMMAND_TOPIC, self._on_barrier_command)

        logger.info("CommandDispatcher initialized and subscriptions registered.")

    # -----------------------------------------------------------------------
    # Handlers de eventos MQTT → comandos al M4
    # -----------------------------------------------------------------------

    def _on_access_granted(self, envelope: Dict[str, Any]) -> None:
        """
        Evento: access_granted  →  comando OPEN al M4.

        Payload esperado (del orquestador):
            { "plate": "ABC-123", "decision": "ACCESS_GRANTED",
              "reason": "whitelist" | "payment_approved" }
        """
        trace_id = envelope.get("trace_id", "unknown")
        plate    = envelope.get("payload", {}).get("plate", "?")
        reason   = envelope.get("payload", {}).get("reason", "?")

        logger.info(
            "Access granted → sending OPEN to M4 | plate=%s reason=%s trace_id=%s",
            plate, reason, trace_id,
        )
        self._send_to_m4(_ACTION_OPEN, trace_id)

    def _on_access_denied(self, envelope: Dict[str, Any]) -> None:
        """
        Evento: access_denied  →  sin acción física (barrera permanece cerrada).
        Solo registra el evento para auditoría.
        """
        trace_id = envelope.get("trace_id", "unknown")
        plate    = envelope.get("payload", {}).get("plate", "?")
        reason   = envelope.get("payload", {}).get("reason", "?")

        logger.info(
            "Access denied — no physical action | plate=%s reason=%s trace_id=%s",
            plate, reason, trace_id,
        )
        # La barrera ya está cerrada; no se envía nada al M4.

    def _on_barrier_command(self, envelope: Dict[str, Any]) -> None:
        """
        Evento: barrier_command  →  comando directo al M4 (OPEN/CLOSE/STOP).

        Permite al orquestador forzar el estado de la barrera independientemente
        de decisiones de acceso. Usado en modo asistido y override manual.

        Payload esperado:
            { "action": "OPEN" | "CLOSE" | "STOP",
              "source": "orchestrator" | "manual_override" }
        """
        trace_id = envelope.get("trace_id", "unknown")
        payload  = envelope.get("payload", {})
        action   = payload.get("action", "").upper()
        source   = payload.get("source", "unknown")

        if action not in (_ACTION_OPEN, _ACTION_CLOSE, _ACTION_STOP):
            logger.warning(
                "Unknown barrier action '%s' from '%s' — ignored | trace_id=%s",
                action, source, trace_id,
            )
            return

        logger.info(
            "Barrier command received → sending %s to M4 | source=%s trace_id=%s",
            action, source, trace_id,
        )
        self._send_to_m4(action, trace_id)

    # -----------------------------------------------------------------------
    # Handler de respuestas del M4 → eventos MQTT
    # -----------------------------------------------------------------------

    def _on_m4_response(self, raw_message: str) -> None:
        """
        Callback invocado por RPMsgClient cuando llega un mensaje del M4.

        Protocolo de respuesta del M4 (acordado con Integrante A):
            "<ACTION>:OK:<trace_id>"     → acción completada con éxito
            "<ACTION>:FAULT:<trace_id>"  → fallo durante la acción
            "HARDWARE_FAULT:<reason>"    → fallo autónomo del M4 (obstáculo, etc.)

        Args:
            raw_message: Línea de texto recibida del M4 (sin '\\n').
        """
        parts = raw_message.split(":")

        # Fallo autónomo del M4 (no asociado a un comando específico)
        if parts[0] == "HARDWARE_FAULT":
            reason = parts[1] if len(parts) > 1 else "unknown"
            logger.error("M4 hardware fault reported | reason=%s", reason)
            self._publish_hardware_fault(reason)
            return

        # Respuesta a un comando (OPEN/CLOSE/STOP)
        if len(parts) < 3:
            logger.warning("Malformed M4 response: '%s' — ignored.", raw_message)
            return

        action, status, trace_id = parts[0], parts[1], parts[2]

        if status == "OK":
            self._publish_barrier_event(action, trace_id)
        elif status == "FAULT":
            logger.error(
                "M4 command failed | action=%s trace_id=%s", action, trace_id
            )
            self._publish_hardware_fault(
                reason=f"{action}_failed", trace_id=trace_id
            )
        else:
            logger.warning(
                "Unknown M4 status '%s' for action '%s' — ignored.", status, action
            )

    # -----------------------------------------------------------------------
    # Publicación de eventos de confirmación al bus MQTT
    # -----------------------------------------------------------------------

    def _publish_barrier_event(self, action: str, trace_id: str) -> None:
        """Publica barrier_opened o barrier_closed según la acción confirmada por el M4."""
        if action == _ACTION_OPEN:
            topic      = Topics.BARRIER_COMMAND   # reutilizamos el tópico de comandos
            event_type = "barrier_opened"
        elif action == _ACTION_CLOSE:
            topic      = Topics.BARRIER_COMMAND
            event_type = "barrier_closed"
        else:
            logger.debug("No barrier event to publish for action '%s'.", action)
            return

        self.bus.publish(
            topic=topic,
            payload={"action": action, "status": "confirmed", "domain": "mcu"},
            event_type=event_type,
            trace_id=trace_id,
        )
        logger.info(
            "%s confirmed by M4 | trace_id=%s", event_type, trace_id
        )

    def _publish_hardware_fault(
        self, reason: str, trace_id: str = "autonomous"
    ) -> None:
        """Publica hardware_fault al bus para que el orquestador active el modo seguro."""
        self.bus.publish(
            topic=Topics.BARRIER_COMMAND,
            payload={"reason": reason, "domain": "mcu", "source": "m4_firmware"},
            event_type="hardware_fault",
            trace_id=trace_id,
        )
        logger.critical(
            "hardware_fault published | reason=%s trace_id=%s", reason, trace_id
        )

    # -----------------------------------------------------------------------
    # Helpers internos
    # -----------------------------------------------------------------------

    def _send_to_m4(self, action: str, trace_id: str) -> None:
        """Envía un comando al M4 con manejo de errores centralizado."""
        try:
            self.rpmsg.send_command(action, trace_id)
        except (OSError, RuntimeError) as exc:
            logger.error(
                "Failed to send command to M4 | action=%s trace_id=%s error=%s",
                action, trace_id, exc,
            )
            self._publish_hardware_fault(
                reason=f"rpmsg_write_error:{action}", trace_id=trace_id
            )
