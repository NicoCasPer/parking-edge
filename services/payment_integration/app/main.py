"""
main.py — Servicio de integración de pagos.

Responsabilidades:
  - Escucha eventos MQTT plate_read para cobrar acceso.
  - Usa PaymentClient (circuit breaker + store-and-forward) para tolerar fallas.
  - Reconcilia periódicamente pagos encolados.
  - Publica payment_ok / payment_failed en MQTT.

Variables de entorno:
    MQTT_BROKER_HOST        — default: localhost
    MQTT_BROKER_PORT        — default: 1883
    PAYMENT_PROVIDER_URL    — URL del proveedor de pagos
    PAYMENT_API_KEY         — API key del proveedor
    PAYMENT_STORE_PATH      — ruta SQLite para cola local
    MOCK_PAYMENT_SERVER     — "true" para usar mock en puerto 5050
    CB_FAIL_THRESHOLD       — fallos para abrir CB (default: 5)
    CB_RESET_TIMEOUT_S      — segundos OPEN antes de HALF_OPEN (default: 30)
    RECONCILE_INTERVAL_S    — segundos entre reconciliaciones (default: 60)
    LOG_LEVEL               — default: INFO
"""

import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Dict

from services.common.event_bus import EventBus
from services.common.event_models import Topics
from services.payment_integration.app.circuit_breaker import CircuitBreaker
from services.payment_integration.app.local_store import LocalPaymentStore
from services.payment_integration.app.payment_client import PaymentClient

logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("payment-integration")

_RECONCILE_INTERVAL_S = float(os.getenv("RECONCILE_INTERVAL_S", "60.0"))

_running    = True
_stop_event = threading.Event()


def _handle_shutdown(signum, frame) -> None:
    global _running
    logger.info("Señal de cierre recibida (%s).", signum)
    _running = False
    _stop_event.set()


def _make_plate_read_handler(client: PaymentClient, bus: EventBus):
    def _on_plate_read(envelope: Dict[str, Any]) -> None:
        trace_id = envelope.get("trace_id", "unknown")
        payload  = envelope.get("payload", {})
        plate    = payload.get("plate", "")
        status   = payload.get("status", "")

        # Solo procesamos placas leídas exitosamente
        if status != "plate_read":
            logger.debug("plate_read ignorado (status=%s) | trace_id=%s", status, trace_id)
            return

        amount_cop = int(os.getenv("PARKING_FEE_COP", "5000"))
        logger.info("Cobrando acceso | plate=%s amount=%d trace_id=%s",
                    plate, amount_cop, trace_id)

        def _charge_worker() -> None:
            result = client.charge(
                trace_id=trace_id,
                plate=plate,
                amount_cop=amount_cop,
                metadata={"lane_id": payload.get("lane_id", "")},
            )

            event_type = "payment_ok" if result["status"] in ("ok", "duplicate") else "payment_failed"
            try:
                bus.publish(
                    topic=Topics.PAYMENT_EVENT,
                    payload={
                        "plate":  plate,
                        "status": result["status"],
                        "result": result,
                    },
                    event_type=event_type,
                    trace_id=trace_id,
                )
            except Exception as exc:
                logger.error("Error publicando %s: %s", event_type, exc)

        t = threading.Thread(target=_charge_worker, daemon=True,
                             name=f"payment-worker-{trace_id}")
        t.start()

    return _on_plate_read


def _reconcile_loop(client: PaymentClient) -> None:
    """Reintenta pagos encolados periódicamente."""
    logger.info("Loop de reconciliación iniciado | interval=%.0fs", _RECONCILE_INTERVAL_S)
    while not _stop_event.wait(timeout=_RECONCILE_INTERVAL_S):
        try:
            n = client.reconcile_pending()
            if n:
                logger.info("Reconciliación: %d pagos conciliados.", n)
        except Exception as exc:
            logger.warning("Error en reconciliación: %s", exc)
    logger.info("Loop de reconciliación detenido.")


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT,  _handle_shutdown)

    logger.info("payment-integration iniciando...")

    # 1. Cola local (store-and-forward)
    store = LocalPaymentStore()
    store.connect()

    # 2. Circuit breaker (configuración desde env)
    cb = CircuitBreaker(
        fail_threshold=int(os.getenv("CB_FAIL_THRESHOLD", "5")),
        reset_timeout_s=float(os.getenv("CB_RESET_TIMEOUT_S", "30.0")),
        name="payment-provider",
    )

    # 3. Cliente de pagos
    client = PaymentClient(store=store, circuit_breaker=cb)

    # 4. Bus de eventos MQTT
    bus = EventBus(service_name="payment-integration")
    try:
        bus.connect(max_retries=5)
    except ConnectionError as exc:
        logger.critical("No se puede conectar al broker MQTT: %s — abortando.", exc)
        sys.exit(1)

    # 5. Suscribirse a plate_read
    bus.subscribe(Topics.PLATE_READ, _make_plate_read_handler(client, bus))

    # 6. Hilo de reconciliación
    rec_thread = threading.Thread(
        target=_reconcile_loop,
        args=(client,),
        daemon=True,
        name="payment-reconcile",
    )
    rec_thread.start()

    logger.info("payment-integration listo | reconcile_interval=%.0fs", _RECONCILE_INTERVAL_S)

    try:
        while _running:
            time.sleep(1.0)
    finally:
        logger.info("Cerrando payment-integration...")
        _stop_event.set()
        rec_thread.join(timeout=5.0)
        bus.disconnect()
        logger.info("payment-integration detenido.")


if __name__ == "__main__":
    main()
