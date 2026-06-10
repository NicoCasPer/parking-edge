"""
ocr_pipeline.py — Conector entre el OCR del vision-service y el bus de eventos.

Responsabilidad única:
  Recibir el texto y la confianza ya extraídos por el pipeline de visión del
  Integrante A, pasarlos al PlateValidator, y publicar el evento canónico
  correcto en el bus MQTT:
    → plate_read        si la placa es válida y supera el umbral de confianza
    → plate_unreadable  si el texto está vacío, la confianza es baja o el
                        formato no es colombiano

  Este módulo NO ejecuta Tesseract ni hace ningún procesamiento de imagen.
  Es el punto de integración entre los dos integrantes dentro del vision-service.

Interfaz de entrada (llamada directa desde el código del Integrante A):

    pipeline.process(
        text        = "ABC-123",   # texto crudo devuelto por Tesseract
        confidence  = 0.91,        # confianza media Tesseract (escala 0.0–1.0)
        lane_id     = "ENTRADA-1", # identificador del carril físico
        evidence_id = "img/...",   # path de la imagen ROI para auditoría
        frame_quality = 0.87,      # calidad del frame evaluada por quality.py
        retries     = 1,           # número de reintentos que hizo el pipeline A
        trace_id    = "uuid...",   # heredar el trace_id del evento presence_detected
    )

Configuración (leída de policies.yaml):
    ocr.confidence_min   — umbral de confianza (default 0.85)
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
    os.path.join(os.path.dirname(__file__), "../../../../config/policies.yaml"),
)
_OCR_ENGINE_VERSION = "tesseract-5.3"


class OCRPipeline:
    """
    Conector delgado entre el output del OCR (Integrante A) y el bus MQTT.

    Instanciar una sola vez al arrancar el vision-service y reutilizar
    para cada placa detectada.
    """

    def __init__(
        self,
        event_bus:      EventBus,
        policies_path:  str = _DEFAULT_POLICIES_PATH,
        lane_id:        str = "ENTRADA-1",
    ) -> None:
        """
        Args:
            event_bus:     Instancia ya conectada del EventBus compartido.
            policies_path: Ruta al policies.yaml. Lee ocr.confidence_min.
            lane_id:       Identificador del carril físico (configurable por instancia).
        """
        self.event_bus = event_bus
        self.lane_id   = lane_id

        confidence_min = self._load_confidence_threshold(policies_path)
        self.validator = PlateValidator(confidence_threshold=confidence_min)

        logger.info(
            "OCRPipeline ready | lane=%s confidence_min=%.2f",
            self.lane_id, confidence_min,
        )

    # -----------------------------------------------------------------------
    # API pública — único punto de entrada desde el código del Integrante A
    # -----------------------------------------------------------------------

    def process(
        self,
        text:          str,
        confidence:    float,
        evidence_id:   str,
        frame_quality: float,
        retries:       int = 0,
        lane_id:       Optional[str] = None,
        trace_id:      Optional[str] = None,
    ) -> ValidationResult:
        """
        Valida el texto OCR y publica el evento correspondiente en el bus.

        Args:
            text:          Texto crudo devuelto por Tesseract (ej. "A8C-123").
            confidence:    Confianza media del OCR en escala 0.0–1.0.
            evidence_id:   Path relativo de la imagen ROI guardada (para auditoría).
            frame_quality: Puntuación de calidad del frame evaluada por quality.py (0–1).
            retries:       Número de reintentos realizados por el pipeline de captura.
            lane_id:       Sobreescribe el lane_id de instancia si se proporciona.
            trace_id:      UUID heredado del evento presence_detected de origen.
                           Si es None se genera uno nuevo.

        Returns:
            ValidationResult con is_valid, plate normalizada y rejection_reason.
            El resultado ya ha sido publicado en MQTT al momento de retornar.
        """
        effective_lane = lane_id or self.lane_id
        result = self.validator.validate(text, confidence)

        if result.is_valid:
            self._publish_plate_read(result, evidence_id, frame_quality, retries,
                                     effective_lane, trace_id)
        else:
            self._publish_plate_unreadable(result, evidence_id, effective_lane, trace_id)

        return result

    # -----------------------------------------------------------------------
    # Publicación de eventos canónicos
    # -----------------------------------------------------------------------

    def _publish_plate_read(
        self,
        result:        ValidationResult,
        evidence_id:   str,
        frame_quality: float,
        retries:       int,
        lane_id:       str,
        trace_id:      Optional[str],
    ) -> None:
        """Publica parking/events/plate_read con el payload canónico del blueprint."""
        payload = {
            "schema_version": "1.2",
            "lane_id":        lane_id,
            "domain":         "linux",
            "plate":          result.plate,
            "confidence":     round(result.confidence, 4),
            "frame_quality":  round(frame_quality, 4),
            "evidence_id":    evidence_id,
            "ocr_engine":     _OCR_ENGINE_VERSION,
            "retries":        retries,
        }
        self.event_bus.publish(
            topic=Topics.PLATE_READ,
            payload=payload,
            event_type="plate_read",
            trace_id=trace_id,
        )
        logger.info(
            "plate_read published | plate=%s confidence=%.2f lane=%s trace_id=%s",
            result.plate, result.confidence, lane_id,
            trace_id or "(auto)",
        )

    def _publish_plate_unreadable(
        self,
        result:      ValidationResult,
        evidence_id: str,
        lane_id:     str,
        trace_id:    Optional[str],
    ) -> None:
        """Publica parking/events/plate_unreadable con el motivo de rechazo."""
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
            "plate_unreadable published | reason=%s raw='%s' confidence=%.2f lane=%s",
            result.rejection_reason, result.raw_text, result.confidence, lane_id,
        )

    # -----------------------------------------------------------------------
    # Carga de configuración
    # -----------------------------------------------------------------------

    def _load_confidence_threshold(self, policies_path: str) -> float:
        """
        Lee ocr.confidence_min de policies.yaml.
        Si el archivo no existe o el campo no está, usa 0.85 como fallback seguro.
        """
        fallback = 0.85
        try:
            with open(policies_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            threshold = config.get("ocr", {}).get("confidence_min", fallback)
            logger.debug("Loaded confidence_min=%.2f from %s", threshold, policies_path)
            return float(threshold)
        except FileNotFoundError:
            logger.warning(
                "policies.yaml not found at '%s', using fallback confidence_min=%.2f",
                policies_path, fallback,
            )
            return fallback
        except (yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
            logger.error(
                "Error reading confidence_min from policies.yaml: %s — using fallback %.2f",
                exc, fallback,
            )
            return fallback
