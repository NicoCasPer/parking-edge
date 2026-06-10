"""
parking-edge/services/connectivity-service/app/main.py

Punto de entrada del connectivity-service.
Responsabilidades:
  - Cargar ParkingPolicies desde la ruta indicada en la variable de
    entorno POLICIES_PATH (o el default del proyecto).
  - Instanciar y conectar EventBus al broker Mosquitto local.
  - Instanciar TelemetryService con las dependencias ya construidas.
  - Manejar SIGTERM / SIGINT para un apagado limpio (systemd lo usa).
  - Configurar logging estructurado antes de cualquier otra operación.

Variables de entorno reconocidas:
  POLICIES_PATH   Ruta al policies.yaml
                  Default: /opt/parking-edge/config/policies.yaml
  MQTT_HOST       Host del broker Mosquitto
                  Default: localhost
  MQTT_PORT       Puerto del broker
                  Default: 1883
  DISK_PATH       Partición a monitorear
                  Default: /
  LOG_LEVEL       Nivel de logging (DEBUG, INFO, WARNING, ERROR)
                  Default: INFO
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading

# ---------------------------------------------------------------------------
# Imports internos — rutas relativas al paquete app/
# ---------------------------------------------------------------------------
# Ajusta si tu PYTHONPATH apunta a otro nivel del árbol.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))

from event_bus import EventBus          # noqa: E402  (services/common/event_bus.py)
from telemetry import TelemetryService  # noqa: E402  (mismo paquete)

# ParkingPolicies vive en access-orchestrator; si no está en el path
# ajusta la siguiente línea o usa un import relativo según tu layout.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "access-orchestrator", "app"),
)
from policies import ParkingPolicies    # noqa: E402


# ---------------------------------------------------------------------------
# Constantes / defaults
# ---------------------------------------------------------------------------

SERVICE_NAME = "connectivity-service"

DEFAULT_POLICIES_PATH = "/opt/parking-edge/config/policies.yaml"
DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 1883
DEFAULT_DISK_PATH = "/"
DEFAULT_LOG_LEVEL = "INFO"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


logger = logging.getLogger(SERVICE_NAME)


# ---------------------------------------------------------------------------
# Señales de SO (SIGTERM / SIGINT)
# ---------------------------------------------------------------------------

class _ShutdownHandler:
    """
    Captura SIGTERM y SIGINT y activa un threading.Event que el bucle
    principal monitorea para detenerse limpiamente.
    """

    def __init__(self) -> None:
        self._stop_event = threading.Event()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def install(self) -> None:
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT, self._handle)

    def _handle(self, signum: int, frame) -> None:  # noqa: ANN001
        sig_name = signal.Signals(signum).name
        logger.info("[%s] Señal %s recibida — iniciando apagado", SERVICE_NAME, sig_name)
        self._stop_event.set()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def _read_env() -> dict:
    return {
        "policies_path": os.environ.get("POLICIES_PATH", DEFAULT_POLICIES_PATH),
        "mqtt_host":     os.environ.get("MQTT_HOST", DEFAULT_MQTT_HOST),
        "mqtt_port":     int(os.environ.get("MQTT_PORT", DEFAULT_MQTT_PORT)),
        "disk_path":     os.environ.get("DISK_PATH", DEFAULT_DISK_PATH),
        "log_level":     os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL),
    }


def main() -> int:
    """
    Punto de entrada principal.
    Retorna código de salida (0 = OK, 1 = error de arranque).
    """
    cfg = _read_env()
    _configure_logging(cfg["log_level"])

    logger.info("[%s] Arrancando — pid=%d", SERVICE_NAME, os.getpid())
    logger.info("[%s] policies_path=%s", SERVICE_NAME, cfg["policies_path"])
    logger.info("[%s] mqtt=%s:%d", SERVICE_NAME, cfg["mqtt_host"], cfg["mqtt_port"])

    # -- Manejador de señales -------------------------------------------------
    shutdown = _ShutdownHandler()
    shutdown.install()

    # -- Políticas -----------------------------------------------------------
    try:
        policies = ParkingPolicies(cfg["policies_path"])
    except Exception as exc:
        logger.critical(
            "[%s] No se pudo cargar policies.yaml: %s", SERVICE_NAME, exc,
            exc_info=True,
        )
        return 1

    # -- EventBus ------------------------------------------------------------
    try:
        bus = EventBus(
            host=cfg["mqtt_host"],
            port=cfg["mqtt_port"],
            client_id=f"{SERVICE_NAME}-telemetry",
        )
        bus.connect()
    except Exception as exc:
        logger.critical(
            "[%s] No se pudo conectar al broker MQTT (%s:%d): %s",
            SERVICE_NAME, cfg["mqtt_host"], cfg["mqtt_port"], exc,
            exc_info=True,
        )
        return 1

    # -- TelemetryService ----------------------------------------------------
    telemetry = TelemetryService(
        bus=bus,
        policies=policies,
        disk_path=cfg["disk_path"],
    )

    # -- Bucle principal (bloqueante hasta SIGTERM/SIGINT) -------------------
    logger.info(
        "[%s] Iniciando bucle de telemetría — intervalo=%ss",
        SERVICE_NAME,
        policies.heartbeat_interval_s,
    )
    try:
        telemetry.run_loop(stop_event=shutdown.stop_event)
    except Exception as exc:
        logger.critical(
            "[%s] Error inesperado en run_loop: %s", SERVICE_NAME, exc,
            exc_info=True,
        )
        return 1
    finally:
        # Desconexión limpia del broker aunque haya excepción
        try:
            bus.disconnect()
            logger.info("[%s] Desconectado del broker MQTT", SERVICE_NAME)
        except Exception as exc:
            logger.warning(
                "[%s] Error al desconectar del broker: %s", SERVICE_NAME, exc,
            )

    logger.info("[%s] Apagado limpio completado", SERVICE_NAME)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())