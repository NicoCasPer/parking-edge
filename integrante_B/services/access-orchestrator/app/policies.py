"""
policies.py — Carga y expone la configuración de operación desde policies.yaml.

Lee el archivo en arranque y provee acceso tipado a cada parámetro.
Ningún servicio debe hardcodear valores de negocio; todo pasa por aquí.

Configuración relevante para el orquestador (sección access del YAML):
    default_mode:      "FAIL_CLOSED" | "FAIL_OPEN_LIMITED" | "ASSISTED"
    whitelist_ttl_min: minutos de validez de entradas de whitelist (cache local)
    assisted_timeout_s: segundos antes de que el modo asistido auto-deniegue

Configuración OCR (sección ocr):
    confidence_min:  umbral mínimo de confianza (0.0–1.0)
    max_retries:     reintentos ante frame de baja calidad

Uso:
    policies = Policies.load()
    if policies.default_mode == "FAIL_CLOSED":
        ...
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_POLICIES_PATH = os.getenv(
    "POLICIES_PATH",
    os.path.join(os.path.dirname(__file__), "../../../../config/policies.yaml"),
)


@dataclass
class OCRPolicies:
    confidence_min:   float = 0.85
    max_retries:      int   = 3
    retry_window_ms:  int   = 900
    plate_regex:      str   = r"^[A-Z]{3}-[0-9]{3}$"


@dataclass
class AccessPolicies:
    default_mode:       str   = "FAIL_CLOSED"   # FAIL_CLOSED | FAIL_OPEN_LIMITED | ASSISTED
    whitelist_ttl_min:  int   = 120
    assisted_timeout_s: int   = 120


@dataclass
class ExternalProviderPolicies:
    timeout_ms:      int = 1200
    max_retries:     int = 2
    backoff_base_ms: int = 400


@dataclass
class CircuitBreakerPolicies:
    fail_threshold:   int = 5
    reset_timeout_s:  int = 30


@dataclass
class Policies:
    ocr:               OCRPolicies               = field(default_factory=OCRPolicies)
    access:            AccessPolicies            = field(default_factory=AccessPolicies)
    external_provider: ExternalProviderPolicies  = field(default_factory=ExternalProviderPolicies)
    circuit_breaker:   CircuitBreakerPolicies    = field(default_factory=CircuitBreakerPolicies)

    # ------------------------------------------------------------------
    # Propiedades de acceso rápido (los más usados por el orquestador)
    # ------------------------------------------------------------------

    @property
    def default_mode(self) -> str:
        return self.access.default_mode

    @property
    def assisted_timeout_s(self) -> int:
        return self.access.assisted_timeout_s

    @property
    def confidence_min(self) -> float:
        return self.ocr.confidence_min

    # ------------------------------------------------------------------
    # Constructor desde archivo
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str = _DEFAULT_POLICIES_PATH) -> "Policies":
        """
        Carga policies.yaml y construye la instancia.

        Si el archivo no existe o tiene un error, retorna valores por defecto
        con un WARNING (no aborta el arranque del servicio).

        Args:
            path: Ruta al archivo policies.yaml.

        Returns:
            Instancia de Policies con los valores del archivo o defaults.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            logger.info("Policies loaded from '%s'", path)
            return cls._from_dict(raw)

        except FileNotFoundError:
            logger.warning(
                "policies.yaml not found at '%s' — using all defaults.", path
            )
            return cls()

        except yaml.YAMLError as exc:
            logger.error(
                "Malformed policies.yaml at '%s': %s — using all defaults.", path, exc
            )
            return cls()

    @classmethod
    def _from_dict(cls, raw: dict) -> "Policies":
        """Construye la instancia a partir del dict parseado por yaml.safe_load."""
        ocr_raw  = raw.get("ocr",  {})
        acc_raw  = raw.get("access", {})
        ext_raw  = raw.get("external_provider", {})
        cb_raw   = raw.get("circuit_breaker", {})

        return cls(
            ocr=OCRPolicies(
                confidence_min  = float(ocr_raw.get("confidence_min",  0.85)),
                max_retries     = int(ocr_raw.get("max_retries",     3)),
                retry_window_ms = int(ocr_raw.get("retry_window_ms", 900)),
                plate_regex     = str(ocr_raw.get("plate_regex", r"^[A-Z]{3}-[0-9]{3}$")),
            ),
            access=AccessPolicies(
                default_mode       = str(acc_raw.get("default_mode", "FAIL_CLOSED")),
                whitelist_ttl_min  = int(acc_raw.get("whitelist_ttl_min",  120)),
                assisted_timeout_s = int(acc_raw.get("assisted_timeout_s", 120)),
            ),
            external_provider=ExternalProviderPolicies(
                timeout_ms      = int(ext_raw.get("timeout_ms",      1200)),
                max_retries     = int(ext_raw.get("max_retries",     2)),
                backoff_base_ms = int(ext_raw.get("backoff_base_ms", 400)),
            ),
            circuit_breaker=CircuitBreakerPolicies(
                fail_threshold  = int(cb_raw.get("fail_threshold",  5)),
                reset_timeout_s = int(cb_raw.get("reset_timeout_s", 30)),
            ),
        )
