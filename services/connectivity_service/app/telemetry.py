"""
parking-edge/services/connectivity-service/app/telemetry.py

Recolecta métricas del sistema (CPU, RAM, disco, temperatura, uptime)
usando psutil y las publica como evento `system_heartbeat` en el bus
MQTT cada `heartbeat_interval_s` segundos.

Responsabilidades:
  - Leer métricas con psutil (sin efectos secundarios en tests).
  - Construir el payload canónico de heartbeat.
  - Publicar vía EventBus (inyectado, nunca instanciado internamente).
  - Detectar umbrales de alerta y loguear advertencias.
  - Exponerse como clase `TelemetryService` con métodos
    `collect()`, `publish_heartbeat()` y `run_loop()`.

Dependencias externas: psutil, services/common/event_bus, event_models.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Protocol

import psutil

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol — permite mockear el EventBus en tests sin importarlo
# ---------------------------------------------------------------------------

class EventBusProtocol(Protocol):
    def publish(self, topic: str, payload: dict) -> None:
        ...


# ---------------------------------------------------------------------------
# Protocol — permite mockear ParkingPolicies en tests
# ---------------------------------------------------------------------------

class PoliciesProtocol(Protocol):
    heartbeat_interval_s: float
    cpu_alert_threshold: float
    memory_alert_threshold: float
    disk_alert_threshold: float


# ---------------------------------------------------------------------------
# Métricas del sistema
# ---------------------------------------------------------------------------

class SystemMetrics:
    """
    Wrapper fino sobre psutil.
    Aislado en su propia clase para poder ser mockeado completamente
    en tests sin parchear psutil directamente.
    """

    def cpu_percent(self, interval: float = 0.5) -> float:
        """Uso de CPU en porcentaje (0.0–100.0)."""
        return psutil.cpu_percent(interval=interval)

    def memory_percent(self) -> float:
        """Uso de RAM en porcentaje."""
        return psutil.virtual_memory().percent

    def disk_percent(self, path: str = "/") -> float:
        """Uso de disco en porcentaje para la partición indicada."""
        return psutil.disk_usage(path).percent

    def uptime_seconds(self) -> float:
        """Segundos transcurridos desde el arranque del sistema."""
        return time.time() - psutil.boot_time()

    def temperature_celsius(self) -> Optional[float]:
        """
        Temperatura de la CPU en °C.
        Retorna None si el hardware no expone sensores (ej. VM, CI).
        En BeaglePlay la lectura llega por /sys/class/thermal/thermal_zone0/temp
        que psutil mapea bajo la clave 'cpu_thermal' o similar.
        """
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return None
            # Preferencia de claves comunes en ARM / BeaglePlay
            for key in ("cpu_thermal", "cpu-thermal", "coretemp", "k10temp"):
                entries = temps.get(key)
                if entries:
                    return round(entries[0].current, 1)
            # Fallback: primer sensor disponible
            first_key = next(iter(temps))
            return round(temps[first_key][0].current, 1)
        except (AttributeError, StopIteration, OSError):
            return None


# ---------------------------------------------------------------------------
# Servicio de telemetría
# ---------------------------------------------------------------------------

class TelemetryService:
    """
    Publica periódicamente un evento `system_heartbeat` con métricas
    del sistema operativo de la BeaglePlay.

    Uso típico (en main.py):
        svc = TelemetryService(bus=event_bus, policies=policies)
        svc.run_loop()          # bloqueante; úsalo en un hilo o proceso

    En tests:
        svc = TelemetryService(bus=mock_bus, policies=mock_policies,
                               metrics=mock_metrics)
        payload = svc.collect()
        svc.publish_heartbeat()
    """

    SERVICE_NAME = "connectivity-service"

    def __init__(
        self,
        bus: EventBusProtocol,
        policies: PoliciesProtocol,
        metrics: Optional[SystemMetrics] = None,
        disk_path: str = "/",
    ) -> None:
        """
        Args:
            bus:       Instancia de EventBus (o mock) ya conectada.
            policies:  ParkingPolicies (o mock) con umbrales y configuración.
            metrics:   SystemMetrics (o mock). Si es None se crea una instancia real.
            disk_path: Partición a monitorear. Default '/' (raíz).
        """
        self._bus = bus
        self._policies = policies
        self._metrics = metrics or SystemMetrics()
        self._disk_path = disk_path
        self._running = False

        logger.info(
            "[%s] TelemetryService inicializado — intervalo=%ss",
            self.SERVICE_NAME,
            self._policies.heartbeat_interval_s,
        )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def collect(self) -> dict:
        """
        Lee las métricas del sistema y retorna el payload del heartbeat.

        Returns:
            dict con las claves definidas en el contrato del proyecto:
            cpu_percent, memory_percent, disk_percent, uptime_seconds,
            service_name, temperature_c.
        """
        cpu = self._metrics.cpu_percent()
        mem = self._metrics.memory_percent()
        disk = self._metrics.disk_percent(self._disk_path)
        uptime = self._metrics.uptime_seconds()
        temp = self._metrics.temperature_celsius()

        self._check_thresholds(cpu, mem, disk)

        return {
            "cpu_percent":    round(cpu, 1),
            "memory_percent": round(mem, 1),
            "disk_percent":   round(disk, 1),
            "uptime_seconds": round(uptime, 1),
            "service_name":   self.SERVICE_NAME,
            "temperature_c":  temp,          # puede ser None
        }

    def publish_heartbeat(self) -> None:
        """
        Recolecta métricas y publica un mensaje canónico `system_heartbeat`
        en el tópico `parking/events/system_heartbeat`.

        El mensaje sigue la estructura definida en event_models.py:
        {
            "trace_id":   <uuid4>,
            "timestamp":  <ISO8601-UTC>,
            "event_type": "system_heartbeat",
            "source":     "connectivity-service",
            "payload":    { ...métricas... }
        }
        """
        try:
            payload = self.collect()
            message = {
                "trace_id":   str(uuid.uuid4()),
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "event_type": "system_heartbeat",
                "source":     self.SERVICE_NAME,
                "payload":    payload,
            }
            self._bus.publish("parking/events/system_heartbeat", message)
            logger.debug(
                "[%s] Heartbeat publicado — cpu=%.1f%% mem=%.1f%% disk=%.1f%%",
                self.SERVICE_NAME,
                payload["cpu_percent"],
                payload["memory_percent"],
                payload["disk_percent"],
            )
        except Exception as exc:  # noqa: BLE001
            # No propagamos: un heartbeat perdido no debe derribar el servicio.
            logger.error(
                "[%s] Error publicando heartbeat: %s",
                self.SERVICE_NAME, exc, exc_info=True,
            )

    def run_loop(self, *, stop_event=None) -> None:
        """
        Bucle principal bloqueante. Publica un heartbeat cada
        `heartbeat_interval_s` segundos.

        Args:
            stop_event: threading.Event opcional. El bucle termina cuando
                        el evento se activa. Si es None, corre indefinidamente.

        Uso en hilo:
            import threading
            stop = threading.Event()
            t = threading.Thread(target=svc.run_loop, kwargs={"stop_event": stop})
            t.start()
            ...
            stop.set()   # detiene el bucle limpiamente
        """
        self._running = True
        logger.info("[%s] run_loop iniciado", self.SERVICE_NAME)

        while self._running:
            if stop_event and stop_event.is_set():
                break

            self.publish_heartbeat()

            # Espera interruptible: duerme en tramos de 1 s para reaccionar
            # rápido a stop_event sin bloquear el hilo entero.
            interval = self._policies.heartbeat_interval_s
            elapsed = 0.0
            while elapsed < interval:
                if stop_event and stop_event.is_set():
                    self._running = False
                    break
                time.sleep(min(1.0, interval - elapsed))
                elapsed += 1.0

        self._running = False
        logger.info("[%s] run_loop detenido", self.SERVICE_NAME)

    def stop(self) -> None:
        """Señaliza el bucle para que se detenga en la próxima iteración."""
        self._running = False

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _check_thresholds(
        self, cpu: float, mem: float, disk: float
    ) -> None:
        """Emite advertencias de log si alguna métrica supera su umbral."""
        if cpu >= self._policies.cpu_alert_threshold:
            logger.warning(
                "[%s] ALERTA CPU: %.1f%% >= umbral %.1f%%",
                self.SERVICE_NAME, cpu, self._policies.cpu_alert_threshold,
            )
        if mem >= self._policies.memory_alert_threshold:
            logger.warning(
                "[%s] ALERTA MEMORIA: %.1f%% >= umbral %.1f%%",
                self.SERVICE_NAME, mem, self._policies.memory_alert_threshold,
            )
        if disk >= self._policies.disk_alert_threshold:
            logger.warning(
                "[%s] ALERTA DISCO: %.1f%% >= umbral %.1f%%",
                self.SERVICE_NAME, disk, self._policies.disk_alert_threshold,
            )