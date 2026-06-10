"""
plate_validator.py — Validación de texto OCR contra el formato de placa colombiana.

Responsabilidades:
  1. Normalizar el texto crudo que devuelve Tesseract (limpiar ruido, corregir
     errores de OCR frecuentes en placas).
  2. Validar que el texto normalizado cumple el formato colombiano: AAA-NNN
     (tres letras mayúsculas, guion, tres dígitos).
  3. Evaluar si la confianza media del OCR supera el umbral mínimo configurable.
  4. Devolver un ValidationResult claro con la razón de rechazo cuando falla.

Formato colombiano soportado:
  - Vehículos particulares y motos: [A-Z]{3}-[0-9]{3}  (ej. ABC-123)

Uso:
    validator = PlateValidator(confidence_threshold=0.60)
    result = validator.validate("A8C-123", confidence=0.85)
    if result.is_valid:
        print(result.plate)   # "ABC-123"  (B corregido desde 8)
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Formato colombiano: tres letras mayúsculas, guion, tres dígitos
_PLATE_REGEX = re.compile(r'^[A-Z]{3}-\d{3}$')

# Umbral de confianza por defecto (escala 0.0–1.0, alineado con policies.yaml)
DEFAULT_CONFIDENCE_THRESHOLD = 0.60

# Errores frecuentes de Tesseract en cada zona de la placa.
# Clave = carácter erróneo que devuelve el OCR, valor = carácter correcto.
_LETTER_FIXES: dict[str, str] = {
    "0": "O",   # cero → letra O
    "1": "I",   # uno  → letra I
    "8": "B",   # ocho → letra B
    "5": "S",   # cinco → letra S
    "6": "G",   # seis → letra G
    "2": "Z",   # dos  → letra Z
}

_DIGIT_FIXES: dict[str, str] = {
    "O": "0",   # letra O → cero
    "I": "1",   # letra I → uno
    "l": "1",   # ele minúscula → uno
    "B": "8",   # letra B → ocho
    "S": "5",   # letra S → cinco
    "G": "6",   # letra G → seis
    "Z": "2",   # letra Z → dos
}


# ---------------------------------------------------------------------------
# Resultado de validación
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """
    Encapsula el resultado completo de validar un texto OCR.

    Attributes:
        is_valid:         True si el texto cumple formato y supera el umbral de confianza.
        plate:            Texto normalizado y corregido (ej. "ABC-123").
                          None si is_valid es False.
        raw_text:         Texto exacto devuelto por Tesseract, sin modificar.
        confidence:       Confianza media reportada por Tesseract (0.0–100.0).
        rejection_reason: Código de rechazo cuando is_valid es False:
                            "no_text"          — el OCR no extrajo ningún texto
                            "low_confidence"   — confianza por debajo del umbral
                            "invalid_format"   — texto no coincide con formato colombiano
                          None cuando is_valid es True.
    """
    is_valid:         bool
    plate:            Optional[str]
    raw_text:         str
    confidence:       float
    rejection_reason: Optional[str] = None

    def __str__(self) -> str:
        if self.is_valid:
            return f"VALID plate={self.plate} confidence={self.confidence:.2f}"
        return (
            f"INVALID reason={self.rejection_reason} "
            f"raw='{self.raw_text}' confidence={self.confidence:.2f}"
        )


# ---------------------------------------------------------------------------
# Validador principal
# ---------------------------------------------------------------------------

class PlateValidator:
    """
    Valida texto OCR contra el formato de placa colombiana.

    Instanciar una sola vez por servicio y reutilizar.
    """

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> None:
        """
        Args:
            confidence_threshold: Confianza mínima aceptable (0.0–1.0, ej. 0.85).
                                  Alineado con el campo ocr.confidence_min de policies.yaml.
                                  Textos por debajo se rechazan con "low_confidence"
                                  aunque el formato sea correcto.
        """
        self.confidence_threshold = confidence_threshold
        logger.info(
            "PlateValidator initialized | confidence_threshold=%.2f",
            self.confidence_threshold,
        )

    def validate(self, raw_text: str, confidence: float) -> ValidationResult:
        """
        Valida el texto OCR crudo contra el formato de placa colombiana.

        El proceso sigue este orden:
            1. Verificar que hay texto (no vacío).
            2. Verificar umbral de confianza.
            3. Normalizar: limpiar caracteres extraños y corregir errores de OCR.
            4. Validar con regex.

        Args:
            raw_text:   Texto devuelto por Tesseract (puede tener espacios,
                        saltos de línea o caracteres extraños).
            confidence: Confianza media de Tesseract para este texto (0.0–1.0).

        Returns:
            ValidationResult con is_valid=True y plate normalizada,
            o is_valid=False con rejection_reason indicando el motivo.
        """
        # --- 1. Texto vacío ---
        if not raw_text or not raw_text.strip():
            logger.debug("Validation failed: empty OCR output")
            return ValidationResult(
                is_valid=False,
                plate=None,
                raw_text=raw_text,
                confidence=confidence,
                rejection_reason="no_text",
            )

        # --- 2. Umbral de confianza ---
        if confidence < self.confidence_threshold:
            logger.debug(
                "Validation failed: low confidence | confidence=%.2f threshold=%.2f",
                confidence, self.confidence_threshold,
            )
            return ValidationResult(
                is_valid=False,
                plate=None,
                raw_text=raw_text,
                confidence=confidence,
                rejection_reason="low_confidence",
            )

        # --- 3. Normalizar ---
        normalized = self._normalize(raw_text)

        # --- 4. Validar formato ---
        if not _PLATE_REGEX.match(normalized):
            logger.debug(
                "Validation failed: invalid format | normalized='%s' raw='%s'",
                normalized, raw_text,
            )
            return ValidationResult(
                is_valid=False,
                plate=None,
                raw_text=raw_text,
                confidence=confidence,
                rejection_reason="invalid_format",
            )

        logger.info(
            "Plate validated | plate=%s confidence=%.2f", normalized, confidence
        )
        return ValidationResult(
            is_valid=True,
            plate=normalized,
            raw_text=raw_text,
            confidence=confidence,
            rejection_reason=None,
        )

    # -----------------------------------------------------------------------
    # Normalización interna
    # -----------------------------------------------------------------------

    def _normalize(self, text: str) -> str:
        """
        Limpia y corrige el texto OCR para maximizar el match con el regex.

        Pasos:
            1. Strip y convertir a mayúsculas.
            2. Reemplazar separadores alternativos (espacio, guion bajo) por guion.
            3. Descartar cualquier carácter que no sea letra, dígito o guion.
            4. Aplicar correcciones de OCR específicas por zona:
               - Zona letras (posiciones 0-2): corregir dígitos que parecen letras.
               - Zona dígitos (posiciones 4-6): corregir letras que parecen dígitos.

        Args:
            text: Texto crudo de Tesseract.

        Returns:
            Texto normalizado en formato "XXX-NNN" si es posible,
            o el texto limpio tal cual si no tiene la estructura esperada.
        """
        # Paso 1: limpiar y mayúsculas
        cleaned = text.strip().upper()

        # Paso 2: normalizar el separador
        # Tesseract a veces devuelve "ABC 123", "ABC_123" o "ABC.123"
        for sep in (" ", "_", ".", ",", ";"):
            cleaned = cleaned.replace(sep, "-")

        # Paso 3: descartar caracteres no esperados (ruido OCR)
        cleaned = re.sub(r"[^A-Z0-9\-]", "", cleaned)

        # Paso 4: corrección posicional de errores de OCR
        # Solo aplicamos si la longitud es 7 (ABC-123) para no corromper casos atípicos
        if len(cleaned) == 7 and cleaned[3] == "-":
            letter_part = cleaned[:3]
            digit_part  = cleaned[4:]

            letter_part = "".join(_LETTER_FIXES.get(c, c) for c in letter_part)
            digit_part  = "".join(_DIGIT_FIXES.get(c, c)  for c in digit_part)

            cleaned = f"{letter_part}-{digit_part}"

        return cleaned
