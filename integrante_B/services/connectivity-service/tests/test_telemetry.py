"""
parking-edge/services/connectivity-service/tests/test_telemetry.py

Tests para TelemetryService y SystemMetrics.
NO requiere psutil real, broker MQTT ni hardware.
Todo mockeado con unittest.mock.

Grupos:
  1. collect()          — payload correcto, redondeo, temperatura None
  2. publish_heartbeat()— estructura canónica, tópico, delegación a bus
  3. Umbrales de alerta — warnings de log cuando se supera cada umbral
  4. Errores en collect — excepciones de psutil no propagan fuera de publish
  5. run_loop()         — se detiene con stop_event, llama publish N veces
  6. SystemMetrics      — wrappers de psutil retornan tipos correctos
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from telemetry import TelemetryService, SystemMetrics  # noqa: E402


# ---------------------------------------------------------------------------
# Factories / helpers
# ---------------------------------------------------------------------------

def _make_policies(
    interval: float = 30.0,
    cpu_threshold: float = 80.0,
    mem_threshold: float = 85.0,
    disk_threshold: float = 90.0,
) -> MagicMock:
    p = MagicMock()
    p.heartbeat_interval_s = interval
    p.cpu_alert_threshold = cpu_threshold
    p.memory_alert_threshold = mem_threshold
    p.disk_alert_threshold = disk_threshold
    return p


def _make_metrics(
    cpu: float = 45.2,
    mem: float = 61.0,
    disk: float = 38.5,
    uptime: float = 3600.0,
    temp: float | None = 52.1,
) -> MagicMock:
    m = MagicMock(spec=SystemMetrics)
    m.cpu_percent.return_value = cpu
    m.memory_percent.return_value = mem
    m.disk_percent.return_value = disk
    m.uptime_seconds.return_value = uptime
    m.temperature_celsius.return_value = temp
    return m


def _make_service(
    policies=None,
    metrics=None,
    bus=None,
    disk_path: str = "/",
) -> tuple[TelemetryService, MagicMock, MagicMock, MagicMock]:
    """Retorna (svc, bus, policies, metrics) listos para usar."""
    bus = bus or MagicMock()
    policies = policies or _make_policies()
    metrics = metrics or _make_metrics()
    svc = TelemetryService(
        bus=bus,
        policies=policies,
        metrics=metrics,
        disk_path=disk_path,
    )
    return svc, bus, policies, metrics


# ---------------------------------------------------------------------------
# Grupo 1 — collect()
# ---------------------------------------------------------------------------

class TestCollect(unittest.TestCase):

    def setUp(self):
        self.svc, _, _, self.metrics = _make_service()

    def test_returns_dict(self):
        result = self.svc.collect()
        self.assertIsInstance(result, dict)

    def test_all_required_keys_present(self):
        required = {
            "cpu_percent", "memory_percent", "disk_percent",
            "uptime_seconds", "service_name", "temperature_c",
        }
        self.assertEqual(required, set(self.svc.collect().keys()))

    def test_cpu_value_matches_metrics(self):
        self.metrics.cpu_percent.return_value = 55.678
        result = self.svc.collect()
        self.assertAlmostEqual(result["cpu_percent"], 55.7, places=1)

    def test_memory_value_matches_metrics(self):
        self.metrics.memory_percent.return_value = 72.345
        result = self.svc.collect()
        self.assertAlmostEqual(result["memory_percent"], 72.3, places=1)

    def test_disk_value_matches_metrics(self):
        self.metrics.disk_percent.return_value = 88.999
        result = self.svc.collect()
        self.assertAlmostEqual(result["disk_percent"], 89.0, places=1)

    def test_uptime_value_matches_metrics(self):
        self.metrics.uptime_seconds.return_value = 7200.0
        result = self.svc.collect()
        self.assertAlmostEqual(result["uptime_seconds"], 7200.0, places=1)

    def test_service_name_is_connectivity_service(self):
        self.assertEqual(self.svc.collect()["service_name"], "connectivity-service")

    def test_temperature_present_when_available(self):
        self.metrics.temperature_celsius.return_value = 52.1
        result = self.svc.collect()
        self.assertAlmostEqual(result["temperature_c"], 52.1, places=1)

    def test_temperature_none_when_not_available(self):
        self.metrics.temperature_celsius.return_value = None
        result = self.svc.collect()
        self.assertIsNone(result["temperature_c"])

    def test_disk_path_forwarded_to_metrics(self):
        svc, _, _, metrics = _make_service(disk_path="/data")
        svc.collect()
        metrics.disk_percent.assert_called_once_with("/data")

    def test_values_are_rounded_to_one_decimal(self):
        self.metrics.cpu_percent.return_value = 33.333333
        result = self.svc.collect()
        # Debe tener como máximo 1 decimal
        cpu_str = str(result["cpu_percent"])
        decimals = len(cpu_str.split(".")[-1]) if "." in cpu_str else 0
        self.assertLessEqual(decimals, 1)


# ---------------------------------------------------------------------------
# Grupo 2 — publish_heartbeat()
# ---------------------------------------------------------------------------

class TestPublishHeartbeat(unittest.TestCase):

    def setUp(self):
        self.svc, self.bus, _, _ = _make_service()

    def test_bus_publish_called_once(self):
        self.svc.publish_heartbeat()
        self.bus.publish.assert_called_once()

    def test_correct_topic(self):
        self.svc.publish_heartbeat()
        topic = self.bus.publish.call_args[0][0]
        self.assertEqual(topic, "parking/events/system_heartbeat")

    def test_message_has_trace_id(self):
        self.svc.publish_heartbeat()
        msg = self.bus.publish.call_args[0][1]
        self.assertIn("trace_id", msg)
        self.assertIsInstance(msg["trace_id"], str)
        self.assertTrue(len(msg["trace_id"]) > 0)

    def test_message_trace_id_is_unique_per_call(self):
        self.svc.publish_heartbeat()
        id1 = self.bus.publish.call_args[0][1]["trace_id"]
        self.svc.publish_heartbeat()
        id2 = self.bus.publish.call_args[0][1]["trace_id"]
        self.assertNotEqual(id1, id2)

    def test_message_has_iso8601_timestamp(self):
        from datetime import datetime
        self.svc.publish_heartbeat()
        msg = self.bus.publish.call_args[0][1]
        self.assertIn("timestamp", msg)
        # Debe ser parseable como ISO 8601
        dt = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
        self.assertIsNotNone(dt)

    def test_message_event_type(self):
        self.svc.publish_heartbeat()
        msg = self.bus.publish.call_args[0][1]
        self.assertEqual(msg["event_type"], "system_heartbeat")

    def test_message_source(self):
        self.svc.publish_heartbeat()
        msg = self.bus.publish.call_args[0][1]
        self.assertEqual(msg["source"], "connectivity-service")

    def test_message_payload_is_dict(self):
        self.svc.publish_heartbeat()
        msg = self.bus.publish.call_args[0][1]
        self.assertIsInstance(msg["payload"], dict)

    def test_message_payload_contains_cpu(self):
        self.svc.publish_heartbeat()
        payload = self.bus.publish.call_args[0][1]["payload"]
        self.assertIn("cpu_percent", payload)

    def test_canonical_keys_in_message(self):
        self.svc.publish_heartbeat()
        msg = self.bus.publish.call_args[0][1]
        for key in ("trace_id", "timestamp", "event_type", "source", "payload"):
            with self.subTest(key=key):
                self.assertIn(key, msg)


# ---------------------------------------------------------------------------
# Grupo 3 — Umbrales de alerta
# ---------------------------------------------------------------------------

class TestThresholdAlerts(unittest.TestCase):

    def _svc_with_metrics(self, cpu=0.0, mem=0.0, disk=0.0):
        policies = _make_policies(
            cpu_threshold=80.0,
            mem_threshold=85.0,
            disk_threshold=90.0,
        )
        metrics = _make_metrics(cpu=cpu, mem=mem, disk=disk)
        svc, _, _, _ = _make_service(policies=policies, metrics=metrics)
        return svc

    def test_no_warning_below_all_thresholds(self):
        svc = self._svc_with_metrics(cpu=70.0, mem=80.0, disk=85.0)
        with self.assertLogs("connectivity-service", level="WARNING") as cm:
            # Forzamos al menos un log para que assertLogs no falle
            import logging
            logging.getLogger("connectivity-service").warning("_dummy_")
            svc.collect()
        # Solo debe estar el dummy, no alertas reales
        real_alerts = [m for m in cm.output if "ALERTA" in m]
        self.assertEqual(len(real_alerts), 0)

    def test_cpu_alert_when_at_threshold(self):
        svc = self._svc_with_metrics(cpu=80.0)
        with self.assertLogs("connectivity-service", level="WARNING") as cm:
            svc.collect()
        self.assertTrue(any("CPU" in m for m in cm.output))

    def test_cpu_alert_when_above_threshold(self):
        svc = self._svc_with_metrics(cpu=95.0)
        with self.assertLogs("connectivity-service", level="WARNING") as cm:
            svc.collect()
        self.assertTrue(any("CPU" in m for m in cm.output))

    def test_memory_alert_when_at_threshold(self):
        svc = self._svc_with_metrics(mem=85.0)
        with self.assertLogs("connectivity-service", level="WARNING") as cm:
            svc.collect()
        self.assertTrue(any("MEMORIA" in m for m in cm.output))

    def test_disk_alert_when_at_threshold(self):
        svc = self._svc_with_metrics(disk=90.0)
        with self.assertLogs("connectivity-service", level="WARNING") as cm:
            svc.collect()
        self.assertTrue(any("DISCO" in m for m in cm.output))

    def test_multiple_alerts_fired_simultaneously(self):
        svc = self._svc_with_metrics(cpu=90.0, mem=90.0, disk=95.0)
        with self.assertLogs("connectivity-service", level="WARNING") as cm:
            svc.collect()
        alerts = [m for m in cm.output if "ALERTA" in m]
        self.assertEqual(len(alerts), 3)


# ---------------------------------------------------------------------------
# Grupo 4 — Errores en collect / publish
# ---------------------------------------------------------------------------

class TestErrorHandling(unittest.TestCase):

    def test_bus_publish_exception_does_not_propagate(self):
        """Un error de MQTT no debe derribar el servicio."""
        bus = MagicMock()
        bus.publish.side_effect = ConnectionError("broker caído")
        svc, _, _, _ = _make_service(bus=bus)
        try:
            svc.publish_heartbeat()   # No debe lanzar
        except Exception as exc:
            self.fail(f"publish_heartbeat propagó excepción: {exc}")

    def test_metrics_exception_does_not_propagate(self):
        """Un fallo de psutil no debe derribar el servicio."""
        metrics = _make_metrics()
        metrics.cpu_percent.side_effect = OSError("sensor no disponible")
        svc, _, _, _ = _make_service(metrics=metrics)
        try:
            svc.publish_heartbeat()
        except Exception as exc:
            self.fail(f"publish_heartbeat propagó excepción de psutil: {exc}")

    def test_bus_called_zero_times_on_collect_error(self):
        """Si collect() falla, el bus no debe recibir ningún mensaje."""
        bus = MagicMock()
        metrics = _make_metrics()
        metrics.cpu_percent.side_effect = RuntimeError("fallo grave")
        svc, _, _, _ = _make_service(bus=bus, metrics=metrics)
        svc.publish_heartbeat()
        bus.publish.assert_not_called()

    def test_publish_heartbeat_logs_error_on_bus_failure(self):
        bus = MagicMock()
        bus.publish.side_effect = Exception("fallo MQTT")
        svc, _, _, _ = _make_service(bus=bus)
        with self.assertLogs("connectivity-service", level="ERROR") as cm:
            svc.publish_heartbeat()
        self.assertTrue(any("ERROR" in m or "error" in m.lower() for m in cm.output))


# ---------------------------------------------------------------------------
# Grupo 5 — run_loop()
# ---------------------------------------------------------------------------

class TestRunLoop(unittest.TestCase):

    def test_run_loop_stops_on_event(self):
        """El bucle debe terminar en ≤ 3 s cuando se activa stop_event."""
        svc, _, _, _ = _make_service(
            policies=_make_policies(interval=0.05)  # 50 ms para acelerar el test
        )
        stop = threading.Event()
        t = threading.Thread(target=svc.run_loop, kwargs={"stop_event": stop})
        t.start()
        time.sleep(0.2)
        stop.set()
        t.join(timeout=3.0)
        self.assertFalse(t.is_alive(), "run_loop no se detuvo tras stop_event")

    def test_publish_called_at_least_once(self):
        """Debe publicar al menos un heartbeat antes de detenerse."""
        bus = MagicMock()
        svc, _, _, _ = _make_service(
            bus=bus,
            policies=_make_policies(interval=0.05),
        )
        stop = threading.Event()
        t = threading.Thread(target=svc.run_loop, kwargs={"stop_event": stop})
        t.start()
        time.sleep(0.3)
        stop.set()
        t.join(timeout=3.0)
        self.assertGreaterEqual(bus.publish.call_count, 1)

    def test_publish_called_multiple_times(self):
        """Con intervalo corto se deben emitir varios heartbeats."""
        bus = MagicMock()
        svc, _, _, _ = _make_service(
            bus=bus,
            policies=_make_policies(interval=0.05),
        )
        stop = threading.Event()
        t = threading.Thread(target=svc.run_loop, kwargs={"stop_event": stop})
        t.start()
        time.sleep(0.5)
        stop.set()
        t.join(timeout=3.0)
        self.assertGreater(bus.publish.call_count, 1)

    def test_stop_method_terminates_loop(self):
        """svc.stop() debe terminar el bucle sin stop_event externo."""
        svc, _, _, _ = _make_service(
            policies=_make_policies(interval=0.05),
        )
        t = threading.Thread(target=svc.run_loop)
        t.start()
        time.sleep(0.2)
        svc.stop()
        t.join(timeout=3.0)
        self.assertFalse(t.is_alive(), "run_loop no se detuvo tras svc.stop()")


# ---------------------------------------------------------------------------
# Grupo 6 — SystemMetrics (unit, sin psutil real)
# ---------------------------------------------------------------------------

class TestSystemMetrics(unittest.TestCase):
    """
    Verifica que los wrappers de psutil retornan los tipos correctos
    y manejan correctamente la ausencia de sensores de temperatura.
    """

    def test_cpu_percent_returns_float(self):
        with patch("psutil.cpu_percent", return_value=42.5):
            sm = SystemMetrics()
            result = sm.cpu_percent(interval=0.0)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 42.5)

    def test_memory_percent_returns_float(self):
        mock_mem = MagicMock()
        mock_mem.percent = 55.0
        with patch("psutil.virtual_memory", return_value=mock_mem):
            sm = SystemMetrics()
            result = sm.memory_percent()
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 55.0)

    def test_disk_percent_returns_float(self):
        mock_disk = MagicMock()
        mock_disk.percent = 70.0
        with patch("psutil.disk_usage", return_value=mock_disk):
            sm = SystemMetrics()
            result = sm.disk_percent("/")
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 70.0)

    def test_uptime_seconds_positive(self):
        with patch("psutil.boot_time", return_value=time.time() - 3600):
            sm = SystemMetrics()
            result = sm.uptime_seconds()
        self.assertGreater(result, 0)

    def test_temperature_returns_float_when_available(self):
        mock_entry = MagicMock()
        mock_entry.current = 52.1
        with patch("psutil.sensors_temperatures",
                   return_value={"cpu_thermal": [mock_entry]}):
            sm = SystemMetrics()
            result = sm.temperature_celsius()
        self.assertAlmostEqual(result, 52.1, places=1)

    def test_temperature_returns_none_when_no_sensors(self):
        with patch("psutil.sensors_temperatures", return_value={}):
            sm = SystemMetrics()
            result = sm.temperature_celsius()
        self.assertIsNone(result)

    def test_temperature_returns_none_when_attribute_error(self):
        """En sistemas sin sensors_temperatures (Windows/CI) debe retornar None."""
        with patch("psutil.sensors_temperatures", side_effect=AttributeError):
            sm = SystemMetrics()
            result = sm.temperature_celsius()
        self.assertIsNone(result)

    def test_temperature_fallback_to_first_available_sensor(self):
        """Si no hay clave preferida, usa el primer sensor disponible."""
        mock_entry = MagicMock()
        mock_entry.current = 48.0
        with patch("psutil.sensors_temperatures",
                   return_value={"some_other_sensor": [mock_entry]}):
            sm = SystemMetrics()
            result = sm.temperature_celsius()
        self.assertAlmostEqual(result, 48.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)