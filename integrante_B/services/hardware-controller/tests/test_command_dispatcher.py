"""
test_command_dispatcher.py — Pruebas unitarias del CommandDispatcher.

EventBus y RPMsgClient se mockean completamente.
Se prueba cada rama de traducción MQTT → M4 y M4 → MQTT.

Ejecutar:
    cd parking-edge
    python -m pytest services/hardware-controller/tests/test_command_dispatcher.py -v
"""

import unittest
from unittest.mock import MagicMock, call, patch

from services.hardware_controller.app.command_dispatcher import CommandDispatcher
from services.common.event_models import Topics


def _make_dispatcher():
    """Crea un CommandDispatcher con bus y rpmsg completamente mockeados."""
    bus   = MagicMock()
    rpmsg = MagicMock()
    dispatcher = CommandDispatcher(event_bus=bus, rpmsg_client=rpmsg)
    return dispatcher, bus, rpmsg


def _envelope(event_type: str, payload: dict, trace_id: str = "test-trace") -> dict:
    """Helper para construir un envelope MQTT mínimo."""
    return {
        "trace_id":   trace_id,
        "event_type": event_type,
        "source":     "test",
        "payload":    payload,
    }


class TestDispatcherSubscriptions(unittest.TestCase):
    """Verifica que el dispatcher se suscribe a los tópicos correctos al iniciar."""

    def test_subscribes_to_access_granted(self):
        _, bus, _ = _make_dispatcher()
        subscribed = [c[0][0] for c in bus.subscribe.call_args_list]
        self.assertIn(Topics.ACCESS_GRANTED, subscribed)

    def test_subscribes_to_access_denied(self):
        _, bus, _ = _make_dispatcher()
        subscribed = [c[0][0] for c in bus.subscribe.call_args_list]
        self.assertIn(Topics.ACCESS_DENIED, subscribed)

    def test_subscribes_to_barrier_command(self):
        _, bus, _ = _make_dispatcher()
        subscribed = [c[0][0] for c in bus.subscribe.call_args_list]
        self.assertIn(Topics.BARRIER_COMMAND, subscribed)

    def test_registers_m4_callback(self):
        _, _, rpmsg = _make_dispatcher()
        rpmsg.set_message_callback.assert_called_once()


class TestAccessGrantedToM4(unittest.TestCase):
    """access_granted → OPEN debe enviarse al M4."""

    def test_sends_open_command(self):
        dispatcher, _, rpmsg = _make_dispatcher()
        envelope = _envelope("access_granted",
                             {"plate": "ABC-123", "reason": "whitelist"},
                             trace_id="trace-001")

        dispatcher._on_access_granted(envelope)

        rpmsg.send_command.assert_called_once_with("OPEN", "trace-001")

    def test_trace_id_forwarded_to_m4(self):
        dispatcher, _, rpmsg = _make_dispatcher()
        dispatcher._on_access_granted(
            _envelope("access_granted", {"plate": "XYZ-789"}, trace_id="my-uuid")
        )
        _, kwargs_trace = rpmsg.send_command.call_args[0]
        self.assertEqual(kwargs_trace, "my-uuid")


class TestAccessDeniedNoAction(unittest.TestCase):
    """access_denied → NO debe enviarse ningún comando al M4."""

    def test_no_rpmsg_command_sent(self):
        dispatcher, _, rpmsg = _make_dispatcher()
        dispatcher._on_access_denied(
            _envelope("access_denied", {"plate": "NOP-456", "reason": "unknown_plate"})
        )
        rpmsg.send_command.assert_not_called()


class TestBarrierCommandRouting(unittest.TestCase):
    """barrier_command con acción válida → comando correcto al M4."""

    def test_open_command_forwarded(self):
        dispatcher, _, rpmsg = _make_dispatcher()
        dispatcher._on_barrier_command(
            _envelope("barrier_command",
                      {"action": "OPEN", "source": "manual_override"},
                      trace_id="override-trace")
        )
        rpmsg.send_command.assert_called_once_with("OPEN", "override-trace")

    def test_close_command_forwarded(self):
        dispatcher, _, rpmsg = _make_dispatcher()
        dispatcher._on_barrier_command(
            _envelope("barrier_command", {"action": "CLOSE", "source": "orchestrator"})
        )
        rpmsg.send_command.assert_called_once_with("CLOSE", "test-trace")

    def test_stop_command_forwarded(self):
        dispatcher, _, rpmsg = _make_dispatcher()
        dispatcher._on_barrier_command(
            _envelope("barrier_command", {"action": "STOP", "source": "orchestrator"})
        )
        rpmsg.send_command.assert_called_once_with("STOP", "test-trace")

    def test_unknown_action_ignored(self):
        """Acciones desconocidas no deben enviarse al M4 ni publicar nada."""
        dispatcher, bus, rpmsg = _make_dispatcher()
        # Limpiar las llamadas del __init__ (subscribe)
        bus.publish.reset_mock()

        dispatcher._on_barrier_command(
            _envelope("barrier_command", {"action": "EXPLODE", "source": "test"})
        )
        rpmsg.send_command.assert_not_called()
        bus.publish.assert_not_called()

    def test_lowercase_action_normalized(self):
        """Las acciones en minúsculas deben normalizarse a mayúsculas."""
        dispatcher, _, rpmsg = _make_dispatcher()
        dispatcher._on_barrier_command(
            _envelope("barrier_command", {"action": "open", "source": "test"})
        )
        rpmsg.send_command.assert_called_once_with("OPEN", "test-trace")


class TestM4ResponseHandling(unittest.TestCase):
    """Respuestas del M4 → eventos MQTT correctos."""

    def test_open_ok_publishes_barrier_opened(self):
        dispatcher, bus, _ = _make_dispatcher()
        bus.publish.reset_mock()

        dispatcher._on_m4_response("OPEN:OK:trace-abc")

        bus.publish.assert_called_once()
        kwargs = bus.publish.call_args[1]
        self.assertEqual(kwargs["event_type"], "barrier_opened")
        self.assertEqual(kwargs["trace_id"],   "trace-abc")

    def test_close_ok_publishes_barrier_closed(self):
        dispatcher, bus, _ = _make_dispatcher()
        bus.publish.reset_mock()

        dispatcher._on_m4_response("CLOSE:OK:trace-xyz")

        kwargs = bus.publish.call_args[1]
        self.assertEqual(kwargs["event_type"], "barrier_closed")

    def test_open_fault_publishes_hardware_fault(self):
        dispatcher, bus, _ = _make_dispatcher()
        bus.publish.reset_mock()

        dispatcher._on_m4_response("OPEN:FAULT:trace-fail")

        kwargs = bus.publish.call_args[1]
        self.assertEqual(kwargs["event_type"], "hardware_fault")
        self.assertIn("OPEN_failed", kwargs["payload"]["reason"])

    def test_autonomous_hardware_fault(self):
        """El M4 puede reportar fallos autónomos sin trace_id."""
        dispatcher, bus, _ = _make_dispatcher()
        bus.publish.reset_mock()

        dispatcher._on_m4_response("HARDWARE_FAULT:OBSTACLE_DETECTED")

        kwargs = bus.publish.call_args[1]
        self.assertEqual(kwargs["event_type"], "hardware_fault")
        self.assertEqual(kwargs["payload"]["reason"], "OBSTACLE_DETECTED")

    def test_malformed_response_ignored(self):
        """Respuestas malformadas no deben publicar ni lanzar excepción."""
        dispatcher, bus, _ = _make_dispatcher()
        bus.publish.reset_mock()

        try:
            dispatcher._on_m4_response("GARBLED_DATA")
        except Exception as exc:
            self.fail(f"Malformed response raised unexpectedly: {exc}")

        bus.publish.assert_not_called()


class TestRPMsgWriteError(unittest.TestCase):
    """Si RPMsg falla al escribir, debe publicarse hardware_fault."""

    def test_rpmsg_error_triggers_hardware_fault(self):
        dispatcher, bus, rpmsg = _make_dispatcher()
        rpmsg.send_command.side_effect = OSError("write error")
        bus.publish.reset_mock()

        dispatcher._on_access_granted(
            _envelope("access_granted", {"plate": "ABC-123"}, trace_id="err-trace")
        )

        kwargs = bus.publish.call_args[1]
        self.assertEqual(kwargs["event_type"], "hardware_fault")
        self.assertIn("rpmsg_write_error", kwargs["payload"]["reason"])
        self.assertEqual(kwargs["trace_id"], "err-trace")


if __name__ == "__main__":
    unittest.main()
