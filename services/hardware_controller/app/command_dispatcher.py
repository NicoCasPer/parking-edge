"""
command_dispatcher.py — Traductor de eventos MQTT ↔ comandos RPMsg para el M4.

Correcciones respecto a integrante_B:
  - Maneja correctamente el mensaje "PRESENCE_DETECTED" del M4 y lo publica
    en MQTT como parking/events/presence_detected (antes era ignorado como
    mensaje "malformado" por no tener formato ACTION:STATUS:trace_id).
  - El heartbeat periódico hacia el M4 se gestiona en main.py (hilo dedicado)
    y no en este dispatcher.

Flujo:
    M4 → "PRESENCE_DETECTED"            → MQTT presence_detected
    MQTT access_granted                  → M4 "OPEN:<trace_id>"
    MQTT barrier_command (OPEN/CLOSE/STOP) → M4 "<ACTION>:<trace_id>"
    M4 "OPEN:OK:<trace_id>"              → MQTT barrier_opened
    M4 "HARDWARE_FAULT:<reason>"         → MQTT hardware_fault
"""

import logging
from typing import Any, Dict

from services.common.event_bus import EventBus
from services.common.event_models import Topics
from services.hardware_controller.app.rpmsg_client import RPMsgClient

logger = logging.getLogger(__name__)

_ACTION_OPEN  = "OPEN"
_ACTION_CLOSE = "CLOSE"
_ACTION_STOP  = "STOP"


class CommandDispatcher:
    """Puente entre bus MQTT y firmware M4 vía RPMsg."""

    def __init__(self, event_bus: EventBus, rpmsg_client: RPMsgClient) -> None:
        self.bus   = event_bus
        self.rpmsg = rpmsg_client

        self.rpmsg.set_message_callback(self._on_m4_message)

        self.bus.subscribe(Topics.ACCESS_GRANTED,  self._on_access_granted)
        self.bus.subscribe(Topics.ACCESS_DENIED,   self._on_access_denied)
        self.bus.subscribe(Topics.BARRIER_COMMAND, self._on_barrier_command)

        logger.info("CommandDispatcher listo. Suscripciones registradas.")

    # -----------------------------------------------------------------------
    # MQTT → M4
    # -----------------------------------------------------------------------

    def _on_access_granted(self, envelope: Dict[str, Any]) -> None:
        trace_id = envelope.get("trace_id", "unknown")
        plate    = envelope.get("payload", {}).get("plate", "?")
        reason   = envelope.get("payload", {}).get("reason", "?")
        logger.info("access_granted → OPEN M4 | plate=%s reason=%s trace_id=%s",
                    plate, reason, trace_id)
        self._send_to_m4(_ACTION_OPEN, trace_id)

    def _on_access_denied(self, envelope: Dict[str, Any]) -> None:
        trace_id = envelope.get("trace_id", "unknown")
        plate    = envelope.get("payload", {}).get("plate", "?")
        logger.info("access_denied — sin acción física | plate=%s trace_id=%s",
                    plate, trace_id)

    def _on_barrier_command(self, envelope: Dict[str, Any]) -> None:
        trace_id = envelope.get("trace_id", "unknown")
        payload  = envelope.get("payload", {})
        action   = payload.get("action", "").upper()
        source   = payload.get("source", "unknown")

        if action not in (_ACTION_OPEN, _ACTION_CLOSE, _ACTION_STOP):
            logger.warning("Acción de barrera desconocida '%s' — ignorada | trace_id=%s",
                           action, trace_id)
            return

        logger.info("barrier_command → %s M4 | source=%s trace_id=%s",
                    action, source, trace_id)
        self._send_to_m4(action, trace_id)

    # -----------------------------------------------------------------------
    # M4 → MQTT
    # -----------------------------------------------------------------------

    def _on_m4_message(self, raw_message: str) -> None:
        """
        Callback para todos los mensajes entrantes del M4.

        Casos soportados:
          "PRESENCE_DETECTED"          → publica presence_detected en MQTT
          "HARDWARE_FAULT:<reason>"    → publica hardware_fault
          "<ACTION>:OK:<trace_id>"     → publica barrier_opened/closed
          "<ACTION>:FAULT:<trace_id>"  → publica hardware_fault
        """
        # Evento autónomo de presencia de vehículo
        if raw_message.strip() == "PRESENCE_DETECTED":
            logger.info("M4 detectó vehículo → publicando presence_detected")
            self._publish_presence_detected()
            return

        parts = raw_message.split(":")

        # Fallo autónomo del M4
        if parts[0] == "HARDWARE_FAULT":
            reason = parts[1] if len(parts) > 1 else "unknown"
            logger.error("hardware_fault reportado por M4 | reason=%s", reason)
            self._publish_hardware_fault(reason)
            return

        # Respuesta a un comando (ACTION:STATUS:trace_id)
        if len(parts) < 3:
            logger.warning("Mensaje M4 no reconocido: '%s' — ignorado.", raw_message)
            return

        action, status, trace_id = parts[0], parts[1], ":".join(parts[2:])
        if status == "OK":
            self._publish_barrier_event(action, trace_id)
        elif status == "FAULT":
            logger.error("Comando M4 falló | action=%s trace_id=%s", action, trace_id)
            self._publish_hardware_fault(f"{action}_failed", trace_id)
        else:
            logger.warning("Estado M4 desconocido '%s' para '%s' — ignorado.",
                           status, action)

    # -----------------------------------------------------------------------
    # Publicación MQTT
    # -----------------------------------------------------------------------

    def _publish_presence_detected(self) -> None:
        """Publica parking/events/presence_detected para que vision-service arranque."""
        try:
            self.bus.publish(
                topic=Topics.PRESENCE_DETECTED,
                payload={"domain": "mcu", "source": "m4_sensor"},
                event_type="presence_detected",
            )
        except Exception as exc:
            logger.error("Error publicando presence_detected: %s", exc)

    def _publish_barrier_event(self, action: str, trace_id: str) -> None:
        if action == _ACTION_OPEN:
            event_type = "barrier_opened"
        elif action == _ACTION_CLOSE:
            event_type = "barrier_closed"
        else:
            return
        try:
            self.bus.publish(
                topic=Topics.BARRIER_COMMAND,
                payload={"action": action, "status": "confirmed", "domain": "mcu"},
                event_type=event_type,
                trace_id=trace_id,
            )
            logger.info("%s confirmado por M4 | trace_id=%s", event_type, trace_id)
        except Exception as exc:
            logger.error("Error publicando %s: %s", event_type, exc)

    def _publish_hardware_fault(
        self, reason: str, trace_id: str = "autonomous"
    ) -> None:
        try:
            self.bus.publish(
                topic=Topics.BARRIER_COMMAND,
                payload={"reason": reason, "domain": "mcu", "source": "m4_firmware"},
                event_type="hardware_fault",
                trace_id=trace_id,
            )
            logger.critical("hardware_fault | reason=%s trace_id=%s", reason, trace_id)
        except Exception as exc:
            logger.error("Error publicando hardware_fault: %s", exc)

    def _send_to_m4(self, action: str, trace_id: str) -> None:
        try:
            self.rpmsg.send_command(action, trace_id)
        except Exception as exc:
            logger.error("Error enviando comando M4 | action=%s trace_id=%s error=%s",
                         action, trace_id, exc)
            self._publish_hardware_fault(f"rpmsg_write_error:{action}", trace_id)
