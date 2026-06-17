"""
ocr_pipeline.py — Conector entre el pipeline de visión y el bus MQTT.

Responsabilidad única: recibir el texto y la confianza ya extraídos por el
pipeline de visión, pasarlos al PlateValidator, y publicar el evento canónico:
  → plate_read        si la placa es válida y supera el umbral de confianza
  → plate_unreadable  si el texto está vacío, la confianza es baja o el
                      formato no es colombiano

Este módulo NO ejecuta Tesseract ni hace procesamiento de imagen.
Es el punto de integración entre la visión (Juanito_part) y el bus MQTT
(integrante_B).

Escala de confianza: 0.0–1.0 (Tesseract retorna 0–100, normalizar antes de llamar).
"""

import logging
import os
from typing import Optional

import yaml

from services.common.event_bus import EventBus
from services.common.event_models import Topics
from services.vision_service.app.plate_validator import PlateValidator, ValidationResult

logger = logging.getLogger(__name__)

_DEFAULT_POLICIES_PATH = os.getenv(
    "POLICIES_PATH",
    os.path.join(os.path.dirname(__file__), "../../../config/policies.yaml"),
)


def _get_tesseract_version() -> str:
    """Obtiene la versión real de Tesseract instalado para el audit trail."""
    try:
        import pytesseract
        return f"tesseract-{pytesseract.get_tesseract_version()}"
    except Exception:
        return "tesseract-unknown"


class OCRPipeline:
    """
    Conector entre el output del OCR y el bus MQTT.
    Instanciar una sola vez al arrancar el vision-service.
    """

    def __init__(
        self,
        event_bus:     EventBus,
        policies_path: str = _DEFAULT_POLICIES_PATH,
        lane_id:       str = "ENTRADA-1",
    ) -> None:
        self.event_bus = event_bus
        self.lane_id   = lane_id
        self._ocr_engine_version = _get_tesseract_version()

        confidence_min = self._load_confidence_threshold(policies_path)
        self.validator = PlateValidator(confidence_threshold=confidence_min)

        logger.info(
            "OCRPipeline listo | lane=%s confidence_min=%.2f engine=%s",
            self.lane_id, confidence_min, self._ocr_engine_version,
        )

    def process(
        self,
        text:          str,
        confidence:    float,    # escala 0.0–1.0
        evidence_id:   str,
        frame_quality: float,
        retries:       int = 0,
        lane_id:       Optional[str] = None,
        trace_id:      Optional[str] = None,
    ) -> ValidationResult:
        """
        Valida el texto OCR y publica el evento MQTT correspondiente.

        Args:
            text:          Texto crudo de Tesseract (ej. "A8C-123").
            confidence:    Confianza en escala 0.0–1.0 (no 0–100).
            evidence_id:   Path de la imagen ROI para auditoría.
            frame_quality: Puntuación de nitidez Laplaciana normalizada (0–1).
            retries:       Reintentos realizados por el pipeline de captura.
            lane_id:       Sobreescribe el lane_id de instancia si se proporciona.
            trace_id:      UUID heredado del evento presence_detected.

        Returns:
            ValidationResult con is_valid, plate normalizada y rejection_reason.
        """
        effective_lane = lane_id or self.lane_id
        result = self.validator.validate(text, confidence)

        if result.is_valid:
            self._publish_plate_read(result, evidence_id, frame_quality, retries,
                                     effective_lane, trace_id)
        else:
            self._publish_plate_unreadable(result, evidence_id, effective_lane, trace_id)

        return result

    def _publish_plate_read(
        self,
        result: ValidationResult,
        evidence_id: str,
        frame_quality: float,
        retries: int,
        lane_id: str,
        trace_id: Optional[str],
    ) -> None:
        payload = {
            "schema_version": "1.2",
            "lane_id":        lane_id,
            "domain":         "linux",
            "plate":          result.plate,
            "confidence":     round(result.confidence, 4),
            "frame_quality":  round(frame_quality, 4),
            "evidence_id":    evidence_id,
            "ocr_engine":     self._ocr_engine_version,
            "retries":        retries,
        }
        self.event_bus.publish(
            topic=Topics.PLATE_READ,
            payload=payload,
            event_type="plate_read",
            trace_id=trace_id,
        )
        logger.info(
            "plate_read | plate=%s confidence=%.2f lane=%s",
            result.plate, result.confidence, lane_id,
        )

    def _publish_plate_unreadable(
        self,
        result: ValidationResult,
        evidence_id: str,
        lane_id: str,
        trace_id: Optional[str],
    ) -> None:
        payload = {
            "schema_version": "1.2",
            "lane_id":        lane_id,
            "domain":         "linux",
            "reason":         result.rejection_reason,
            "confidence":     round(result.confidence, 4),
            "raw_text":       result.raw_text,
            "evidence_id":    evidence_id,
        }
        self.event_bus.publish(
            topic=Topics.PLATE_UNREADABLE,
            payload=payload,
            event_type="plate_unreadable",
            trace_id=trace_id,
        )
        logger.warning(
            "plate_unreadable | reason=%s raw='%s' confidence=%.2f lane=%s",
            result.rejection_reason, result.raw_text, result.confidence, lane_id,
        )

    def _load_confidence_threshold(self, policies_path: str) -> float:
        fallback = 0.85
        try:
            with open(policies_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            return float(config.get("ocr", {}).get("confidence_min", fallback))
        except FileNotFoundError:
            logger.warning("policies.yaml no encontrado en '%s', usando fallback=%.2f",
                           policies_path, fallback)
            return fallback
        except Exception as exc:
            logger.error("Error leyendo confidence_min: %s — fallback=%.2f", exc, fallback)
            return fallback
