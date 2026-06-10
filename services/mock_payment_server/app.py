"""
app.py — Servidor mock de proveedor de pagos para desarrollo y pruebas.

Simula el endpoint POST /v1/charge con comportamiento configurable:
  - MOCK_PAYMENT_FAIL_RATE: probabilidad (0.0–1.0) de fallo aleatorio.
  - MOCK_PAYMENT_SLOW_MS:   latencia artificial en milisegundos.

Uso:
    python -m services.mock_payment_server.app
    # o desde docker-compose con MOCK_PAYMENT_SERVER=true
"""

import json
import logging
import os
import random
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [mock-payment] %(message)s",
)
logger = logging.getLogger("mock-payment")

_PORT          = int(os.getenv("MOCK_PAYMENT_PORT", "5050"))
_FAIL_RATE     = float(os.getenv("MOCK_PAYMENT_FAIL_RATE", "0.0"))
_SLOW_MS       = int(os.getenv("MOCK_PAYMENT_SLOW_MS", "0"))
_seen_keys: set = set()   # idempotencia en memoria (reset al reiniciar)


class PaymentHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args) -> None:
        logger.debug(fmt, *args)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/charge":
            self._respond(404, {"error": "Not found"})
            return

        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "Invalid JSON"})
            return

        idem_key   = data.get("idempotency_key", "")
        plate      = data.get("plate", "")
        amount_cop = data.get("amount_cop", 0)

        # Latencia artificial
        if _SLOW_MS > 0:
            time.sleep(_SLOW_MS / 1000.0)

        # Idempotencia
        if idem_key in _seen_keys:
            logger.info("Cargo duplicado ignorado | key=%s", idem_key)
            self._respond(200, {"status": "already_processed", "idempotency_key": idem_key})
            return

        # Fallo aleatorio simulado
        if _FAIL_RATE > 0 and random.random() < _FAIL_RATE:
            logger.warning("Fallo simulado | key=%s", idem_key)
            self._respond(503, {"error": "Service temporarily unavailable (simulated)"})
            return

        _seen_keys.add(idem_key)
        logger.info("Cargo aprobado | plate=%s amount=%d key=%s", plate, amount_cop, idem_key)
        self._respond(200, {
            "status":           "approved",
            "idempotency_key":  idem_key,
            "plate":            plate,
            "amount_cop":       amount_cop,
            "transaction_id":   f"mock-{idem_key[:8]}",
        })

    def _respond(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = HTTPServer(("0.0.0.0", _PORT), PaymentHandler)
    logger.info(
        "Mock payment server en puerto %d | fail_rate=%.0f%% slow=%dms",
        _PORT, _FAIL_RATE * 100, _SLOW_MS,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Mock payment server detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
