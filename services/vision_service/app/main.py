"""
main.py — Punto de entrada del vision-service (Migrado a TensorFlow Lite Nativo).

Integra la captura de cámara (Juanito_part) con el bus MQTT (integrante_B):
  1. Se suscribe a parking/events/presence_detected.
  2. Por cada evento, lanza un worker thread para no bloquear el loop principal.
  3. El worker: captura ráfaga → selecciona mejor frame → YOLO ROI TFLite → Tesseract →
     normaliza confianza → OCRPipeline.process() → publica plate_read/unreadable.
  4. Limpia los frames temporales después del procesamiento.
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
import tensorflow as tf

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
# Detector YOLO con Motor TensorFlow Lite Nativo
# ---------------------------------------------------------------------------

class YOLO11TFLiteDetector:
    """Clase empaquetadora para realizar inferencia YOLO INT8 usando tf.lite."""
    def __init__(self, model_path: str):
        self.interpreter = tf.lite.Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        
        # Dimensiones de entrada requeridas por el modelo (.tflite)
        input_shape = self.input_details[0]['shape']
        self.model_height = input_shape[1]
        self.model_width = input_shape[2]
        self.input_dtype = self.input_details[0]['dtype']

    def detect(self, img_rgb: np.ndarray, conf_threshold: float = 0.25, nms_threshold: float = 0.45) -> list:
        h_orig, w_orig = img_rgb.shape[:2]
        
        # 1. Preprocesar: Redimensionar imagen al tamaño del modelo
        img_resized = cv2.resize(img_rgb, (self.model_width, self.model_height))
        input_data = np.expand_dims(img_resized, axis=0)
        
        # Manejo de la cuantización INT8 del modelo
        if self.input_dtype == np.int8 or self.input_dtype == np.uint8:
            scale, zero_point = self.input_details[0]['quantization']
            if scale != 0:
                input_data = (input_data / 255.0 / scale) + zero_point
            input_data = input_data.astype(self.input_dtype)
        else:
            input_data = input_data.astype(np.float32) / 255.0
            
        # 2. Inferencia ejecutada directamente en la CPU mediante XNNPACK
        self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
        self.interpreter.invoke()
        
        # 3. Postprocesar: Extraer salidas brutas y aplicar de-cuantización si aplica
        output_tensor = self.interpreter.get_tensor(self.output_details[0]['index'])
        if self.output_details[0]['dtype'] == np.int8 or self.output_details[0]['dtype'] == np.uint8:
            scale, zero_point = self.output_details[0]['quantization']
            output_tensor = (output_tensor.astype(np.float32) - zero_point) * scale
            
        # Transformar tensor de salida (Squeeze + Transponer para formato YOLOv8/v11)
        output = np.squeeze(output_tensor).T  # Shape resultante: (8400, 4 + clases)
        
        boxes, confidences = [], []
        for pred in output:
            scores = pred[4:]
            confidence = float(np.max(scores))
            if confidence > conf_threshold:
                cx, cy, w, h = pred[:4]
                # Re-escalar coordenadas de formato centro a tamaño original de la cámara
                x = int((cx - w / 2) * (w_orig / self.model_width))
                y = int((cy - h / 2) * (h_orig / self.model_height))
                w_box = int(w * (w_orig / self.model_width))
                h_box = int(h * (h_orig / self.model_height))
                
                boxes.append([x, y, w_box, h_box])
                confidences.append(confidence)
                
        # Non-Maximum Suppression (NMS) nativo de OpenCV para mitigar duplicados
        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, nms_threshold)
        
        final_boxes = []
        if len(indices) > 0:
            for i in indices.flatten():
                x, y, w, h = boxes[i]
                # Retornar en el formato estándar xyxy que espera el recorte posterior
                final_boxes.append([max(0, x), max(0, y), min(w_orig, x + w), min(h_orig, y + h)])
                
        return final_boxes


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
            # Carga del detector TFLite personalizado sin dependencia de Ultralytics
            _yolo_model = YOLO11TFLiteDetector(_MODEL_PATH)
            logger.info("Modelo YOLO TFLite cargado correctamente: %s", _MODEL_PATH)
        except Exception as exc:
            logger.error("Error cargando modelo YOLO TFLite: %s", exc)
        return _yolo_model


# ---------------------------------------------------------------------------
# OCR con extracción de confianza (escala 0.0–1.0)
# ---------------------------------------------------------------------------

def _run_tesseract(roi_image: np.ndarray) -> tuple[str, float]:
    """
    Ejecuta Tesseract sobre una imagen ROI y retorna (texto, confianza_0_1).
    """
    if roi_image is None or roi_image.size == 0:
        return "", 0.0

    try:
        import pytesseract

        gray = cv2.cvtColor(roi_image, cv2.COLOR_RGB2GRAY)
        binarized = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

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
    Ejecuta el pipeline completo en un thread worker.
    """
    frames = capture_burst(num_frames=5)
    if not frames:
        logger.warning("No se capturaron frames. Evento ignorado.")
        return

    try:
        # 1. Seleccionar mejor frame
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
        frame_quality = min(sharpness_score / (MIN_SHARPNESS_THRESHOLD * 10), 1.0)

        # 2. Cargar imagen
        img = cv2.imread(best_frame)
        if img is None:
            logger.error("No se pudo leer imagen: %s", best_frame)
            pipeline.process("", 0.0, best_frame, 0.0, lane_id=lane_id, trace_id=trace_id)
            return
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 3. Detección de placa con YOLO TFLite
        model = _get_yolo_model()
        if model is None:
            logger.warning("Modelo YOLO no disponible. plate_unreadable.")
            pipeline.process("", 0.0, best_frame, frame_quality,
                             lane_id=lane_id, trace_id=trace_id)
            return

        # LLAMADA AL NUEVO DETECTOR NATIVO
        boxes = model.detect(img_rgb)

        if len(boxes) == 0:
            logger.info("YOLO no detectó placa en el frame.")
            pipeline.process("", 0.0, best_frame, frame_quality,
                             lane_id=lane_id, trace_id=trace_id)
            return

        # Extracción limpia de coordenadas
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

        # 5. Publicar evento MQTT
        pipeline.process(
            text=raw_text,
            confidence=confidence,
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

    logger.info("vision-service iniciando con soporte TFLite...")

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