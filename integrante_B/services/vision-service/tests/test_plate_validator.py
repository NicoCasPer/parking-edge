"""
test_plate_validator.py — Pruebas unitarias del PlateValidator.

Cubren todos los caminos del validador:
  - Placas colombianas válidas (exactas y con ruido OCR corregible)
  - Rechazo por texto vacío
  - Rechazo por baja confianza
  - Rechazo por formato inválido
  - Normalización del separador
  - Correcciones posicionales de OCR (letras↔dígitos)

Ejecutar:
    cd parking-edge
    python -m pytest services/vision-service/tests/test_plate_validator.py -v
"""

import unittest
from services.vision_service.app.plate_validator import (
    PlateValidator,
    ValidationResult,
    DEFAULT_CONFIDENCE_THRESHOLD,
)


class TestPlateValidatorValid(unittest.TestCase):
    """Casos que deben resultar en is_valid=True."""

    def setUp(self):
        self.v = PlateValidator(confidence_threshold=0.60)

    def test_exact_valid_plate(self):
        """Placa exacta sin ruido debe pasar directamente."""
        r = self.v.validate("ABC-123", 0.90)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "ABC-123")
        self.assertIsNone(r.rejection_reason)

    def test_lowercase_input_normalized(self):
        """Tesseract a veces devuelve minúsculas; deben convertirse."""
        r = self.v.validate("abc-123", 0.85)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "ABC-123")

    def test_leading_trailing_whitespace(self):
        """Espacios alrededor del texto son ruido habitual de Tesseract."""
        r = self.v.validate("  XYZ-789  \n", 0.75)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "XYZ-789")

    def test_space_as_separator(self):
        """'ABC 123' (espacio en lugar de guion) debe normalizarse."""
        r = self.v.validate("ABC 123", 0.80)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "ABC-123")

    def test_underscore_as_separator(self):
        r = self.v.validate("DEF_456", 0.70)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "DEF-456")

    def test_at_confidence_threshold(self):
        """Exactamente en el umbral debe pasar (umbral es mínimo inclusivo)."""
        r = self.v.validate("GHI-789", 0.60)
        self.assertTrue(r.is_valid)

    # --- Correcciones de OCR posicionales ---

    def test_ocr_fix_zero_to_O_in_letters(self):
        """'0' en zona de letras es error típico de OCR por la letra 'O'."""
        r = self.v.validate("AB0-123", 0.88)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "ABO-123")

    def test_ocr_fix_one_to_I_in_letters(self):
        """'1' en zona de letras debe corregirse a 'I'."""
        r = self.v.validate("A1C-456", 0.82)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "AIC-456")

    def test_ocr_fix_eight_to_B_in_letters(self):
        """'8' en zona de letras debe corregirse a 'B'."""
        r = self.v.validate("A8C-789", 0.79)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "ABC-789")

    def test_ocr_fix_O_to_zero_in_digits(self):
        """'O' en zona de dígitos es error típico de OCR por el cero."""
        r = self.v.validate("XYZ-1O3", 0.91)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "XYZ-103")

    def test_ocr_fix_I_to_one_in_digits(self):
        """'I' en zona de dígitos debe corregirse a '1'."""
        r = self.v.validate("MNO-I23", 0.84)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "MNO-123")

    def test_ocr_fix_multiple_errors(self):
        """Múltiples errores de OCR en la misma placa deben corregirse todos."""
        # '0BC' → 'OBC' en letras, '1O3' → '103' en dígitos
        r = self.v.validate("0BC-1O3", 0.77)
        self.assertTrue(r.is_valid)
        self.assertEqual(r.plate, "OBC-103")

    def test_raw_text_preserved(self):
        """raw_text siempre debe contener el texto original de Tesseract."""
        raw = "A8C-123"
        r = self.v.validate(raw, 0.80)
        self.assertEqual(r.raw_text, raw)


class TestPlateValidatorInvalid(unittest.TestCase):
    """Casos que deben resultar en is_valid=False."""

    def setUp(self):
        self.v = PlateValidator(confidence_threshold=0.60)

    # --- Texto vacío ---

    def test_empty_string(self):
        r = self.v.validate("", 0.90)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "no_text")
        self.assertIsNone(r.plate)

    def test_whitespace_only(self):
        r = self.v.validate("   \n\t  ", 0.90)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "no_text")

    # --- Baja confianza ---

    def test_below_confidence_threshold(self):
        r = self.v.validate("ABC-123", 0.599)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "low_confidence")
        self.assertIsNone(r.plate)

    def test_zero_confidence(self):
        r = self.v.validate("ABC-123", 0.0)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "low_confidence")

    def test_confidence_checked_before_format(self):
        """Baja confianza debe rechazarse aunque el formato sea inválido también."""
        r = self.v.validate("INVALIDO", 0.30)
        # El rechazo debe ser "low_confidence", no "invalid_format"
        self.assertEqual(r.rejection_reason, "low_confidence")

    # --- Formato inválido ---

    def test_only_letters_no_digits(self):
        r = self.v.validate("ABCDEF", 0.80)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "invalid_format")

    def test_digits_before_letters(self):
        """Formato de placa extranjera (dígitos primero)."""
        r = self.v.validate("123-ABC", 0.85)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "invalid_format")

    def test_too_many_letters(self):
        """4 letras en vez de 3."""
        r = self.v.validate("ABCD-123", 0.80)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "invalid_format")

    def test_too_many_digits(self):
        """4 dígitos en vez de 3."""
        r = self.v.validate("ABC-1234", 0.80)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "invalid_format")

    def test_missing_separator(self):
        """Sin guion el formato no es válido aunque los caracteres sean correctos."""
        r = self.v.validate("ABC123", 0.80)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "invalid_format")

    def test_letter_in_digit_zone_not_fixable(self):
        """'X' en zona de dígitos no tiene corrección conocida → formato inválido."""
        r = self.v.validate("ABC-12X", 0.80)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "invalid_format")

    def test_random_noise_string(self):
        r = self.v.validate("###---@@@", 0.75)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "invalid_format")


class TestPlateValidatorCustomThreshold(unittest.TestCase):
    """Verifica que el umbral configurable funciona correctamente."""

    def test_strict_threshold(self):
        """Con umbral alto (90%), una placa con confianza 85% debe rechazarse."""
        v = PlateValidator(confidence_threshold=0.90)
        r = v.validate("ABC-123", 0.85)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.rejection_reason, "low_confidence")

    def test_lenient_threshold(self):
        """Con umbral bajo (30%), la misma confianza debe pasar."""
        v = PlateValidator(confidence_threshold=0.30)
        r = v.validate("ABC-123", 0.35)
        self.assertTrue(r.is_valid)

    def test_default_threshold_value(self):
        self.assertEqual(DEFAULT_CONFIDENCE_THRESHOLD, 0.60)


class TestValidationResultStr(unittest.TestCase):
    """Verifica que la representación string del resultado es útil para logging."""

    def test_valid_result_str(self):
        v = PlateValidator()
        r = v.validate("ABC-123", 91.0)
        self.assertIn("VALID", str(r))
        self.assertIn("ABC-123", str(r))

    def test_invalid_result_str(self):
        v = PlateValidator()
        r = v.validate("", 0.0)
        self.assertIn("INVALID", str(r))
        self.assertIn("no_text", str(r))


if __name__ == "__main__":
    unittest.main()
