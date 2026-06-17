-- simulation_data.sql — Datos de prueba con fechas dinámicas (relativas a 'now').
-- Usar con: sqlite3 parking.db < simulation_data.sql

-- Placas en whitelist con vigencia de 1 año desde hoy
INSERT OR IGNORE INTO whitelist (plate, owner_name, valid_from, valid_until)
VALUES
    ('ABC123', 'Juan Pérez',    date('now'),              date('now', '+1 year')),
    ('XYZ789', 'María García',  date('now'),              date('now', '+1 year')),
    ('DEF012', 'Carlos López',  date('now'),              date('now', '+1 year')),
    ('GHI012', 'Ana Martínez',  date('now'),              date('now', '+1 year')),
    ('JKL345', 'Luis Torres',   date('now', '-30 days'),  date('now', '+6 months'));

-- Placa expirada (para probar denegación de acceso)
INSERT OR IGNORE INTO whitelist (plate, owner_name, valid_from, valid_until)
VALUES
    ('EXP999', 'Placa Expirada', date('now', '-2 years'), date('now', '-1 day'));

-- Eventos de pago aprobados de las últimas 24 horas
INSERT OR IGNORE INTO payment_events (trace_id, plate, amount_cop, status, provider_tx_id)
VALUES
    ('sim-pay-001', 'ABC123', 5000, 'APPROVED', 'mock-pay-001'),
    ('sim-pay-002', 'XYZ789', 5000, 'APPROVED', 'mock-pay-002'),
    ('sim-pay-003', 'OTR111', 5000, 'APPROVED', 'mock-pay-003');

-- Eventos de acceso: granted + denied
INSERT OR IGNORE INTO access_events (trace_id, plate, lane_id, decision, reason, confidence, frame_quality)
VALUES
    ('sim-acc-001', 'ABC123', 'ENTRADA-1', 'GRANTED', 'whitelist',        0.95, 0.88),
    ('sim-acc-002', 'OTR111', 'ENTRADA-1', 'GRANTED', 'payment',          0.87, 0.75),
    ('sim-acc-003', 'EXP999', 'ENTRADA-1', 'DENIED',  'whitelist_expired',0.91, 0.82),
    ('sim-acc-004', 'UNK000', 'ENTRADA-1', 'DENIED',  'not_found',        0.78, 0.71),
    ('sim-acc-005', 'ABC123', 'ENTRADA-1', 'GRANTED', 'whitelist',        0.93, 0.90);
