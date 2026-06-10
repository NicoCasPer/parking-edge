"""
event_models.py — Modelos canónicos de eventos del sistema de parqueadero.

Todos los mensajes MQTT del sistema siguen la estructura:
    {
        "trace_id":   str (UUID),
        "timestamp":  str (ISO 8601 UTC),
        "event_type": str,
        "source":     str (nombre del servicio emisor),
        "payload":    dict
    }

Cada Payload concreto documenta el contrato de datos entre servicios.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


# ---------------------------------------------------------------------------
# Tópicos MQTT canónicos — fuente única de verdad para todos los servicios
# ---------------------------------------------------------------------------

class Topics:
    PREFIX = "parking"

    # Eventos (publicados por los servicios, consumidos por el orquestador)
    PRESENCE_DETECTED = f"{PREFIX}/events/presence_detected"
    PLATE_READ        = f"{PREFIX}/events/plate_read"
    PLATE_UNREADABLE  = f"{PREFIX}/events/plate_unreadable"
    ACCESS_GRANTED    = f"{PREFIX}/events/access_granted"
    ACCESS_DENIED     = f"{PREFIX}/events/access_denied"
    ASSISTED_MODE     = f"{PREFIX}/events/assisted_mode"
    SYSTEM_HEARTBEAT  = f"{PREFIX}/events/system_heartbeat"

    # Pagos
    PAYMENT_EVENT     = f"{PREFIX}/events/payment"

    # Comandos (publicados por el orquestador, consumidos por hardware-controller)
    BARRIER_COMMAND   = f"{PREFIX}/commands/barrier"
    MANUAL_OVERRIDE   = f"{PREFIX}/commands/override"


# ---------------------------------------------------------------------------
# Envelope canónico
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """
    Estructura raíz de cualquier mensaje en el bus.
    Usar build_event() para construir instancias correctas.
    """
    event_type: str
    payload:    Dict[str, Any]
    source:     str = ""
    trace_id:   str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:  str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_event(
    event_type: str,
    payload:    Dict[str, Any],
    source:     str = "",
    trace_id:   Optional[str] = None,
) -> Dict[str, Any]:
    """
    Helper para construir un envelope canónico como dict listo para publicar.

    Args:
        event_type: Identificador del evento (ej. "plate_read").
        payload:    Datos específicos del evento.
        source:     Nombre del servicio que emite el evento.
        trace_id:   UUID de trazabilidad. Se genera automáticamente si es None.

    Returns:
        dict con la estructura canónica completa.

    Example:
        >>> msg = build_event("plate_read", {"plate": "ABC-123", "confidence": 91.5}, source="vision-service")
        >>> msg["event_type"]
        'plate_read'
    """
    return Event(
        event_type=event_type,
        payload=payload,
        source=source,
        trace_id=trace_id or str(uuid.uuid4()),
    ).to_dict()


# ---------------------------------------------------------------------------
# Payloads concretos (documentan el contrato entre servicios)
# ---------------------------------------------------------------------------

@dataclass
class PlateReadPayload:
    """
    Emitido por: vision-service
    Consumido por: access-orchestrator
    """
    plate:      str    # Texto extraído y validado, ej. "ABC-123"
    confidence: float  # Confianza media de Tesseract (0.0 – 100.0)
    image_path: Optional[str] = None  # Path local para auditoría, opcional


@dataclass
class PlateUnreadablePayload:
    """
    Emitido por: vision-service cuando OCR falla o formato no es válido.
    Consumido por: access-orchestrator → activa modo asistido.
    """
    reason:     str   # "low_confidence" | "invalid_format" | "no_text"
    confidence: float
    raw_text:   str = ""  # Texto crudo que devolvió Tesseract (para debugging)


@dataclass
class AccessDecisionPayload:
    """
    Emitido por: access-orchestrator
    Consumido por: hardware-controller (para abrir/cerrar barrera) y dashboard.
    """
    plate:       str
    decision:    str            # "ACCESS_GRANTED" | "ACCESS_DENIED"
    reason:      str            # "whitelist" | "payment_approved" | "payment_denied" | "unknown_plate"
    operator_id: Optional[str] = None  # Presente solo en overrides manuales


@dataclass
class BarrierCommandPayload:
    """
    Emitido por: access-orchestrator
    Consumido por: hardware-controller → enviado al M4 vía RPMsg.
    """
    action:   str   # "OPEN" | "CLOSE"
    source:   str   # "orchestrator" | "manual_override"
    trace_id: str = ""  # Hereda el trace_id de la decisión de acceso


@dataclass
class SystemHeartbeatPayload:
    """
    Emitido por: connectivity-service cada 30 segundos.
    Consumido por: dashboard (para mostrar salud del sistema).
    """
    cpu_percent:    float
    memory_percent: float
    disk_percent:   float
    uptime_seconds: float
    service_name:   str
    temperature_c:  Optional[float] = None  # Disponible en BeaglePlay si psutil lo soporta
