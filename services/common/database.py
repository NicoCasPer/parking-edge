"""
database.py — Acceso a la base de datos SQLite del parqueadero.

Implementa DatabaseProtocol (definido en access-orchestrator) con SQLite.
Todas las consultas usan parámetros enlazados para prevenir inyección SQL.

Variables de entorno:
    DATABASE_PATH  — ruta al archivo .db  (default: /var/lib/parking/parking.db)
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "/var/lib/parking/parking.db")


class Database:
    """
    Capa de acceso a SQLite para whitelist, pagos y auditoría de accesos.

    Uso:
        db = Database("/var/lib/parking/parking.db")
        db.connect()
        entry = db.get_whitelist("ABC-123")
        db.insert_event({...})
    """

    def __init__(self, path: str = _DEFAULT_DB_PATH) -> None:
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """
        Abre la conexión SQLite. Crea el directorio y aplica el schema inicial
        si la base de datos no existe todavía.

        Raises:
            sqlite3.Error: Si no se puede abrir el archivo.
        """
        db_dir = os.path.dirname(self.path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._conn = sqlite3.connect(
            self.path,
            check_same_thread=False,   # varios hilos pueden compartir la conexión
            isolation_level=None,       # autocommit
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._apply_schema()
        logger.info("Database connected | path=%s", self.path)

    # -----------------------------------------------------------------------
    # DatabaseProtocol
    # -----------------------------------------------------------------------

    def get_whitelist(self, plate: str) -> Optional[Dict[str, Any]]:
        """
        Busca una placa en la lista blanca activa (valid_until >= hoy).

        Returns:
            dict con los campos del registro, o None si no existe / está expirada.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        row = self._fetchone(
            "SELECT * FROM whitelist WHERE plate = ? AND valid_until >= ?",
            (plate.upper(), today),
        )
        if row:
            logger.debug("Whitelist hit | plate=%s valid_until=%s", plate, row["valid_until"])
        return dict(row) if row else None

    def check_payment(self, plate: str) -> Optional[Dict[str, Any]]:
        """
        Busca un pago aprobado para la placa en el día de hoy.

        Returns:
            dict con los campos del registro de pago, o None si no existe.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        row = self._fetchone(
            """SELECT * FROM payment_events
               WHERE plate = ?
                 AND status = 'APPROVED'
                 AND DATE(paid_at) = ?
               ORDER BY paid_at DESC
               LIMIT 1""",
            (plate.upper(), today),
        )
        if row:
            logger.debug("Payment hit | plate=%s paid_at=%s", plate, row["paid_at"])
        return dict(row) if row else None

    def insert_event(self, event: Dict[str, Any]) -> None:
        """
        Inserta un registro en la tabla de auditoría de accesos.

        Args:
            event: dict con claves: trace_id, plate, decision, reason, lane_id.
                   created_at se rellena automáticamente.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            """INSERT INTO access_events
               (trace_id, plate, decision, reason, lane_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event.get("trace_id"),
                event.get("plate"),
                event.get("decision"),
                event.get("reason"),
                event.get("lane_id"),
                now,
            ),
        )
        logger.debug(
            "Access event recorded | plate=%s decision=%s trace_id=%s",
            event.get("plate"), event.get("decision"), event.get("trace_id"),
        )

    # -----------------------------------------------------------------------
    # Helpers internos
    # -----------------------------------------------------------------------

    def _apply_schema(self) -> None:
        """Crea las tablas si no existen (idempotente)."""
        schema_path = os.path.join(
            os.path.dirname(__file__), "../../db/schema.sql"
        )
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                self._conn.executescript(f.read())
        else:
            # Fallback inline — tablas mínimas para arranque sin archivo externo
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    plate      TEXT    NOT NULL UNIQUE,
                    owner_name TEXT,
                    valid_until TEXT   NOT NULL,
                    created_at TEXT    DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS payment_events (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    plate          TEXT    NOT NULL,
                    paid_at        TEXT    NOT NULL,
                    amount_cop     INTEGER,
                    status         TEXT    NOT NULL,
                    transaction_id TEXT
                );
                CREATE TABLE IF NOT EXISTS access_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id   TEXT,
                    plate      TEXT,
                    decision   TEXT,
                    reason     TEXT,
                    lane_id    TEXT,
                    created_at TEXT    DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_whitelist_plate  ON whitelist(plate);
                CREATE INDEX IF NOT EXISTS idx_payment_plate    ON payment_events(plate, status, paid_at);
                CREATE INDEX IF NOT EXISTS idx_access_trace     ON access_events(trace_id);
                CREATE INDEX IF NOT EXISTS idx_access_plate     ON access_events(plate);
            """)
        logger.debug("Database schema applied.")

    def _execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.execute(sql, params)

    def _fetchone(
        self, sql: str, params: tuple = ()
    ) -> Optional[sqlite3.Row]:
        cur = self._conn.execute(sql, params)
        return cur.fetchone()
