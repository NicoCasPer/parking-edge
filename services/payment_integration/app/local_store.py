"""
local_store.py — Cola local de eventos de pago pendientes (store-and-forward).

Cuando el proveedor externo no está disponible, los eventos de pago se
encolan en SQLite. Un worker los reintenta periódicamente y los concilia
cuando la conectividad se restablece.

Garantías:
  - Idempotencia por trace_id: un mismo evento no se procesa dos veces.
  - Persistencia ante reinicios del servicio (SQLite en disco).
  - Orden FIFO dentro de cada lote de conciliación.
"""

import logging
import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_STORE_PATH = os.getenv(
    "PAYMENT_STORE_PATH", "/var/lib/parking/payment_queue.db"
)


class LocalPaymentStore:
    """
    Cola persistente de pagos pendientes de conciliación.

    Uso:
        store = LocalPaymentStore("/var/lib/parking/payment_queue.db")
        store.connect()
        store.enqueue({"trace_id": "...", "plate": "ABC-123", "amount": 5000})
        pending = store.get_pending(limit=10)
        store.mark_processed("trace_id_aquí")
    """

    def __init__(self, path: str = _DEFAULT_STORE_PATH) -> None:
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        db_dir = os.path.dirname(self.path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False,
                                     isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._apply_schema()
        logger.info("LocalPaymentStore conectada | path=%s", self.path)

    def enqueue(self, event: Dict[str, Any]) -> None:
        """Encola un evento de pago si no existe ya (idempotencia por trace_id)."""
        trace_id = event.get("trace_id")
        if not trace_id:
            logger.warning("Evento de pago sin trace_id — descartado.")
            return

        self._conn.execute(
            """INSERT OR IGNORE INTO payment_queue
               (trace_id, plate, amount_cop, event_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                trace_id,
                event.get("plate"),
                event.get("amount_cop", 0),
                str(event),
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )
        logger.debug("Pago encolado | trace_id=%s plate=%s", trace_id, event.get("plate"))

    def get_pending(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retorna los primeros `limit` eventos pendientes (FIFO)."""
        cur = self._conn.execute(
            "SELECT * FROM payment_queue WHERE processed = 0 ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    def mark_processed(self, trace_id: str) -> None:
        """Marca un evento como procesado exitosamente."""
        self._conn.execute(
            "UPDATE payment_queue SET processed = 1, processed_at = ? WHERE trace_id = ?",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), trace_id),
        )
        logger.debug("Pago conciliado | trace_id=%s", trace_id)

    def is_duplicate(self, trace_id: str) -> bool:
        """Retorna True si el trace_id ya fue procesado (idempotencia)."""
        cur = self._conn.execute(
            "SELECT processed FROM payment_queue WHERE trace_id = ?", (trace_id,)
        )
        row = cur.fetchone()
        return row is not None and row["processed"] == 1

    def _apply_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS payment_queue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id     TEXT    NOT NULL UNIQUE,
                plate        TEXT,
                amount_cop   INTEGER DEFAULT 0,
                event_json   TEXT,
                processed    INTEGER DEFAULT 0,
                created_at   TEXT,
                processed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pq_processed ON payment_queue(processed, id);
        """)
