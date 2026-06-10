"""
circuit_breaker.py — Circuit breaker para llamadas a proveedor externo de pagos.

Estados:
  CLOSED  — operación normal; las llamadas pasan al proveedor.
  OPEN    — demasiados fallos; las llamadas se rechazan localmente sin tocar el proveedor.
  HALF_OPEN — tras reset_timeout_s, permite un intento de prueba para verificar recuperación.

Configuración (de policies.yaml → circuit_breaker):
  fail_threshold  — fallos consecutivos para abrir el circuito (default 5)
  reset_timeout_s — segundos en OPEN antes de pasar a HALF_OPEN (default 30)
"""

import logging
import time
from enum import Enum
from threading import Lock
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CBState(Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpen(Exception):
    """Lanzada cuando el circuit breaker está OPEN y se intenta una llamada."""


class CircuitBreaker:
    """
    Circuit breaker por instancia (un CB por proveedor externo).

    Uso:
        cb = CircuitBreaker(fail_threshold=5, reset_timeout_s=30)
        try:
            result = cb.call(lambda: requests.get(...))
        except CircuitBreakerOpen:
            result = fallback_policy()
    """

    def __init__(
        self,
        fail_threshold:  int   = 5,
        reset_timeout_s: float = 30.0,
        name:            str   = "default",
    ) -> None:
        self.fail_threshold  = fail_threshold
        self.reset_timeout_s = reset_timeout_s
        self.name            = name

        self._state         = CBState.CLOSED
        self._failure_count = 0
        self._opened_at:    float = 0.0
        self._lock          = Lock()

        logger.info(
            "CircuitBreaker '%s' init | fail_threshold=%d reset_timeout=%.0fs",
            name, fail_threshold, reset_timeout_s,
        )

    @property
    def state(self) -> CBState:
        with self._lock:
            return self._state

    def call(self, fn: Callable[[], T]) -> T:
        """
        Ejecuta fn() si el circuito está CLOSED o HALF_OPEN.
        Actualiza el estado según el resultado.

        Args:
            fn: Callable sin argumentos que realiza la llamada externa.

        Returns:
            Resultado de fn().

        Raises:
            CircuitBreakerOpen: Si el circuito está OPEN.
            Exception:          Si fn() lanza una excepción (y registra el fallo).
        """
        with self._lock:
            if self._state == CBState.OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self.reset_timeout_s:
                    logger.info("CircuitBreaker '%s': OPEN → HALF_OPEN (elapsed=%.1fs)",
                                self.name, elapsed)
                    self._state = CBState.HALF_OPEN
                else:
                    raise CircuitBreakerOpen(
                        f"CircuitBreaker '{self.name}' is OPEN "
                        f"({elapsed:.1f}s/{self.reset_timeout_s}s elapsed)"
                    )

        try:
            result = fn()
            self._on_success()
            return result
        except CircuitBreakerOpen:
            raise
        except Exception as exc:
            self._on_failure(exc)
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CBState.HALF_OPEN:
                logger.info("CircuitBreaker '%s': HALF_OPEN → CLOSED (probe succeeded).",
                            self.name)
            self._state         = CBState.CLOSED
            self._failure_count = 0

    def _on_failure(self, exc: Exception) -> None:
        with self._lock:
            self._failure_count += 1
            logger.warning(
                "CircuitBreaker '%s' failure %d/%d: %s",
                self.name, self._failure_count, self.fail_threshold, exc,
            )
            if self._failure_count >= self.fail_threshold or self._state == CBState.HALF_OPEN:
                self._state     = CBState.OPEN
                self._opened_at = time.monotonic()
                logger.error(
                    "CircuitBreaker '%s': → OPEN (failures=%d)", self.name, self._failure_count
                )
