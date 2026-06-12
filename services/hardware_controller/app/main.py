"""
main.py — Punto de entrada del hardware-controller.

Transporte hacia los GPIOs: UART hacia el ESP32 WROOM-32 (SerialClient), que
reemplaza al antiguo M4/RPMsg. Para volver al M4 bastaría con reinstanciar
RPMsgClient (la interfaz es idéntica).

Detalles:
  - Hilo dedicado de heartbeat que envía "HEARTBEAT" al ESP32 cada
    HEARTBEAT_INTERVAL_S segundos (default 1.0). Este hilo es independiente
    del loop principal y del procesamiento MQTT, garantizando que el watchdog
    del ESP32 siempre reciba latidos aunque Linux esté ocupado.

Variables de entorno:
    MQTT_BROKER_HOST        — default: localhost
    MQTT_BROKER_PORT        — default: 1883
    UART_DEVICE             — default: /dev/ttyS2
    UART_BAUDRATE           — default: 115200
    UART_SIMULATED          — "true" para desarrollo sin ESP32
    HEARTBEAT_INTERVAL_S    — segundos entre heartbeats al ESP32 (default: 1.0)
    LANE_ID                 — default: ENTRADA-1
    LOG_LEVEL               — default: INFO
"""

import logging
import os
import signal
import sys
import threading
import time

from services.common.event_bus import EventBus
from services.hardware_controller.app.command_dispatcher import CommandDispatcher
from services.hardware_controller.app.serial_client import SerialClient

logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("hardware-controller")

_HEARTBEAT_INTERVAL_S = float(os.getenv("HEARTBEAT_INTERVAL_S", "1.0"))

_running     = True
_stop_event  = threading.Event()


def _handle_shutdown(signum, frame) -> None:
    global _running
    logger.info("Señal de cierre recibida (%s).", signum)
    _running = False
    _stop_event.set()


def _heartbeat_loop(link: SerialClient) -> None:
    """
    Hilo dedicado: envía HEARTBEAT al ESP32 cada HEARTBEAT_INTERVAL_S segundos.
    Garantiza que el watchdog del ESP32 recibe latidos aunque el procesamiento
    de visión o MQTT esté ocupado.
    """
    logger.info("Heartbeat hacia ESP32 iniciado | interval=%.1fs", _HEARTBEAT_INTERVAL_S)
    while not _stop_event.wait(timeout=_HEARTBEAT_INTERVAL_S):
        try:
            link.send_command("HEARTBEAT", "heartbeat")
        except Exception as exc:
            logger.warning("Error enviando HEARTBEAT al ESP32: %s", exc)
    logger.info("Hilo de heartbeat detenido.")


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT,  _handle_shutdown)

    logger.info("hardware-controller iniciando...")

    lane_id = os.getenv("LANE_ID", "ENTRADA-1")

    # 1. Bus de eventos MQTT
    bus = EventBus(service_name="hardware-controller")
    try:
        bus.connect(max_retries=5)
    except ConnectionError as exc:
        logger.critical("No se puede conectar al broker MQTT: %s — abortando.", exc)
        sys.exit(1)

    # 2. Canal UART hacia el ESP32
    link = SerialClient()
    try:
        link.open()
    except OSError as exc:
        logger.critical("No se puede abrir el UART: %s — abortando.", exc)
        bus.disconnect()
        sys.exit(1)

    # 3. Dispatcher: conecta bus ↔ ESP32 (la interfaz es la misma que RPMsgClient)
    _dispatcher = CommandDispatcher(event_bus=bus, rpmsg_client=link)

    # 4. Hilo de heartbeat hacia el ESP32 (independiente del loop principal)
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(link,),
        daemon=True,
        name="esp32-heartbeat",
    )
    hb_thread.start()

    logger.info(
        "hardware-controller listo | lane=%s device=%s simulated=%s",
        lane_id, link.device, link._simulated,
    )

    try:
        while _running:
            time.sleep(1.0)
    finally:
        logger.info("Cerrando hardware-controller...")
        _stop_event.set()
        hb_thread.join(timeout=3.0)
        link.close()
        bus.disconnect()
        logger.info("hardware-controller detenido.")


if __name__ == "__main__":
    main()
