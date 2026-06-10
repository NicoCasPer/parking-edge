"""
quality.py — Métricas de calidad de imagen para selección de frames.

Responsabilidad única: calcular la varianza del Laplaciano como indicador
de nitidez (alta varianza = imagen nítida; baja varianza = imagen borrosa).
"""

import logging

import cv2

logger = logging.getLogger(__name__)

# Umbral mínimo de nitidez Laplaciana para considerar un frame procesable.
# Frames por debajo de este valor son demasiado borrosos para OCR confiable.
MIN_SHARPNESS_THRESHOLD = 30.0


def laplacian_variance(image_path: str) -> float:
    """
    Calcula la varianza del Laplaciano de una imagen en escala de grises.

    Args:
        image_path: Ruta al archivo de imagen.

    Returns:
        Varianza del Laplaciano (mayor = más nítido). Retorna 0.0 si hay error.
    """
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            logger.warning("No se pudo leer la imagen para calcular nitidez: %s", image_path)
            return 0.0
        return float(cv2.Laplacian(img, cv2.CV_64F).var())
    except Exception as exc:
        logger.warning("Error calculando nitidez en %s: %s", image_path, exc)
        return 0.0


def is_sharp_enough(image_path: str, threshold: float = MIN_SHARPNESS_THRESHOLD) -> bool:
    """
    Determina si un frame supera el umbral mínimo de nitidez.

    Args:
        image_path: Ruta al archivo de imagen.
        threshold:  Varianza Laplaciana mínima aceptable.

    Returns:
        True si el frame es suficientemente nítido para OCR.
    """
    return laplacian_variance(image_path) >= threshold
