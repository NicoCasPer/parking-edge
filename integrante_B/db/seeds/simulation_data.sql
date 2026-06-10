-- ============================================================
-- Simulation Seed Data — Integrante B
-- Pobla la BD con 20 registros para pruebas de integración
-- Compatible con el schema.sql del Integrante A
-- ============================================================

-- BLOQUE 1: Whitelist activa (pase mensual vigente)
INSERT INTO whitelist (plate, owner_name, valid_until) VALUES
  ('ABC-123', 'Carlos Gómez',    '2025-12-31'),
  ('BCD-234', 'Laura Martínez',  '2025-11-30'),
  ('CDE-345', 'Pedro Ruiz',      '2025-12-15'),
  ('DEF-456', 'Ana Torres',      '2025-10-31'),
  ('EFG-567', 'Juan Ospina',     '2025-12-01');

-- BLOQUE 2: Whitelist expirada (debe tratarse como sin pago)
INSERT INTO whitelist (plate, owner_name, valid_until) VALUES
  ('JKL-012', 'Ricardo Arias',   '2024-06-30'),
  ('KLM-123', 'Sofía Cardona',   '2024-01-15'),
  ('LMN-234', 'Diego Moreno',    '2023-12-31');

-- BLOQUE 3: Pagaron hoy (acceso por transacción reciente)
INSERT INTO payment_events (plate, paid_at, amount, status) VALUES
  ('FGH-678', datetime('now'), 3500, 'APPROVED'),
  ('GHI-789', datetime('now'), 3500, 'APPROVED'),
  ('HIJ-890', datetime('now'), 3500, 'APPROVED'),
  ('IJK-901', datetime('now'), 3500, 'APPROVED'),
  ('MNO-345', datetime('now'), 3500, 'APPROVED');

-- BLOQUE 4: Sin pago registrado (no están en whitelist ni han pagado)
-- Estas placas simplemente no existen en ninguna tabla → acceso denegado
-- NOP-456, OPQ-567, PQR-678, QRS-789, RST-890
-- (No requieren INSERT — su ausencia es el caso de prueba)

-- Registro de referencia para tests
INSERT INTO simulation_metadata (plate, scenario, expected_decision) VALUES
  ('ABC-123', 'whitelist_active',   'ACCESS_GRANTED'),
  ('JKL-012', 'whitelist_expired',  'ACCESS_DENIED'),
  ('FGH-678', 'payment_today',      'ACCESS_GRANTED'),
  ('NOP-456', 'no_record',          'ACCESS_DENIED');