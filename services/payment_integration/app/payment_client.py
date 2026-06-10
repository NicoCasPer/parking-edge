"""
payment_client.py — Cliente HTTPS para el proveedor externo de pagos.

Implementa:
  - Idempotencia por trace_id (RF-16): evita cargos duplicados.
  - Circuit breaker (RF-17): falla rápido cuando el proveedor está caído.
  - Store-and-forward (RF-18/19): encola localmente si el CB está OPEN.
  - Reintento con backoff exponencial: 1s, 2s, 4s.

Variables de entorno:
    PAYMENT_PROVIDER_URL  — URL base del proveedor (obligatoria en producción)
    PAYMENT_API_KEY       — API key del proveedor (obligatoria en producción)
    PAYMENT_TIMEOUT_S     — timeout por petición en segundos (default: 5.0)
    MOCK_PAYMENT_SERVER   — "true" para usar servidor local de prueba en puerto 5050
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.payment_integration.app.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
)
from services.payment_integration.app.local_store import LocalPaymentStore

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER_URL = "http://localhost:5050"  # mock por defecto
_PAYMENT_TIMEOUT_S    = float(os.getenv("PAYMENT_TIMEOUT_S", "5.0"))
_MAX_RETRIES          = 3


def _build_provider_url() -> str:
    if os.getenv("MOCK_PAYMENT_SERVER", "").lower() in ("true", "1", "yes"):
        return "http://localhost:5050"
    url = os.getenv("PAYMENT_PROVIDER_URL", "")
    if not url:
        logger.warning("PAYMENT_PROVIDER_URL no configurada — usando mock en localhost:5050")
        return _DEFAULT_PROVIDER_URL
    return url.rstrip("/")


class PaymentClient:
    """
    Cliente de pagos con circuit breaker, idempotencia y store-and-forward.

    Uso típico (desde payment-integration/app/main.py):
        client = PaymentClient(store=store, circuit_breaker=cb)
        result = client.charge(trace_id="...", plate="ABC123", amount_cop=5000)
    """

    def __init__(
        self,
        store:           LocalPaymentStore,
        circuit_breaker: CircuitBreaker,
        provider_url:    Optional[str] = None,
    ) -> None:
        self.store       = store
        self.cb          = circuit_breaker
        self.base_url    = provider_url or _build_provider_url()
        self._api_key    = os.getenv("PAYMENT_API_KEY", "dev-key")

        logger.info(
            "PaymentClient listo | url=%s cb=%s",
            self.base_url, self.cb.name,
        )

    def charge(
        self,
        trace_id:   str,
        plate:      str,
        amount_cop: int,
        metadata:   Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Cobra un pago al proveedor externo.

        Flujo:
          1. Si ya fue procesado (is_duplicate), retorna éxito sin volver a cobrar.
          2. Si el CB está OPEN, encola localmente (store-and-forward).
          3. Intenta la llamada HTTPS con hasta 3 reintentos (backoff 1s/2s/4s).
          4. En éxito: marca procesado en store.
          5. En fallo final: encola localmente para conciliación posterior.

        Returns:
            {"status": "ok"|"queued"|"duplicate", "trace_id": ..., ...}
        """
        # Idempotencia: no volver a cobrar
        if self.store.is_duplicate(trace_id):
            logger.info("Pago duplicado ignorado | trace_id=%s", trace_id)
            return {"status": "duplicate", "trace_id": trace_id}

        event = {
            "trace_id":   trace_id,
            "plate":      plate,
            "amount_cop": amount_cop,
            **(metadata or {}),
        }

        # Store-and-forward si el CB está OPEN
        from services.payment_integration.app.circuit_breaker import CBState
        if self.cb.state == CBState.OPEN:
            logger.warning("CB OPEN — pago encolado localmente | trace_id=%s", trace_id)
            self.store.enqueue(event)
            return {"status": "queued", "trace_id": trace_id}

        # Intentar cobro con backoff
        last_exc: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = self.cb.call(lambda: self._http_charge(trace_id, plate, amount_cop))
                self.store.mark_processed(trace_id)
                logger.info(
                    "Pago exitoso | trace_id=%s plate=%s amount=%d attempt=%d",
                    trace_id, plate, amount_cop, attempt,
                )
                return {"status": "ok", "trace_id": trace_id, **result}
            except CircuitBreakerOpen as exc:
                logger.warning("CB abierto durante intento %d | trace_id=%s", attempt, trace_id)
                last_exc = exc
                break
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    wait = 2 ** (attempt - 1)  # 1s, 2s
                    logger.warning(
                        "Intento %d/%d falló | trace_id=%s error=%s — reintentando en %ds",
                        attempt, _MAX_RETRIES, trace_id, exc, wait,
                    )
                    time.sleep(wait)

        # Todos los intentos fallaron → encolar
        logger.error(
            "Pago fallido tras %d intentos — encolando | trace_id=%s error=%s",
            _MAX_RETRIES, trace_id, last_exc,
        )
        self.store.enqueue(event)
        return {"status": "queued", "trace_id": trace_id, "error": str(last_exc)}

    def reconcile_pending(self) -> int:
        """
        Reintenta pagar los eventos encolados.
        Llámalo periódicamente desde el loop del servicio.

        Returns:
            Número de eventos conciliados exitosamente.
        """
        pending = self.store.get_pending(limit=20)
        if not pending:
            return 0

        logger.info("Reconciliación: %d pagos pendientes.", len(pending))
        reconciled = 0
        for row in pending:
            trace_id = row["trace_id"]
            try:
                self.cb.call(
                    lambda: self._http_charge(
                        trace_id, row.get("plate", ""), row.get("amount_cop", 0)
                    )
                )
                self.store.mark_processed(trace_id)
                reconciled += 1
                logger.info("Pago conciliado | trace_id=%s", trace_id)
            except CircuitBreakerOpen:
                logger.warning("CB OPEN — reconciliación detenida.")
                break
            except Exception as exc:
                logger.warning("Conciliación fallida | trace_id=%s error=%s", trace_id, exc)

        return reconciled

    def _http_charge(self, trace_id: str, plate: str, amount_cop: int) -> Dict[str, Any]:
        """Petición HTTPS al proveedor. Lanza excepción en cualquier error."""
        payload = json.dumps({
            "idempotency_key": trace_id,
            "plate":           plate,
            "amount_cop":      amount_cop,
            "currency":        "COP",
        }).encode("utf-8")

        req = Request(
            url=f"{self.base_url}/v1/charge",
            data=payload,
            method="POST",
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "X-Trace-Id":    trace_id,
            },
        )

        try:
            with urlopen(req, timeout=_PAYMENT_TIMEOUT_S) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body
        except HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body_text}") from exc
        except URLError as exc:
            raise RuntimeError(f"URLError: {exc.reason}") from exc
        except Exception as exc:
            raise RuntimeError(f"Error inesperado al cobrar: {exc}") from exc
