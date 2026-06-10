"""
test_orchestrator.py — Pruebas unitarias e integración del Orchestrator.

Estrategia:
  - EventBus mockeado: verificamos qué tópicos y payloads se publican.
  - Base de datos REAL (SQLite en memoria) poblada con simulation_data
    adaptado al schema mínimo. Esto prueba la lógica de negocio completa
    sin depender del database.py del Integrante A.

Casos cubiertos (uno por cada fila de simulation_metadata):
  - Whitelist activa          → ACCESS_GRANTED + barrier OPEN
  - Whitelist expirada        → ACCESS_DENIED  (unknown_plate)
  - Pago registrado hoy       → ACCESS_GRANTED + barrier OPEN
  - Sin registro              → ACCESS_DENIED  (unknown_plate)
  - Placa ilegible            → assisted_mode

Ejecutar:
    cd parking-edge
    python -m pytest services/access-orchestrator/tests/test_orchestrator.py -v
"""

import sqlite3
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, call

from services.access_orchestrator.app.orchestrator import Orchestrator
from services.access_orchestrator.app.policies import Policies
from services.common.event_models import Topics


# ---------------------------------------------------------------------------
# BD de prueba — SQLite en memoria con el schema mínimo necesario
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS whitelist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plate       TEXT NOT NULL UNIQUE,
    owner_name  TEXT,
    valid_until TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payment_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    plate          TEXT NOT NULL,
    paid_at        TEXT NOT NULL,
    amount_cop     INTEGER,
    status         TEXT NOT NULL,
    transaction_id TEXT
);

CREATE TABLE IF NOT EXISTS access_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id   TEXT,
    plate      TEXT,
    decision   TEXT,
    reason     TEXT,
    lane_id    TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_SEED_SQL = """
-- Whitelist activa
INSERT INTO whitelist (plate, owner_name, valid_until) VALUES
    ('ABC-123', 'Carlos Gómez',   '2027-12-31'),
    ('BCD-234', 'Laura Martínez', '2027-11-30'),
    ('EFG-567', 'Juan Ospina',    '2027-12-01');

-- Whitelist expirada
INSERT INTO whitelist (plate, owner_name, valid_until) VALUES
    ('JKL-012', 'Ricardo Arias', '2024-06-30'),
    ('KLM-123', 'Sofía Cardona', '2024-01-15');

-- Pagos de hoy
INSERT INTO payment_events (plate, paid_at, amount_cop, status, transaction_id) VALUES
    ('FGH-678', datetime('now'), 3500, 'APPROVED', 'TXN-001'),
    ('GHI-789', datetime('now'), 3500, 'APPROVED', 'TXN-002'),
    ('MNO-345', datetime('now'), 3500, 'APPROVED', 'TXN-005');

-- Sin registro: NOP-456, OPQ-567 (no insertados — su ausencia es el caso de prueba)
"""


class InMemoryDatabase:
    """
    Implementación real de DatabaseProtocol usando SQLite en memoria.
    Replica la lógica que tendrá database.py del Integrante A.
    """

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.executescript(_SEED_SQL)
        self.conn.commit()

    def get_whitelist(self, plate: str) -> Optional[Dict[str, Any]]:
        """Retorna registro si plate existe en whitelist con valid_until > ahora."""
        row = self.conn.execute(
            "SELECT * FROM whitelist WHERE plate = ? AND valid_until > datetime('now')",
            (plate,)
        ).fetchone()
        return dict(row) if row else None

    def check_payment(self, plate: str) -> Optional[Dict[str, Any]]:
        """Retorna el pago más reciente APPROVED de hoy para la placa."""
        row = self.conn.execute(
            """SELECT * FROM payment_events
               WHERE plate = ?
                 AND status = 'APPROVED'
                 AND date(paid_at) = date('now')
               ORDER BY paid_at DESC LIMIT 1""",
            (plate,)
        ).fetchone()
        return dict(row) if row else None

    def insert_event(self, event: Dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT INTO access_events (trace_id, plate, decision, reason, lane_id)
               VALUES (:trace_id, :plate, :decision, :reason, :lane_id)""",
            event,
        )
        self.conn.commit()

    def count_events(self, plate: str) -> int:
        """Helper para assertions: cuántos eventos se registraron para esta placa."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM access_events WHERE plate = ?", (plate,)
        ).fetchone()
        return row[0]


# ---------------------------------------------------------------------------
# Fixture base
# ---------------------------------------------------------------------------

def _make_orchestrator(db=None):
    bus      = MagicMock()
    database = db or InMemoryDatabase()
    policies = Policies()  # defaults
    orch     = Orchestrator(event_bus=bus, database=database, policies=policies)
    bus.publish.reset_mock()  # limpiar las llamadas del __init__ si las hay
    return orch, bus, database


def _plate_read_envelope(plate: str, trace_id: str = "t-001", lane_id: str = "ENTRADA-1") -> dict:
    return {
        "trace_id":   trace_id,
        "event_type": "plate_read",
        "source":     "vision-service",
        "payload": {
            "plate":         plate,
            "confidence":    0.93,
            "frame_quality": 0.87,
            "evidence_id":   f"img/{plate}.jpg",
            "lane_id":       lane_id,
            "retries":       0,
        },
    }


def _unreadable_envelope(reason: str = "low_confidence", trace_id: str = "t-unr") -> dict:
    return {
        "trace_id":   trace_id,
        "event_type": "plate_unreadable",
        "source":     "vision-service",
        "payload": {
            "reason":      reason,
            "confidence":  0.30,
            "raw_text":    "???",
            "evidence_id": "img/bad.jpg",
            "lane_id":     "ENTRADA-1",
        },
    }


# ---------------------------------------------------------------------------
# Tests: whitelist activa
# ---------------------------------------------------------------------------

class TestWhitelistGranted(unittest.TestCase):

    def setUp(self):
        self.orch, self.bus, self.db = _make_orchestrator()

    def test_whitelist_plate_gets_access_granted(self):
        self.orch._on_plate_read(_plate_read_envelope("ABC-123", trace_id="wl-1"))
        topics = [c[1]["topic"] for c in self.bus.publish.call_args_list]
        self.assertIn(Topics.ACCESS_GRANTED, topics)

    def test_whitelist_plate_sends_barrier_open(self):
        self.orch._on_plate_read(_plate_read_envelope("BCD-234", trace_id="wl-2"))
        barrier_calls = [
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.BARRIER_COMMAND
        ]
        self.assertEqual(len(barrier_calls), 1)
        self.assertEqual(barrier_calls[0][1]["payload"]["action"], "OPEN")

    def test_whitelist_reason_is_whitelist(self):
        self.orch._on_plate_read(_plate_read_envelope("EFG-567", trace_id="wl-3"))
        granted_calls = [
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.ACCESS_GRANTED
        ]
        self.assertEqual(granted_calls[0][1]["payload"]["reason"], "whitelist")

    def test_whitelist_event_recorded_in_db(self):
        self.orch._on_plate_read(_plate_read_envelope("ABC-123", trace_id="wl-db"))
        self.assertEqual(self.db.count_events("ABC-123"), 1)

    def test_trace_id_propagated_to_access_granted(self):
        self.orch._on_plate_read(_plate_read_envelope("ABC-123", trace_id="my-trace"))
        granted_call = next(
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.ACCESS_GRANTED
        )
        self.assertEqual(granted_call[1]["trace_id"], "my-trace")


# ---------------------------------------------------------------------------
# Tests: whitelist expirada → debe tratarse como sin registro
# ---------------------------------------------------------------------------

class TestExpiredWhitelistDenied(unittest.TestCase):

    def setUp(self):
        self.orch, self.bus, self.db = _make_orchestrator()

    def test_expired_whitelist_gets_access_denied(self):
        self.orch._on_plate_read(_plate_read_envelope("JKL-012", trace_id="exp-1"))
        topics = [c[1]["topic"] for c in self.bus.publish.call_args_list]
        self.assertIn(Topics.ACCESS_DENIED, topics)
        self.assertNotIn(Topics.ACCESS_GRANTED, topics)

    def test_expired_whitelist_no_barrier_command(self):
        self.orch._on_plate_read(_plate_read_envelope("KLM-123", trace_id="exp-2"))
        barrier_calls = [
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.BARRIER_COMMAND
        ]
        self.assertEqual(len(barrier_calls), 0)


# ---------------------------------------------------------------------------
# Tests: pago registrado hoy
# ---------------------------------------------------------------------------

class TestPaymentGranted(unittest.TestCase):

    def setUp(self):
        self.orch, self.bus, self.db = _make_orchestrator()

    def test_paid_plate_gets_access_granted(self):
        self.orch._on_plate_read(_plate_read_envelope("FGH-678", trace_id="pay-1"))
        topics = [c[1]["topic"] for c in self.bus.publish.call_args_list]
        self.assertIn(Topics.ACCESS_GRANTED, topics)

    def test_paid_plate_sends_barrier_open(self):
        self.orch._on_plate_read(_plate_read_envelope("GHI-789", trace_id="pay-2"))
        barrier_calls = [
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.BARRIER_COMMAND
        ]
        self.assertEqual(len(barrier_calls), 1)

    def test_paid_reason_is_payment_approved(self):
        self.orch._on_plate_read(_plate_read_envelope("MNO-345", trace_id="pay-3"))
        granted_calls = [
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.ACCESS_GRANTED
        ]
        self.assertEqual(granted_calls[0][1]["payload"]["reason"], "payment_approved")

    def test_paid_event_recorded_in_db(self):
        self.orch._on_plate_read(_plate_read_envelope("FGH-678", trace_id="pay-db"))
        self.assertEqual(self.db.count_events("FGH-678"), 1)


# ---------------------------------------------------------------------------
# Tests: sin registro
# ---------------------------------------------------------------------------

class TestNoRecordDenied(unittest.TestCase):

    def setUp(self):
        self.orch, self.bus, self.db = _make_orchestrator()

    def test_unknown_plate_gets_access_denied(self):
        self.orch._on_plate_read(_plate_read_envelope("NOP-456", trace_id="nr-1"))
        topics = [c[1]["topic"] for c in self.bus.publish.call_args_list]
        self.assertIn(Topics.ACCESS_DENIED, topics)
        self.assertNotIn(Topics.ACCESS_GRANTED, topics)

    def test_unknown_plate_reason_is_unknown_plate(self):
        self.orch._on_plate_read(_plate_read_envelope("OPQ-567", trace_id="nr-2"))
        denied_calls = [
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.ACCESS_DENIED
        ]
        self.assertEqual(denied_calls[0][1]["payload"]["reason"], "unknown_plate")

    def test_unknown_plate_no_barrier_command(self):
        self.orch._on_plate_read(_plate_read_envelope("PQR-678", trace_id="nr-3"))
        barrier_calls = [
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.BARRIER_COMMAND
        ]
        self.assertEqual(len(barrier_calls), 0)

    def test_denied_event_recorded_in_db(self):
        self.orch._on_plate_read(_plate_read_envelope("NOP-456", trace_id="nr-db"))
        self.assertEqual(self.db.count_events("NOP-456"), 1)


# ---------------------------------------------------------------------------
# Tests: placa ilegible → modo asistido
# ---------------------------------------------------------------------------

class TestPlateUnreadable(unittest.TestCase):

    def setUp(self):
        self.orch, self.bus, _ = _make_orchestrator()

    def test_unreadable_publishes_assisted_mode(self):
        self.orch._on_plate_unreadable(_unreadable_envelope("low_confidence"))
        topics = [c[1]["topic"] for c in self.bus.publish.call_args_list]
        self.assertIn(Topics.ASSISTED_MODE, topics)

    def test_unreadable_no_access_events(self):
        self.orch._on_plate_unreadable(_unreadable_envelope())
        topics = [c[1]["topic"] for c in self.bus.publish.call_args_list]
        self.assertNotIn(Topics.ACCESS_GRANTED, topics)
        self.assertNotIn(Topics.ACCESS_DENIED,  topics)

    def test_assisted_mode_payload_has_timeout(self):
        self.orch._on_plate_unreadable(_unreadable_envelope())
        assisted_call = next(
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.ASSISTED_MODE
        )
        self.assertIn("timeout_s", assisted_call[1]["payload"])

    def test_unreadable_trace_id_propagated(self):
        self.orch._on_plate_unreadable(_unreadable_envelope(trace_id="unr-trace"))
        assisted_call = next(
            c for c in self.bus.publish.call_args_list
            if c[1].get("topic") == Topics.ASSISTED_MODE
        )
        self.assertEqual(assisted_call[1]["trace_id"], "unr-trace")


# ---------------------------------------------------------------------------
# Tests: resiliencia ante fallo de BD
# ---------------------------------------------------------------------------

class TestDatabaseFailureHandling(unittest.TestCase):

    def test_db_error_results_in_deny_not_exception(self):
        """Si la BD falla, el orquestador debe denegar (FAIL_CLOSED) sin crashear."""
        bus = MagicMock()
        broken_db = MagicMock()
        broken_db.get_whitelist.side_effect = Exception("DB connection lost")
        broken_db.check_payment.side_effect = Exception("DB connection lost")
        broken_db.insert_event.side_effect  = Exception("DB connection lost")

        orch = Orchestrator(event_bus=bus, database=broken_db)
        bus.publish.reset_mock()

        try:
            orch._on_plate_read(_plate_read_envelope("ABC-123", trace_id="db-fail"))
        except Exception as exc:
            self.fail(f"Orchestrator raised unexpectedly on DB failure: {exc}")

        topics = [c[1]["topic"] for c in bus.publish.call_args_list]
        self.assertIn(Topics.ACCESS_DENIED, topics)
        self.assertNotIn(Topics.ACCESS_GRANTED, topics)


if __name__ == "__main__":
    unittest.main()
