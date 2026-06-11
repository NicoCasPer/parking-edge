"""
capture.py — Captura de ráfaga de frames al detectarse un vehículo.

Adaptado de Juanito_part/Modulo_vision/capture.py con las siguientes mejoras:
  - Configuración vía variables de entorno (sin rutas hardcodeadas).
  - Uso de logging en lugar de print.
  - Timestamps en nombres de archivo para evitar colisiones entre eventos.
  - Función cleanup_frames() para liberar espacio en disco tras el procesamiento.
"""

import logging
import os
import time
from typing import List

import cv2

logger = logging.getLogger(__name__)

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
TMP_DIR = os.getenv("TMP_CAPTURES_PATH", "/tmp/parking_captures")


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
