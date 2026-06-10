"""
main.py — Punto de entrada del servicio access-orchestrator.

Responsabilidad:
  Arrancar y mantener el ciclo de vida del servicio:
    1. Cargar políticas desde policies.yaml.
    2. Conectar el EventBus al broker MQTT.
    3. Conectar a la base de datos SQLite.
    4. Instanciar el Orchestrator que suscribe los eventos y toma decisiones.
    5. Mantenerse en ejecución bajo supervisión de systemd.
    6. Cerrar limpiamente ante SIGTERM / SIGINT.

Ejecutar:
    python -m app.main            (desde services/access-orchestrator/)
    systemctl start access-orchestrator.service

Variables de entorno relevantes:
    MQTT_BROKER_HOST  — default: localhost
    MQTT_BROKER_PORT  — default: 1883
    POLICIES_PATH     — default: config/policies.yaml
    DATABASE_PATH     — default: /var/lib/parking/parking.db
    LOG_LEVEL         — default: INFO
"""

import logging
import os
import signal
import sys
import time

from services.common.event_bus import EventBus
from services.access_orchestrator.app.orchestrator import Orchestrator
from services.access_orchestrator.app.policies import Policies

# ---------------------------------------------------------------------------
# Logging estructurado — compatible con systemd/journald
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("access-orchestrator")

_running = True


def _handle_shutdown(signum, frame) -> None:
    global _running
    logger.info("Shutdown signal received (%s) — stopping service.", signum)
    _running = False


def _load_database():
    """
    Importa y retorna la instancia de database.py del Integrante A.

    Importación diferida para que el servicio arranque aunque database.py
    no esté disponible durante el desarrollo (falla en runtime, no en import).
    """
    try:
        from services.common.database import Database
        db_path = os.getenv("DATABASE_PATH", "/var/lib/parking/parking.db")
        db = Database(db_path)
        db.connect()
        logger.info("Database connected | path=%s", db_path)
        return db
    except ImportError:
        logger.critical(
            "services/common/database.py not found. "
            "This module must be provided by Integrante A."
        )
        sys.exit(1)
    except Exception as exc:
        logger.critical("Failed to connect to database: %s", exc)
        sys.exit(1)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT,  _handle_shutdown)

    logger.info("access-orchestrator service starting...")

    # --- 1. Políticas ---
    policies_path = os.getenv("POLICIES_PATH", "config/policies.yaml")
    policies = Policies.load(policies_path)
    logger.info("Policies loaded | mode=%s", policies.default_mode)

    # --- 2. Bus de eventos MQTT ---
    bus = EventBus(service_name="access-orchestrator")
    try:
        bus.connect(max_retries=5)
    except ConnectionError as exc:
        logger.critical("Cannot connect to MQTT broker: %s — aborting.", exc)
        sys.exit(1)

    # --- 3. Base de datos ---
    database = _load_database()

    # --- 4. Orquestador ---
    orchestrator = Orchestrator(          # noqa: F841
        event_bus=bus,
        database=database,
        policies=policies,
    )

    logger.info("access-orchestrator ready and listening for events.")

    # --- 5. Bucle principal ---
    try:
        while _running:
            time.sleep(1.0)
    finally:
        logger.info("Shutting down access-orchestrator...")
        bus.disconnect()
        logger.info("access-orchestrator stopped cleanly.")


if __name__ == "__main__":
    main()
