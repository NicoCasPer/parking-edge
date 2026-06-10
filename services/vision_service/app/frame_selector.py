"""
frame_selector.py — Selección del frame más nítido de una ráfaga de captura.

Usa la varianza del Laplaciano (quality.py) para elegir el frame con mayor
puntuación de nitidez. Si ningún frame supera el umbral mínimo, retorna None
para que el pipeline active el flujo plate_unreadable en vez de intentar OCR
sobre material de baja calidad.
"""

import logging
from typing import List, Optional

from services.vision_service.app.quality import laplacian_variance, MIN_SHARPNESS_THRESHOLD

logger = logging.getLogger(__name__)


def select_best_frame(
    frame_paths: List[str],
    min_sharpness: float = MIN_SHARPNESS_THRESHOLD,
) -> Optional[str]:
    """
    Elige el frame con mayor varianza Laplaciana dentro de una ráfaga.

    Args:
        frame_paths:   Lista de rutas a los frames capturados.
        min_sharpness: Umbral mínimo de nitidez. Si el mejor frame no lo
                       supera, se retorna None (todos los frames son borrosos).

    Returns:
        Ruta al frame más nítido que supera el umbral, o None si:
          - frame_paths está vacío
          - ningún frame supera min_sharpness
    """
    if not frame_paths:
        logger.warning("frame_selector: lista de frames vacía.")
        return None

    scores = {path: laplacian_variance(path) for path in frame_paths}
    best_path = max(scores, key=lambda p: scores[p])
    best_score = scores[best_path]

    logger.info(
        "Mejor frame: %s (nitidez=%.2f, umbral=%.2f)",
        best_path, best_score, min_sharpness,
    )

    if best_score < min_sharpness:
        logger.warning(
            "Todos los frames tienen nitidez insuficiente (mejor=%.2f < umbral=%.2f). "
            "Activar flujo plate_unreadable.",
            best_score, min_sharpness,
        )
        return None

    return best_path
