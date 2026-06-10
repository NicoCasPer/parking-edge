"""
test_event_bus.py — Pruebas unitarias del EventBus.

Se ejecutan SIN broker real: paho-mqtt se mockea completamente.
Cubren publicación, suscripción, reconexión y manejo de errores.

Ejecutar:
    python -m pytest services/common/test_event_bus.py -v
"""

import json
import unittest
from unittest.mock import MagicMock, patch, call
from services.common.event_bus import EventBus
from services.common.event_models import Topics


class TestEventBusPublish(unittest.TestCase):

    def _make_connected_bus(self) -> EventBus:
        """Crea un EventBus con paho mockeado y _connected=True."""
        with patch("services.common.event_bus.mqtt.Client"):
            bus = EventBus("test-service", broker_host="localhost", broker_port=1883)
            bus._connected = True
            bus._client.publish = MagicMock(
                return_value=MagicMock(rc=0)  # MQTT_ERR_SUCCESS
            )
            return bus

    def test_publish_sends_canonical_envelope(self):
        """El mensaje publicado debe incluir trace_id, timestamp, event_type, source y payload."""
        bus = self._make_connected_bus()

        bus.publish(Topics.PLATE_READ, {"plate": "ABC-123", "confidence": 91.5})

        bus._client.publish.assert_called_once()
        topic_arg, raw_msg_arg = bus._client.publish.call_args[0][:2]

        self.assertEqual(topic_arg, Topics.PLATE_READ)
        envelope = json.loads(raw_msg_arg)

        self.assertIn("trace_id", envelope)
        self.assertIn("timestamp", envelope)
        self.assertEqual(envelope["event_type"], "plate_read")  # último segmento del tópico
        self.assertEqual(envelope["source"], "test-service")
        self.assertEqual(envelope["payload"]["plate"], "ABC-123")
        self.assertAlmostEqual(envelope["payload"]["confidence"], 91.5)

    def test_publish_uses_provided_trace_id(self):
        """Si se proporciona trace_id, debe usarse tal cual en el envelope."""
        bus = self._make_connected_bus()
        fixed_id = "aaaabbbb-0000-0000-0000-111122223333"

        bus.publish(Topics.ACCESS_GRANTED, {"plate": "XYZ-789"}, trace_id=fixed_id)

        _, raw_msg = bus._client.publish.call_args[0][:2]
        envelope = json.loads(raw_msg)
        self.assertEqual(envelope["trace_id"], fixed_id)

    def test_publish_raises_when_not_connected(self):
        """Publicar sin conexión debe lanzar RuntimeError, no silenciarse."""
        with patch("services.common.event_bus.mqtt.Client"):
            bus = EventBus("test-service")
            bus._connected = False

        with self.assertRaises(RuntimeError):
            bus.publish(Topics.PLATE_READ, {"plate": "ABC-123", "confidence": 80.0})

    def test_publish_raises_on_non_serializable_payload(self):
        """Payloads no serializables deben lanzar TypeError."""
        bus = self._make_connected_bus()

        with self.assertRaises(TypeError):
            bus.publish(Topics.PLATE_READ, {"object": object()})


class TestEventBusSubscribe(unittest.TestCase):

    def _make_bus(self) -> EventBus:
        with patch("services.common.event_bus.mqtt.Client"):
            bus = EventBus("test-service")
            bus._connected = True
            bus._client.subscribe = MagicMock()
            return bus

    def test_subscribe_registers_callback(self):
        """El callback debe quedar en el dict de suscripciones."""
        bus = self._make_bus()
        handler = MagicMock()

        bus.subscribe(Topics.PLATE_READ, handler)

        self.assertIn(Topics.PLATE_READ, bus._subscriptions)
        self.assertIs(bus._subscriptions[Topics.PLATE_READ], handler)

    def test_subscribe_sends_to_broker_when_connected(self):
        """Si ya hay conexión, la suscripción debe enviarse al broker inmediatamente."""
        bus = self._make_bus()

        bus.subscribe(Topics.ACCESS_DENIED, MagicMock())

        bus._client.subscribe.assert_called_once_with(Topics.ACCESS_DENIED, qos=1)

    def test_on_message_dispatches_to_callback(self):
        """_on_message debe deserializar el payload y llamar al callback correcto."""
        bus = self._make_bus()
        received = []
        bus.subscribe(Topics.PLATE_READ, lambda envelope: received.append(envelope))

        envelope = {
            "trace_id":   "abc-123",
            "timestamp":  "2024-01-01T00:00:00+00:00",
            "event_type": "plate_read",
            "source":     "vision-service",
            "payload":    {"plate": "DEF-456", "confidence": 88.0},
        }
        mock_msg = MagicMock()
        mock_msg.topic   = Topics.PLATE_READ
        mock_msg.payload = json.dumps(envelope).encode("utf-8")

        bus._on_message(None, None, mock_msg)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["payload"]["plate"], "DEF-456")

    def test_on_message_handles_malformed_json(self):
        """Un mensaje malformado no debe propagar excepción ni llamar callbacks."""
        bus = self._make_bus()
        handler = MagicMock()
        bus.subscribe(Topics.PLATE_READ, handler)

        mock_msg = MagicMock()
        mock_msg.topic   = Topics.PLATE_READ
        mock_msg.payload = b"esto no es json {{{{"

        # No debe lanzar excepción
        try:
            bus._on_message(None, None, mock_msg)
        except Exception as exc:
            self.fail(f"_on_message raised unexpectedly: {exc}")

        handler.assert_not_called()

    def test_wildcard_subscription_matches_subtopics(self):
        """Una suscripción con wildcard '+' debe recibir mensajes de subtópicos concretos."""
        bus = self._make_bus()
        received = []
        bus.subscribe("parking/events/+", lambda e: received.append(e))

        envelope = {
            "trace_id": "x", "timestamp": "t",
            "event_type": "access_granted", "source": "orchestrator",
            "payload": {"plate": "GHI-789"},
        }
        mock_msg = MagicMock()
        mock_msg.topic   = Topics.ACCESS_GRANTED  # "parking/events/access_granted"
        mock_msg.payload = json.dumps(envelope).encode("utf-8")

        bus._on_message(None, None, mock_msg)

        self.assertEqual(len(received), 1)


class TestEventBusConnection(unittest.TestCase):

    def test_on_connect_sets_connected_flag(self):
        """_on_connect con rc=0 debe poner _connected = True."""
        with patch("services.common.event_bus.mqtt.Client"):
            bus = EventBus("test-service")
            bus._connected = False
            bus._client.subscribe = MagicMock()

        bus._on_connect(bus._client, None, {}, rc=0)
        self.assertTrue(bus._connected)

    def test_on_connect_resubscribes_all_topics(self):
        """Al reconectar, todos los tópicos registrados deben enviarse al broker."""
        with patch("services.common.event_bus.mqtt.Client"):
            bus = EventBus("test-service")
            bus._subscriptions = {
                Topics.PLATE_READ:    MagicMock(),
                Topics.PLATE_UNREADABLE: MagicMock(),
            }
            mock_client = MagicMock()

        bus._on_connect(mock_client, None, {}, rc=0)

        subscribed_topics = [c[0][0] for c in mock_client.subscribe.call_args_list]
        self.assertIn(Topics.PLATE_READ, subscribed_topics)
        self.assertIn(Topics.PLATE_UNREADABLE, subscribed_topics)

    def test_on_disconnect_clears_connected_flag(self):
        """_on_disconnect debe poner _connected = False."""
        with patch("services.common.event_bus.mqtt.Client"):
            bus = EventBus("test-service")
            bus._connected = True

        bus._on_disconnect(None, None, rc=0)
        self.assertFalse(bus._connected)


if __name__ == "__main__":
    unittest.main()
