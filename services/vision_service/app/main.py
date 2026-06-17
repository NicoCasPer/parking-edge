"""
main.py — Punto de entrada del vision-service (Migrado a TensorFlow Lite Nativo).

Integra la captura de cámara (Juanito_part) con el bus MQTT (integrante_B):
  1. Se suscribe a parking/events/presence_detected.
  2. Por cada evento, lanza un worker thread para no bloquear el loop principal.
  3. El worker abre una SESIÓN de cámara en vivo (una sola a la vez): abre la USB,
     y durante STREAM_MAX_SECONDS reescribe latest.jpg en cada frame (vista en vivo
     del dashboard) mientras corre YOLO ROI TFLite → Tesseract. En cuanto detecta
     una placa CLARA (formato válido + confianza sobre el umbral) publica plate_read
     y termina; el access-orchestrator decide whitelist/pago y abre la barrera.
  4. Si la ventana expira sin placa clara, publica el mejor intento / plate_unreadable.
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
from services.vision_service.app.capture import (
    open_camera,
    write_latest_frame,
    persist_evidence_frame,
)
from services.vision_service.app.quality import MIN_SHARPNESS_THRESHOLD
from services.vision_service.app.ocr_pipeline import OCRPipeline

logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("vision-service")

_MODEL_PATH = os.getenv(
    "MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "../../../Modelo/best_plate_yolo11m_int8.tflite"),
)
_LANE_ID = os.getenv("LANE_ID", "ENTRADA-1")

# Duración máxima de una sesión de cámara en vivo (s) tras detectarse un vehículo.
_STREAM_MAX_SECONDS = float(os.getenv("STREAM_MAX_SECONDS", "12"))

# Frames por segundo de la vista en vivo (latest.jpg). Independiente de YOLO.
_LIVE_FPS = float(os.getenv("LIVE_FPS", "10"))

# Solo una sesión de cámara a la vez: la USB tiene un único dueño.
_session_lock = threading.Lock()

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
        # AÑADIDO: Cerrojo para evitar cruce de hilos en TFLite
        self.lock = threading.Lock()
        
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
            
        # AÑADIDO: Bloqueo exclusivo para la inferencia de TensorFlow Lite
        with self.lock:
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
                # El export TFLite puede dar coords NORMALIZADAS [0,1] o en píxeles
                # del modelo [0, model_width]. Se detecta por magnitud para ser
                # robustos a ambos: si están en [0,1], escalar directo al tamaño de
                # la cámara; si están en píxeles del modelo, escalar por la razón.
                if max(cx, cy, w, h) <= 1.5:
                    sx, sy = w_orig, h_orig
                else:
                    sx, sy = w_orig / self.model_width, h_orig / self.model_height
                # Re-escalar coordenadas de formato centro a tamaño original de la cámara
                x = int((cx - w / 2) * sx)
                y = int((cy - h / 2) * sy)
                w_box = int(w * sx)
                h_box = int(h * sy)
                
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


def _warmup_model() -> None:
    """Ejecuta una inferencia en blanco para pagar el warmup de XNNPACK al arrancar."""
    model = _get_yolo_model()
    if model is None:
        return
    try:
        dummy = np.zeros((model.model_height, model.model_width, 3), dtype=np.uint8)
        t = time.monotonic()
        model.detect(dummy)
        logger.info("YOLO warmup completado en %.2fs", time.monotonic() - t)
    except Exception as exc:
        logger.warning("Warmup YOLO falló: %s", exc)


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

        # Tesseract rinde mucho mejor con caracteres altos: escalar el ROI hasta
        # ~200 px de alto si viene pequeño.
        h, w = gray.shape[:2]
        if 0 < h < 200:
            f = 200.0 / h
            gray = cv2.resize(gray, (int(w * f), 200), interpolation=cv2.INTER_CUBIC)

        binarized = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        # Guardar SIEMPRE lo que ve el OCR para depurar: el recorte a color y la
        # imagen binarizada que entra a Tesseract.
        try:
            edir = os.getenv("EVIDENCE_PATH", "/tmp/parking_evidence")
            cv2.imwrite(os.path.join(edir, "ocr_roi.jpg"),
                        cv2.cvtColor(roi_image, cv2.COLOR_RGB2BGR))
            cv2.imwrite(os.path.join(edir, "ocr_bin.jpg"), binarized)
        except Exception:
            pass

        whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        # psm 7 = una línea de texto (placa completa); 6 = bloque; 8 = palabra.
        best_text, best_conf = "", 0.0
        for psm in (7, 6, 8):
            data = pytesseract.image_to_data(
                binarized,
                config=f"--psm {psm} -c tessedit_char_whitelist={whitelist}",
                output_type=pytesseract.Output.DICT,
            )
            texts, confs = [], []
            for i in range(len(data["text"])):
                t = data["text"][i].strip()
                c = int(data["conf"][i])
                if c > 0 and t:
                    texts.append(t)
                    confs.append(c)
            text = "".join(texts).upper().replace(" ", "")
            conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
            # Preferir lecturas más completas (placa colombiana = 6 chars).
            if text and (len(text) > len(best_text) or
                         (len(text) == len(best_text) and conf > best_conf)):
                best_text, best_conf = text, conf

        return best_text, best_conf

    except Exception as exc:
        logger.error("Error en Tesseract: %s", exc)
        return "", 0.0


# ---------------------------------------------------------------------------
# Calidad de frame (nitidez) sobre un frame en memoria
# ---------------------------------------------------------------------------

def _frame_quality(frame: np.ndarray) -> float:
    """Nitidez Laplaciana normalizada (0–1) de un frame BGR en memoria."""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        return min(sharpness / (MIN_SHARPNESS_THRESHOLD * 10), 1.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Sesión de cámara en vivo por evento de presencia
# ---------------------------------------------------------------------------

def _capture_loop(cap, shared: Dict[str, Any], stop: threading.Event) -> None:
    """
    Hilo de captura: lee frames lo más rápido posible para la vista EN VIVO.

    Reescribe latest.jpg a ~_LIVE_FPS (independiente de lo lento que sea YOLO) y
    deja el último frame en `shared["frame"]` para que el hilo de detección lo
    consuma. Único dueño de la cámara → no hay aperturas concurrentes de /dev/video0.
    """
    min_interval = 1.0 / _LIVE_FPS
    last_write   = 0.0
    while not stop.is_set():
        ok, frame = cap.read()
        if not ok or frame is None or frame.size == 0:
            time.sleep(0.02)
            continue
        shared["frame"] = frame
        now = time.monotonic()
        if now - last_write >= min_interval:
            write_latest_frame(frame)   # vista en vivo del dashboard
            last_write = now


def _run_camera_session(
    pipeline:  OCRPipeline,
    trace_id:  Optional[str],
    lane_id:   str,
) -> None:
    """
    Sesión de cámara en vivo disparada por presence_detected.

    Abre la cámara una sola vez (una sesión a la vez) y arranca dos tareas:
      - captura: transmite la vista en vivo (latest.jpg) a ~_LIVE_FPS,
      - detección: corre YOLO sobre el frame más reciente y, en cuanto lee una
        placa CLARA (formato válido + confianza sobre el umbral), publica
        plate_read y termina → el orchestrator decide whitelist/pago y abre.
    Si la ventana (_STREAM_MAX_SECONDS) expira sin placa clara, publica el mejor
    intento (o plate_unreadable) para dejar traza.

    Desacoplar captura de detección mantiene la vista en vivo fluida aunque la
    inferencia YOLO sea lenta en el BeaglePlay.
    """
    if not _session_lock.acquire(blocking=False):
        logger.info("Sesión de cámara ya activa; se ignora presence_detected | trace_id=%s",
                    trace_id)
        return

    cap = open_camera()
    if cap is None:
        logger.warning("Cámara no disponible. plate_unreadable.")
        pipeline.process("", 0.0, "", 0.0, lane_id=lane_id, trace_id=trace_id)
        _session_lock.release()
        return

    stop      = threading.Event()
    shared: Dict[str, Any] = {"frame": None}
    capturer  = threading.Thread(target=_capture_loop, args=(cap, shared, stop),
                                 daemon=True, name=f"vision-capture-{trace_id}")
    capturer.start()

    try:
        model = _get_yolo_model()
        deadline = time.monotonic() + _STREAM_MAX_SECONDS

        best_conf, best_text, best_frame = -1.0, "", None
        published = False
        yolo_runs = detections = ocr_attempts = 0   # contadores de diagnóstico

        while _running and time.monotonic() < deadline:
            frame = shared["frame"]
            if frame is None or model is None:
                time.sleep(0.05)
                continue

            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            t_det = time.monotonic()
            boxes = model.detect(img_rgb)
            yolo_runs += 1
            if yolo_runs == 1:
                logger.info("YOLO 1ª inferencia: %.2fs | cajas=%d",
                            time.monotonic() - t_det, len(boxes))
            if len(boxes) == 0:
                time.sleep(0.02)
                continue

            detections += 1
            x1, y1, x2, y2 = map(int, boxes[0])
            h, w = img_rgb.shape[:2]
            roi = img_rgb[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
            logger.info("YOLO detectó %d caja(s) | box=(%d,%d,%d,%d) roi=%dx%d",
                        len(boxes), x1, y1, x2, y2, roi.shape[1], roi.shape[0])
            if roi.size == 0:
                continue

            ocr_attempts += 1
            raw_text, confidence = _run_tesseract(roi)
            logger.info("OCR | raw='%s' conf=%.2f", raw_text, confidence)
            if confidence > best_conf:
                best_conf, best_text, best_frame = confidence, raw_text, frame

            # ¿Placa clara? (formato válido + confianza sobre el umbral) → abrir ya.
            if pipeline.validator.validate(raw_text, confidence).is_valid:
                evidence = persist_evidence_frame(frame, trace_id) or ""
                logger.info("Placa clara en vivo | text='%s' confidence=%.2f",
                            raw_text, confidence)
                pipeline.process(raw_text, confidence, evidence, _frame_quality(frame),
                                 lane_id=lane_id, trace_id=trace_id)
                published = True
                break

        logger.info(
            "Fin sesión | yolo_runs=%d detecciones=%d ocr=%d mejor_text='%s' conf=%.2f publicada=%s",
            yolo_runs, detections, ocr_attempts, best_text, max(best_conf, 0.0), published,
        )

        # Ventana terminada sin placa clara: dejar traza del mejor intento.
        if not published:
            fallback = best_frame if best_frame is not None else shared["frame"]
            if fallback is not None:
                evidence = persist_evidence_frame(fallback, trace_id) or ""
                pipeline.process(best_text, max(best_conf, 0.0), evidence,
                                 _frame_quality(fallback),
                                 lane_id=lane_id, trace_id=trace_id)
            else:
                logger.warning("No se capturó ningún frame en la sesión. plate_unreadable.")
                pipeline.process("", 0.0, "", 0.0, lane_id=lane_id, trace_id=trace_id)

    finally:
        stop.set()
        capturer.join(timeout=1.0)
        cap.release()
        _session_lock.release()


# ---------------------------------------------------------------------------
# Callback de evento MQTT presence_detected
# ---------------------------------------------------------------------------

def _make_presence_handler(pipeline: OCRPipeline, lane_id: str):
    def _on_presence_detected(envelope: Dict[str, Any]) -> None:
        trace_id = envelope.get("trace_id")
        logger.info("presence_detected recibido | trace_id=%s", trace_id)

        t = threading.Thread(
            target=_run_camera_session,
            args=(pipeline, trace_id, lane_id),
            daemon=True,
            name=f"vision-session-{trace_id}",
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
        os.path.join(os.path.dirname(__file__), "../../../config/policies.yaml"),
    )
    pipeline = OCRPipeline(event_bus=bus, policies_path=policies_path, lane_id=lane_id)

    bus.subscribe(Topics.PRESENCE_DETECTED, _make_presence_handler(pipeline, lane_id))

    # Calentar el modelo ahora (la 1ª inferencia incluye el warmup de XNNPACK y
    # tarda ~10 s) para que la primera sesión de cámara no se lo coma.
    _warmup_model()

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
