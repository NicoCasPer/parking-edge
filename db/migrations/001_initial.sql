-- 001_initial.sql — Migración inicial: crea todas las tablas del esquema v1.
-- Idempotente: usa CREATE TABLE IF NOT EXISTS para re-ejecutarse de forma segura.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS whitelist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plate       TEXT    NOT NULL,
    owner_name  TEXT,
    valid_from  TEXT    NOT NULL,
    valid_until TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (plate)
);

CREATE INDEX IF NOT EXISTS idx_whitelist_plate ON whitelist(plate);
CREATE INDEX IF NOT EXISTS idx_whitelist_valid  ON whitelist(plate, valid_until);

CREATE TABLE IF NOT EXISTS payment_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT    NOT NULL UNIQUE,
    plate           TEXT    NOT NULL,
    amount_cop      INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL,
    provider_tx_id  TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    processed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_payment_plate    ON payment_events(plate);
CREATE INDEX IF NOT EXISTS idx_payment_status   ON payment_events(status, created_at);
CREATE INDEX IF NOT EXISTS idx_payment_trace    ON payment_events(trace_id);

CREATE TABLE IF NOT EXISTS access_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT    NOT NULL UNIQUE,
    plate           TEXT    NOT NULL,
    lane_id         TEXT    NOT NULL,
    decision        TEXT    NOT NULL,
    reason          TEXT    NOT NULL,
    confidence      REAL    DEFAULT 0.0,
    frame_quality   REAL    DEFAULT 0.0,
    evidence_id     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_access_plate    ON access_events(plate, created_at);
CREATE INDEX IF NOT EXISTS idx_access_decision ON access_events(decision, created_at);
CREATE INDEX IF NOT EXISTS idx_access_trace    ON access_events(trace_id);

-- Tabla de control de migraciones aplicadas
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT NOT NULL PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO schema_migrations (version) VALUES ('001_initial');
