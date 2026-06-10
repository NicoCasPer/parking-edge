"""
test_policies.py — Pruebas unitarias del cargador de políticas.

Cubre:
  - Carga correcta desde YAML válido
  - Valores por defecto ante archivo inexistente
  - Valores por defecto ante YAML malformado
  - Acceso a cada sección y propiedad de acceso rápido
  - Tipos correctos en cada campo

Ejecutar:
    cd parking-edge
    python -m pytest services/access-orchestrator/tests/test_policies.py -v
"""

import unittest
from unittest.mock import mock_open, patch

import yaml

from services.access_orchestrator.app.policies import (
    Policies,
    OCRPolicies,
    AccessPolicies,
    ExternalProviderPolicies,
    CircuitBreakerPolicies,
)

# YAML completo válido que replica el config/policies.yaml real
_VALID_YAML = """
ocr:
  confidence_min: 0.90
  max_retries: 5
  retry_window_ms: 500
  plate_regex: "^[A-Z]{3}-[0-9]{3}$"

access:
  default_mode: "FAIL_OPEN_LIMITED"
  whitelist_ttl_min: 60
  assisted_timeout_s: 90

external_provider:
  timeout_ms: 2000
  max_retries: 3
  backoff_base_ms: 600

circuit_breaker:
  fail_threshold: 10
  reset_timeout_s: 60

telemetry:
  heartbeat_interval_s: 15
  cpu_alert_threshold: 75.0
  memory_alert_threshold: 80.0
  disk_alert_threshold: 85.0
"""

# YAML parcial — solo algunas secciones; el resto debe usar defaults
_PARTIAL_YAML = """
ocr:
  confidence_min: 0.75
"""


class TestPoliciesFromValidYAML(unittest.TestCase):
    """Carga desde YAML completo y válido."""

    def setUp(self):
        with patch("builtins.open", mock_open(read_data=_VALID_YAML)):
            with patch("yaml.safe_load", return_value=yaml.safe_load(_VALID_YAML)):
                self.p = Policies.load("/fake/policies.yaml")

    # --- Sección OCR ---
    def test_ocr_confidence_min(self):
        self.assertAlmostEqual(self.p.ocr.confidence_min, 0.90)

    def test_ocr_max_retries(self):
        self.assertEqual(self.p.ocr.max_retries, 5)

    def test_ocr_retry_window_ms(self):
        self.assertEqual(self.p.ocr.retry_window_ms, 500)

    def test_ocr_plate_regex(self):
        self.assertEqual(self.p.ocr.plate_regex, r"^[A-Z]{3}-[0-9]{3}$")

    # --- Sección Access ---
    def test_access_default_mode(self):
        self.assertEqual(self.p.access.default_mode, "FAIL_OPEN_LIMITED")

    def test_access_whitelist_ttl(self):
        self.assertEqual(self.p.access.whitelist_ttl_min, 60)

    def test_access_assisted_timeout(self):
        self.assertEqual(self.p.access.assisted_timeout_s, 90)

    # --- Sección External Provider ---
    def test_external_provider_timeout(self):
        self.assertEqual(self.p.external_provider.timeout_ms, 2000)

    def test_external_provider_max_retries(self):
        self.assertEqual(self.p.external_provider.max_retries, 3)

    def test_external_provider_backoff(self):
        self.assertEqual(self.p.external_provider.backoff_base_ms, 600)

    # --- Sección Circuit Breaker ---
    def test_circuit_breaker_fail_threshold(self):
        self.assertEqual(self.p.circuit_breaker.fail_threshold, 10)

    def test_circuit_breaker_reset_timeout(self):
        self.assertEqual(self.p.circuit_breaker.reset_timeout_s, 60)

    # --- Propiedades de acceso rápido ---
    def test_shortcut_default_mode(self):
        self.assertEqual(self.p.default_mode, self.p.access.default_mode)

    def test_shortcut_assisted_timeout(self):
        self.assertEqual(self.p.assisted_timeout_s, self.p.access.assisted_timeout_s)

    def test_shortcut_confidence_min(self):
        self.assertAlmostEqual(self.p.confidence_min, self.p.ocr.confidence_min)


class TestPoliciesDefaults(unittest.TestCase):
    """Valores por defecto cuando el archivo no existe o el YAML está incompleto."""

    def test_defaults_on_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            p = Policies.load("/no/existe.yaml")

        self.assertAlmostEqual(p.ocr.confidence_min,        0.85)
        self.assertEqual(p.ocr.max_retries,                  3)
        self.assertEqual(p.access.default_mode,              "FAIL_CLOSED")
        self.assertEqual(p.access.whitelist_ttl_min,         120)
        self.assertEqual(p.access.assisted_timeout_s,        120)
        self.assertEqual(p.external_provider.timeout_ms,     1200)
        self.assertEqual(p.circuit_breaker.fail_threshold,   5)
        self.assertEqual(p.circuit_breaker.reset_timeout_s,  30)

    def test_defaults_on_malformed_yaml(self):
        with patch("builtins.open", mock_open(read_data="::invalid::")):
            with patch("yaml.safe_load", side_effect=yaml.YAMLError("bad yaml")):
                p = Policies.load("/fake/bad.yaml")

        self.assertEqual(p.access.default_mode, "FAIL_CLOSED")
        self.assertAlmostEqual(p.ocr.confidence_min, 0.85)

    def test_partial_yaml_uses_defaults_for_missing_sections(self):
        """Si solo viene la sección 'ocr', el resto debe tomar defaults."""
        with patch("builtins.open", mock_open(read_data=_PARTIAL_YAML)):
            with patch("yaml.safe_load", return_value=yaml.safe_load(_PARTIAL_YAML)):
                p = Policies.load("/fake/partial.yaml")

        self.assertAlmostEqual(p.ocr.confidence_min, 0.75)  # del YAML
        self.assertEqual(p.access.default_mode, "FAIL_CLOSED")  # default
        self.assertEqual(p.circuit_breaker.fail_threshold, 5)   # default

    def test_empty_yaml_uses_all_defaults(self):
        with patch("builtins.open", mock_open(read_data="")):
            with patch("yaml.safe_load", return_value=None):
                p = Policies.load("/fake/empty.yaml")

        self.assertIsInstance(p.ocr,               OCRPolicies)
        self.assertIsInstance(p.access,            AccessPolicies)
        self.assertIsInstance(p.external_provider, ExternalProviderPolicies)
        self.assertIsInstance(p.circuit_breaker,   CircuitBreakerPolicies)


class TestPoliciesTypes(unittest.TestCase):
    """Los tipos deben ser correctos independientemente de cómo los escribe el YAML."""

    def setUp(self):
        # YAML con valores que podrían venir como strings desde el archivo
        _yaml = {"ocr": {"confidence_min": "0.80", "max_retries": "4"}}
        with patch("builtins.open", mock_open(read_data="")):
            with patch("yaml.safe_load", return_value=_yaml):
                self.p = Policies.load("/fake/policies.yaml")

    def test_confidence_min_is_float(self):
        self.assertIsInstance(self.p.ocr.confidence_min, float)

    def test_max_retries_is_int(self):
        self.assertIsInstance(self.p.ocr.max_retries, int)


if __name__ == "__main__":
    unittest.main()