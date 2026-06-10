"""
main.py — Punto de entrada del vision-service.

Integra la captura de cámara (Juanito_part) con el bus MQTT (integrante_B):
  1. Se suscribe a parking/events/presence_detected.
  2. Por cada evento, lanza un worker thread para no bloquear el loop principal.
  3. El worker: captura ráfaga → selecciona mejor frame → YOLO ROI → Tesseract →
     normaliza confianza → OCRPipeline.process() → publica plate_read/unreadable.
  4. Limpia los frames temporales después del procesamiento.

Variables de entorno:
    MQTT_BROKER_HOST  — default: localhost
    MQTT_BROKER_PORT  — default: 1883
    POLICIES_PATH     — ruta a policies.yaml
    CAMERA_INDEX      — default: 0
    TMP_CAPTURES_PATH — default: /tmp/parking_captures
    LANE_ID           — default: ENTRADA-1
    MODEL_PATH        — ruta al modelo YOLO (default: Modelo/best_plate_yolo11m_int8.tflite)
    LOG_LEVEL         — default: INFO
"""

import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, Optional

import cv2
import numpy as np

from services.common.event_bus import EventBus
from services.common.event_models import Topics
from services.vision_service.app.capture import capture_burst, cleanup_frames
from services.vision_service.app.frame_selector import select_best_frame
from services.vision_service.app.quality import laplacian_variance, MIN_SHARPNESS_THRESHOLD
from services.vision_service.app.ocr_pipeline import OCRPipeline

logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("vision-service")

_MODEL_PATH = os.getenv(
    "MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "../../../../Modelo/best_plate_yolo11m_int8.tflite"),
)
_LANE_ID = os.getenv("LANE_ID", "ENTRADA-1")

# Control de señal de cierre
_running = True


def _handle_shutdown(signum, frame) -> None:
    global _running
    logger.info("Señal de cierre recibida (%s).", signum)
    _running = False


# ---------------------------------------------------------------------------
# YOLO lazy loader
# ---------------------------------------------------------------------------

_yolo_model = None
_yolo_lock  = threading.Lock()


def _get_yolo_model():
    global _yolo_model
    with _yolo_lock:
        if _yolo_model is not None:
            return _yolo_model
        if not os.path.exists(_MODEL_PATH):
            logger.error("Modelo YOLO no encontrado: %s", _MODEL_PATH)
            return None
        try:
            from ultralytics import YOLO
            _yolo_model = YOLO(_MODEL_PATH)
            logger.info("Modelo YOLO cargado: %s", _MODEL_PATH)
        except Exception as exc:
            logger.error("Error cargando modelo YOLO: %s", exc)
        return _yolo_model


# ---------------------------------------------------------------------------
# OCR con extracción de confianza (escala 0.0–1.0)
# ---------------------------------------------------------------------------

def _run_tesseract(roi_image: np.ndarray) -> tuple[str, float]:
    """
    Ejecuta Tesseract sobre una imagen ROI y retorna (texto, confianza_0_1).
    Confianza promedio de los caracteres con conf > 0 (–1 significa no aplica).

    Returns:
        (texto, confianza) donde confianza está en 0.0–1.0.
        ("", 0.0) si hay error o ROI vacía.
    """
    if roi_image is None or roi_image.size == 0:
        return "", 0.0

    try:
        import pytesseract

        gray = cv2.cvtColor(roi_image, cv2.COLOR_RGB2GRAY)
        binarized = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        # image_to_data retorna confianza por palabra (0–100, –1 = no aplica)
        data = pytesseract.image_to_data(
            binarized,
            config=r"--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            output_type=pytesseract.Output.DICT,
        )
        texts = [
            data["text"][i]
            for i in range(len(data["text"]))
            if int(data["conf"][i]) > 0 and data["text"][i].strip()
        ]
        confs = [
            int(data["conf"][i])
            for i in range(len(data["text"]))
            if int(data["conf"][i]) > 0 and data["text"][i].strip()
        ]

        raw_text = "".join(texts).strip().upper().replace(" ", "")
        confidence_0_1 = (sum(confs) / len(confs) / 100.0) if confs else 0.0

        return raw_text, confidence_0_1

    except Exception as exc:
        logger.error("Error en Tesseract: %s", exc)
        return "", 0.0


# ---------------------------------------------------------------------------
# Worker de procesamiento por evento de presencia
# ---------------------------------------------------------------------------

def _process_presence_event(
    pipeline:  OCRPipeline,
    trace_id:  Optional[str],
    lane_id:   str,
) -> None:
    """
    Ejecuta el pipeline completo en un thread worker:
      capture → select_best_frame → YOLO → Tesseract → OCRPipeline.process()
    """
    frames = capture_burst(num_frames=5)
    if not frames:
        logger.warning("No se capturaron frames. Evento ignorado.")
        return

    try:
        # 1. Seleccionar mejor frame (por nitidez Laplaciana)
        best_frame = select_best_frame(frames)
        if best_frame is None:
            logger.warning("Todos los frames son de baja calidad. plate_unreadable.")
            pipeline.process(
                text="",
                confidence=0.0,
                evidence_id="",
                frame_quality=0.0,
                lane_id=lane_id,
                trace_id=trace_id,
            )
            return

        sharpness_score = laplacian_variance(best_frame)
        # Normalizar nitidez a 0–1 usando umbral como referencia (>1.0 se satura a 1.0)
        frame_quality = min(sharpness_score / (MIN_SHARPNESS_THRESHOLD * 10), 1.0)

        # 2. Cargar imagen
        img = cv2.imread(best_frame)
        if img is None:
            logger.error("No se pudo leer imagen: %s", best_frame)
            pipeline.process("", 0.0, best_frame, 0.0, lane_id=lane_id, trace_id=trace_id)
            return
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 3. Detección de placa con YOLO
        model = _get_yolo_model()
        if model is None:
            logger.warning("Modelo YOLO no disponible. plate_unreadable.")
            pipeline.process("", 0.0, best_frame, frame_quality,
                             lane_id=lane_id, trace_id=trace_id)
            return

        results = model(img_rgb, verbose=False)
        boxes = results[0].boxes.xyxy.cpu().numpy() if results else []

        if len(boxes) == 0:
            logger.info("YOLO no detectó placa en el frame.")
            pipeline.process("", 0.0, best_frame, frame_quality,
                             lane_id=lane_id, trace_id=trace_id)
            return

        x1, y1, x2, y2 = map(int, boxes[0])
        h, w = img_rgb.shape[:2]
        roi = img_rgb[
            max(0, y1):min(h, y2),
            max(0, x1):min(w, x2),
        ]

        if roi.size == 0:
            logger.warning("ROI vacía después de recorte.")
            pipeline.process("", 0.0, best_frame, frame_quality,
                             lane_id=lane_id, trace_id=trace_id)
            return

        # 4. OCR con confianza normalizada
        raw_text, confidence = _run_tesseract(roi)

        logger.info(
            "OCR completado | text='%s' confidence=%.2f frame_quality=%.2f",
            raw_text, confidence, frame_quality,
        )

        # 5. Publicar evento MQTT (plate_read o plate_unreadable)
        pipeline.process(
            text=raw_text,
            confidence=confidence,     # ya está en 0.0–1.0
            evidence_id=best_frame,
            frame_quality=frame_quality,
            lane_id=lane_id,
            trace_id=trace_id,
        )

    finally:
        cleanup_frames(frames)


# ---------------------------------------------------------------------------
# Callback de evento MQTT presence_detected
# ---------------------------------------------------------------------------

def _make_presence_handler(pipeline: OCRPipeline, lane_id: str):
    def _on_presence_detected(envelope: Dict[str, Any]) -> None:
        trace_id = envelope.get("trace_id")
        logger.info("presence_detected recibido | trace_id=%s", trace_id)

        # Lanzar en thread para no bloquear el loop MQTT ni el heartbeat del M4
        t = threading.Thread(
            target=_process_presence_event,
            args=(pipeline, trace_id, lane_id),
            daemon=True,
            name=f"vision-worker-{trace_id}",
        )
        t.start()

    return _on_presence_detected


# ---------------------------------------------------------------------------
# Arranque del servicio
# ---------------------------------------------------------------------------

def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT,  _handle_shutdown)

    logger.info("vision-service iniciando...")

    lane_id = os.getenv("LANE_ID", _LANE_ID)

    bus = EventBus(service_name="vision-service")
    try:
        bus.connect(max_retries=5)
    except ConnectionError as exc:
        logger.critical("No se puede conectar al broker MQTT: %s — abortando.", exc)
        sys.exit(1)

    policies_path = os.getenv(
        "POLICIES_PATH",
        os.path.join(os.path.dirname(__file__), "../../../../config/policies.yaml"),
    )
    pipeline = OCRPipeline(event_bus=bus, policies_path=policies_path, lane_id=lane_id)

    # Suscribir al evento de presencia de vehículo (publicado por hardware-controller)
    bus.subscribe(Topics.PRESENCE_DETECTED, _make_presence_handler(pipeline, lane_id))

    logger.info("vision-service listo | lane=%s model=%s", lane_id, _MODEL_PATH)

    try:
        while _running:
            time.sleep(1.0)
    finally:
        logger.info("Cerrando vision-service...")
        bus.disconnect()
        logger.info("vision-service detenido.")


if __name__ == "__main__":
    main()
