"""
test_ocr_pipeline.py — Pruebas unitarias del OCRPipeline.

Estrategia: el EventBus y el PlateValidator se mockean completamente.
Esto permite probar la lógica de enrutamiento (plate_read vs plate_unreadable)
sin necesidad de broker MQTT ni lógica de validación real.

Ejecutar:
    cd parking-edge
    python -m pytest services/vision-service/tests/test_ocr_pipeline.py -v
"""

import unittest
from unittest.mock import MagicMock, patch, call

from services.vision_service.app.ocr_pipeline import OCRPipeline
from services.vision_service.app.plate_validator import ValidationResult
from services.common.event_models import Topics


def _make_pipeline(confidence_min: float = 0.85) -> OCRPipeline:
    """
    Crea un OCRPipeline con EventBus mockeado y threshold fijo,
    sin leer policies.yaml del disco.
    """
    bus = MagicMock()
    with patch.object(OCRPipeline, "_load_confidence_threshold", return_value=confidence_min):
        pipeline = OCRPipeline(event_bus=bus, lane_id="ENTRADA-1")
    return pipeline


class TestOCRPipelineRouting(unittest.TestCase):
    """Verifica que process() publica en el tópico correcto según el resultado."""

    def test_valid_plate_publishes_plate_read(self):
        """Una placa válida debe publicar en Topics.PLATE_READ."""
        pipeline = _make_pipeline()

        # Mockear el validador para devolver éxito
        pipeline.validator.validate = MagicMock(return_value=ValidationResult(
            is_valid=True, plate="ABC-123", raw_text="ABC-123",
            confidence=0.93, rejection_reason=None,
        ))

        pipeline.process(
            text="ABC-123", confidence=0.93,
            evidence_id="img/test_roi.jpg", frame_quality=0.87,
        )

        pipeline.event_bus.publish.assert_called_once()
        call_kwargs = pipeline.event_bus.publish.call_args[1]
        self.assertEqual(call_kwargs["topic"], Topics.PLATE_READ)
        self.assertEqual(call_kwargs["event_type"], "plate_read")

    def test_invalid_plate_publishes_plate_unreadable(self):
        """Una placa inválida debe publicar en Topics.PLATE_UNREADABLE."""
        pipeline = _make_pipeline()

        pipeline.validator.validate = MagicMock(return_value=ValidationResult(
            is_valid=False, plate=None, raw_text="???",
            confidence=0.30, rejection_reason="low_confidence",
        ))

        pipeline.process(
            text="???", confidence=0.30,
            evidence_id="img/bad_roi.jpg", frame_quality=0.40,
        )

        pipeline.event_bus.publish.assert_called_once()
        call_kwargs = pipeline.event_bus.publish.call_args[1]
        self.assertEqual(call_kwargs["topic"], Topics.PLATE_UNREADABLE)
        self.assertEqual(call_kwargs["event_type"], "plate_unreadable")


class TestOCRPipelinePlateReadPayload(unittest.TestCase):
    """Verifica que el payload de plate_read cumple el contrato del blueprint (sección 9.3)."""

    def setUp(self):
        self.pipeline = _make_pipeline()
        self.pipeline.validator.validate = MagicMock(return_value=ValidationResult(
            is_valid=True, plate="XYZ-789", raw_text="XYZ-789",
            confidence=0.91, rejection_reason=None,
        ))

    def test_payload_contains_all_required_fields(self):
        """El payload debe incluir todos los campos del contrato del blueprint."""
        self.pipeline.process(
            text="XYZ-789", confidence=0.91,
            evidence_id="img/2026/05/roi.jpg", frame_quality=0.88,
            retries=1, lane_id="SALIDA-1", trace_id="fixed-trace-id",
        )

        payload = self.pipeline.event_bus.publish.call_args[1]["payload"]

        self.assertEqual(payload["plate"],          "XYZ-789")
        self.assertAlmostEqual(payload["confidence"], 0.91, places=3)
        self.assertAlmostEqual(payload["frame_quality"], 0.88, places=3)
        self.assertEqual(payload["evidence_id"],    "img/2026/05/roi.jpg")
        self.assertEqual(payload["ocr_engine"],     "tesseract-5.3")
        self.assertEqual(payload["retries"],        1)
        self.assertEqual(payload["lane_id"],        "SALIDA-1")
        self.assertEqual(payload["schema_version"], "1.2")
        self.assertEqual(payload["domain"],         "linux")

    def test_trace_id_is_forwarded(self):
        """El trace_id proporcionado debe heredarse en el evento publicado."""
        self.pipeline.process(
            text="XYZ-789", confidence=0.91,
            evidence_id="img/roi.jpg", frame_quality=0.88,
            trace_id="my-trace-uuid",
        )
        call_kwargs = self.pipeline.event_bus.publish.call_args[1]
        self.assertEqual(call_kwargs["trace_id"], "my-trace-uuid")

    def test_lane_id_overridable_per_call(self):
        """lane_id pasado en process() debe tener prioridad sobre el de instancia."""
        self.pipeline.process(
            text="XYZ-789", confidence=0.91,
            evidence_id="img/roi.jpg", frame_quality=0.88,
            lane_id="SALIDA-2",
        )
        payload = self.pipeline.event_bus.publish.call_args[1]["payload"]
        self.assertEqual(payload["lane_id"], "SALIDA-2")

    def test_lane_id_falls_back_to_instance(self):
        """Si no se pasa lane_id en process(), debe usarse el de la instancia."""
        self.pipeline.process(
            text="XYZ-789", confidence=0.91,
            evidence_id="img/roi.jpg", frame_quality=0.88,
        )
        payload = self.pipeline.event_bus.publish.call_args[1]["payload"]
        self.assertEqual(payload["lane_id"], "ENTRADA-1")


class TestOCRPipelineUnreadablePayload(unittest.TestCase):
    """Verifica el payload de plate_unreadable para cada rejection_reason."""

    def _process_with_reason(self, reason: str, raw: str, conf: float) -> dict:
        pipeline = _make_pipeline()
        pipeline.validator.validate = MagicMock(return_value=ValidationResult(
            is_valid=False, plate=None, raw_text=raw,
            confidence=conf, rejection_reason=reason,
        ))
        pipeline.process(
            text=raw, confidence=conf,
            evidence_id="img/roi.jpg", frame_quality=0.50,
        )
        return pipeline.event_bus.publish.call_args[1]["payload"]

    def test_low_confidence_reason_propagated(self):
        payload = self._process_with_reason("low_confidence", "ABC-123", 0.40)
        self.assertEqual(payload["reason"], "low_confidence")
        self.assertEqual(payload["raw_text"], "ABC-123")

    def test_invalid_format_reason_propagated(self):
        payload = self._process_with_reason("invalid_format", "123-ABC", 0.91)
        self.assertEqual(payload["reason"], "invalid_format")

    def test_no_text_reason_propagated(self):
        payload = self._process_with_reason("no_text", "", 0.0)
        self.assertEqual(payload["reason"], "no_text")
        self.assertEqual(payload["raw_text"], "")

    def test_unreadable_payload_contains_evidence_id(self):
        payload = self._process_with_reason("invalid_format", "BAD", 0.92)
        self.assertIn("evidence_id", payload)


class TestOCRPipelineReturnValue(unittest.TestCase):
    """process() debe retornar el ValidationResult para que el caller pueda inspeccionarlo."""

    def test_returns_validation_result(self):
        pipeline = _make_pipeline()
        expected = ValidationResult(
            is_valid=True, plate="DEF-456", raw_text="DEF-456",
            confidence=0.95, rejection_reason=None,
        )
        pipeline.validator.validate = MagicMock(return_value=expected)

        result = pipeline.process(
            text="DEF-456", confidence=0.95,
            evidence_id="img/roi.jpg", frame_quality=0.90,
        )
        self.assertIs(result, expected)


class TestOCRPipelinePoliciesLoading(unittest.TestCase):
    """Verifica la carga del threshold desde policies.yaml."""

    def test_loads_threshold_from_yaml(self):
        """Si el YAML existe y tiene ocr.confidence_min, debe usarlo."""
        yaml_content = "ocr:\n  confidence_min: 0.75\n"
        bus = MagicMock()

        with patch("builtins.open", unittest.mock.mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value={"ocr": {"confidence_min": 0.75}}):
                pipeline = OCRPipeline(event_bus=bus, policies_path="/fake/policies.yaml")

        self.assertAlmostEqual(pipeline.validator.confidence_threshold, 0.75)

    def test_falls_back_on_missing_file(self):
        """Si el YAML no existe, debe usar el fallback 0.85 sin lanzar excepción."""
        bus = MagicMock()

        with patch("builtins.open", side_effect=FileNotFoundError):
            pipeline = OCRPipeline(event_bus=bus, policies_path="/no/existe.yaml")

        self.assertAlmostEqual(pipeline.validator.confidence_threshold, 0.85)

    def test_falls_back_on_malformed_yaml(self):
        """YAML malformado no debe propagar excepción."""
        import yaml as yaml_module
        bus = MagicMock()

        with patch("builtins.open", unittest.mock.mock_open(read_data="::invalid::")):
            with patch("yaml.safe_load", side_effect=yaml_module.YAMLError("bad")):
                pipeline = OCRPipeline(event_bus=bus, policies_path="/fake/bad.yaml")

        self.assertAlmostEqual(pipeline.validator.confidence_threshold, 0.85)


if __name__ == "__main__":
    unittest.main()
