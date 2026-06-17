"""
capture.py — Captura de ráfaga de frames al detectarse un vehículo.

Adaptado de Juanito_part/Modulo_vision/capture.py con las siguientes mejoras:
  - Configuración vía variables de entorno (sin rutas hardcodeadas).
  - Uso de logging en lugar de print.
  - Timestamps en nombres de archivo para evitar colisiones entre eventos.
  - Función cleanup_frames() para liberar espacio en disco tras el procesamiento.
"""

import glob
import logging
import os
import shutil
import time
from typing import List, Optional

import cv2

logger = logging.getLogger(__name__)

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
TMP_DIR = os.getenv("TMP_CAPTURES_PATH", "/tmp/parking_captures")

# Directorio persistente de evidencia que el dashboard sirve para mostrar
# "lo que vio la cámara". A diferencia de TMP_DIR, NO se limpia tras procesar:
# se conserva una ventana rodante de las últimas EVIDENCE_MAX_FILES capturas.
EVIDENCE_DIR       = os.getenv("EVIDENCE_PATH", "/tmp/parking_evidence")
EVIDENCE_MAX_FILES = int(os.getenv("EVIDENCE_MAX_FILES", "30"))
# Nombre fijo del último frame, para previsualización rápida en el dashboard.
EVIDENCE_LATEST    = "latest.jpg"


# ── Captura en vivo (pseudo-streaming para el dashboard) ─────────────────────
# El vision-service abre la cámara al detectarse un vehículo y, mientras dura la
# sesión, reescribe latest.jpg en cada frame. El dashboard refresca esa imagen
# rápido → vista "en vivo" sin que un segundo proceso abra /dev/video0 (la USB
# tiene un único dueño).

# Cuántos nodos /dev/videoN escanear si CAMERA_INDEX no abre (la USB puede caer
# en video0/1/2... y el número cambia al reconectar).
_CAMERA_SCAN_MAX = int(os.getenv("CAMERA_SCAN_MAX", "5"))


def _try_open(index: int) -> Optional["cv2.VideoCapture"]:
    """
    Intenta abrir /dev/video<index> y verifica que entregue un frame real.
    Devuelve el VideoCapture listo, o None. La verificación de frame descarta
    nodos que abren pero no capturan (p.ej. el nodo de metadata de una UVC).
    """
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        return None
    ok, frame = cap.read()
    if not ok or frame is None or frame.size == 0:
        cap.release()
        return None
    return cap


def open_camera() -> Optional["cv2.VideoCapture"]:
    """
    Abre la cámara USB para una sesión de streaming, con autodetección de índice.

    Prueba CAMERA_INDEX primero; si no abre o no entrega frames, escanea el resto
    de nodos /dev/video0.._CAMERA_SCAN_MAX. Devuelve None si ninguno funciona.
    """
    candidates = [CAMERA_INDEX] + [i for i in range(_CAMERA_SCAN_MAX) if i != CAMERA_INDEX]

    cap = None
    used = None
    for idx in candidates:
        cap = _try_open(idx)
        if cap is not None:
            used = idx
            break

    if cap is None:
        logger.error("No se pudo abrir ninguna cámara (probé índices %s)", candidates)
        return None

    if used != CAMERA_INDEX:
        logger.warning(
            "Cámara abierta en /dev/video%d (CAMERA_INDEX=%d no funcionó). "
            "Fija CAMERA_INDEX=%d en app.env para evitar el escaneo.",
            used, CAMERA_INDEX, used,
        )
    else:
        logger.info("Cámara abierta en /dev/video%d", used)

    # Buffer mínimo: queremos el frame más reciente, no una cola con retardo.
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    time.sleep(0.3)  # permitir que el sensor regule la exposición
    return cap


def write_latest_frame(frame) -> None:
    """Reescribe latest.jpg con el frame actual (vista en vivo del dashboard)."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return
    try:
        os.makedirs(EVIDENCE_DIR, exist_ok=True)
        dest = os.path.join(EVIDENCE_DIR, EVIDENCE_LATEST)
        tmp  = dest + ".tmp"
        if cv2.imwrite(tmp, frame):
            os.replace(tmp, dest)   # swap atómico: el dashboard nunca lee a medias
    except Exception as exc:
        logger.debug("No se pudo escribir latest.jpg: %s", exc)


def persist_evidence_frame(frame, trace_id: Optional[str] = None) -> Optional[str]:
    """
    Guarda un frame en memoria como evidencia permanente (galería del dashboard)
    y refresca latest.jpg. Equivale a save_evidence() pero sin pasar por disco.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    try:
        os.makedirs(EVIDENCE_DIR, exist_ok=True)
        ts   = int(time.time() * 1000)
        tag  = (trace_id or "evt").split("-")[0]
        dest = os.path.join(EVIDENCE_DIR, f"{ts}_{tag}.jpg")
        if not cv2.imwrite(dest, frame):
            return None
        write_latest_frame(frame)
        _prune_evidence()
        logger.info("Evidencia guardada para el dashboard: %s", dest)
        return dest
    except Exception as exc:
        logger.warning("No se pudo guardar evidencia: %s", exc)
        return None


def capture_burst(num_frames: int = 5) -> List[str]:
    """
    Captura una ráfaga rápida de frames desde una cámara USB.

    Abre la cámara, captura num_frames imágenes separadas 50 ms entre sí
    y cierra la cámara al finalizar. Los frames se guardan con timestamp
    único para evitar sobreescrituras entre eventos concurrentes.

    Args:
        num_frames: Número de frames a capturar (default 5).

    Returns:
        Lista de rutas a los archivos JPEG guardados.
        Lista vacía si la cámara no está disponible.
    """
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("No se puede acceder a la cámara /dev/video%d", CAMERA_INDEX)
        return []

    # Permitir que el sensor regule la exposición
    time.sleep(0.3)

    os.makedirs(TMP_DIR, exist_ok=True)
    timestamp = int(time.time() * 1000)
    saved_paths: List[str] = []

    try:
        for i in range(num_frames):
            ret, frame = cap.read()
            if not ret or frame is None or frame.size == 0:
                logger.warning("Frame %d inválido o no capturado — omitiendo.", i)
                continue

            path = os.path.join(TMP_DIR, f"frame_{timestamp}_{i}.jpg")
            if cv2.imwrite(path, frame):
                saved_paths.append(path)
            else:
                logger.warning("No se pudo guardar frame %d en %s", i, path)

            time.sleep(0.05)  # 50 ms entre frames para capturar movimiento leve

    except Exception as exc:
        logger.error("Error durante captura de ráfaga: %s", exc)
    finally:
        cap.release()

    logger.info(
        "Ráfaga completada: %d/%d frames guardados en '%s'",
        len(saved_paths), num_frames, TMP_DIR,
    )
    return saved_paths


def save_evidence(frame_path: str, trace_id: Optional[str] = None) -> Optional[str]:
    """
    Conserva una copia del frame de evidencia en EVIDENCE_DIR para que el
    dashboard pueda mostrar lo que vio la cámara.

    Copia `frame_path` a EVIDENCE_DIR con un nombre único (timestamp + trace_id),
    actualiza el alias `latest.jpg` y purga las capturas más antiguas dejando
    como máximo EVIDENCE_MAX_FILES. Se llama ANTES de cleanup_frames().

    Args:
        frame_path: Ruta del frame a preservar (típicamente el mejor frame).
        trace_id:   Id de trazabilidad del evento, para nombrar el archivo.

    Returns:
        Ruta del archivo de evidencia guardado, o None si falló.
    """
    if not frame_path or not os.path.exists(frame_path):
        return None

    try:
        os.makedirs(EVIDENCE_DIR, exist_ok=True)
        ts   = int(time.time() * 1000)
        tag  = (trace_id or "evt").split("-")[0]
        dest = os.path.join(EVIDENCE_DIR, f"{ts}_{tag}.jpg")

        shutil.copyfile(frame_path, dest)
        # Alias estable para la previsualización en vivo del dashboard.
        shutil.copyfile(frame_path, os.path.join(EVIDENCE_DIR, EVIDENCE_LATEST))

        _prune_evidence()
        logger.info("Evidencia guardada para el dashboard: %s", dest)
        return dest
    except Exception as exc:
        logger.warning("No se pudo guardar evidencia desde %s: %s", frame_path, exc)
        return None


def _prune_evidence() -> None:
    """Mantiene solo las EVIDENCE_MAX_FILES capturas más recientes (excluye latest)."""
    try:
        files = [
            p for p in glob.glob(os.path.join(EVIDENCE_DIR, "*.jpg"))
            if os.path.basename(p) != EVIDENCE_LATEST
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        for old in files[EVIDENCE_MAX_FILES:]:
            try:
                os.remove(old)
            except OSError:
                pass
    except Exception as exc:
        logger.debug("Error purgando evidencia: %s", exc)


def cleanup_frames(frame_paths: List[str]) -> None:
    """
    Elimina los archivos de frame después de su procesamiento.

    Args:
        frame_paths: Lista de rutas retornadas por capture_burst().
    """
    for path in frame_paths:
        try:
            os.remove(path)
        except OSError as exc:
            logger.debug("No se pudo eliminar frame temporal %s: %s", path, exc)
    logger.debug("Limpieza de %d frames completada.", len(frame_paths))
