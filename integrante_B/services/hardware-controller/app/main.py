"""
main.py — Punto de entrada del servicio hardware-controller.

Responsabilidad:
  Arrancar y mantener el ciclo de vida del servicio:
    1. Conectar el EventBus al broker MQTT.
    2. Abrir el canal RPMsg hacia el M4.
    3. Instanciar el CommandDispatcher que conecta ambos.
    4. Mantenerse en ejecución bajo supervisión de systemd.
    5. Cerrar limpiamente ante SIGTERM / SIGINT.

Ejecutar:
    python -m app.main            (desde services/hardware-controller/)
    systemctl start hardware-controller.service

Variables de entorno relevantes:
    MQTT_BROKER_HOST   — default: localhost
    MQTT_BROKER_PORT   — default: 1883
    RPMSG_DEVICE       — default: /dev/rpmsg0
    RPMSG_SIMULATED    — "true" para desarrollo sin BeaglePlay
    LANE_ID            — Identificador del carril (default: ENTRADA-1)
"""

import logging
import os
import signal
import sys
import time

from services.common.event_bus import EventBus
from services.hardware_controller.app.command_dispatcher import CommandDispatcher
from services.hardware_controller.app.rpmsg_client import RPMsgClient

# ---------------------------------------------------------------------------
# Logging estructurado — compatible con systemd/journald
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("hardware-controller")

# ---------------------------------------------------------------------------
# Estado global del servicio (para el signal handler)
# ---------------------------------------------------------------------------
_running = True


def _handle_shutdown(signum, frame) -> None:
    """Captura SIGTERM y SIGINT para un apagado limpio."""
    global _running
    logger.info("Shutdown signal received (%s) — stopping service.", signum)
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT,  _handle_shutdown)

    logger.info("hardware-controller service starting...")

    lane_id = os.getenv("LANE_ID", "ENTRADA-1")

    # --- 1. Bus de eventos MQTT ---
    bus = EventBus(service_name="hardware-controller")
    try:
        bus.connect(max_retries=5)
    except ConnectionError as exc:
        logger.critical("Cannot connect to MQTT broker: %s — aborting.", exc)
        sys.exit(1)

    # --- 2. Canal RPMsg hacia el M4 ---
    rpmsg = RPMsgClient()
    try:
        rpmsg.open()
    except OSError as exc:
        logger.critical("Cannot open RPMsg device: %s — aborting.", exc)
        bus.disconnect()
        sys.exit(1)

    # --- 3. Dispatcher: conecta bus ↔ M4 ---
    dispatcher = CommandDispatcher(event_bus=bus, rpmsg_client=rpmsg)  # noqa: F841

    logger.info(
        "hardware-controller ready | lane=%s rpmsg=%s simulated=%s",
        lane_id, rpmsg.device, rpmsg._simulated,
    )

    # --- 4. Bucle principal — systemd mantiene vivo el proceso ---
    try:
        while _running:
            time.sleep(1.0)
    finally:
        logger.info("Shutting down hardware-controller...")
        rpmsg.close()
        bus.disconnect()
        logger.info("hardware-controller stopped cleanly.")


if __name__ == "__main__":
    main()
