"""
event_bus.py — Cliente MQTT unificado para todos los servicios del parqueadero.

Responsabilidades:
  - Gestionar la conexión y reconexión automática al broker Mosquitto.
  - Publicar mensajes con estructura canónica (trace_id, timestamp, source).
  - Distribuir mensajes entrantes a los callbacks registrados (soporta wildcards).
  - Proporcionar una API consistente a todos los servicios sin duplicar lógica MQTT.

Configuración (variables de entorno):
  MQTT_BROKER_HOST  — Dirección del broker (default: localhost)
  MQTT_BROKER_PORT  — Puerto TCP del broker (default: 1883)
  MQTT_KEEPALIVE    — Segundos entre pings de keepalive (default: 60)

Uso básico:
    bus = EventBus("vision-service")
    bus.connect()
    bus.subscribe(Topics.PLATE_READ, my_handler)
    bus.publish(Topics.PLATE_READ, {"plate": "ABC-123", "confidence": 91.5})
    ...
    bus.disconnect()
"""

import json
import logging
import os
import time
import uuid
from threading import Lock
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt

from services.common.event_models import Topics, build_event

logger = logging.getLogger(__name__)


class EventBus:
    """
    Cliente MQTT unificado. Un servicio instancia un EventBus, lo conecta
    y usa publish/subscribe. La gestión de hilos y reconexiones es interna.
    """

    def __init__(
        self,
        service_name: str,
        broker_host:  Optional[str] = None,
        broker_port:  Optional[int] = None,
        keepalive:    int = 60,
    ) -> None:
        """
        Args:
            service_name: Identificador del servicio (ej. "vision-service").
                          Se usa en el client_id de MQTT y en el campo "source"
                          de cada mensaje publicado.
            broker_host:  Dirección del broker. Prioridad: argumento > MQTT_BROKER_HOST > "localhost".
            broker_port:  Puerto del broker. Prioridad: argumento > MQTT_BROKER_PORT > 1883.
            keepalive:    Intervalo de keepalive en segundos.
        """
        self.service_name = service_name
        self.broker_host  = broker_host or os.getenv("MQTT_BROKER_HOST", "localhost")
        self.broker_port  = broker_port or int(os.getenv("MQTT_BROKER_PORT", "1883"))
        self.keepalive    = keepalive

        # Paho client — ID único por instancia para evitar colisiones en el broker
        client_id = f"parking-{service_name}-{uuid.uuid4().hex[:8]}"
        self._client = mqtt.Client(client_id=client_id, clean_session=True)

        self._subscriptions: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self._lock      = Lock()
        self._connected = False

        # Asignar callbacks de paho
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        logger.info(
            "EventBus initialized | service=%s broker=%s:%s",
            self.service_name, self.broker_host, self.broker_port,
        )

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------

    def connect(self, max_retries: int = 5, retry_base_delay: float = 2.0) -> None:
        """
        Establece conexión al broker con backoff exponencial.

        Args:
            max_retries:       Número máximo de intentos antes de lanzar excepción.
            retry_base_delay:  Segundos base para el backoff (se duplica por intento).

        Raises:
            ConnectionError: Si todos los intentos fallan.
        """
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "Connecting to MQTT broker (attempt %d/%d) | %s:%s",
                    attempt, max_retries, self.broker_host, self.broker_port,
                )
                self._client.connect(self.broker_host, self.broker_port, self.keepalive)
                self._client.loop_start()

                # Esperar confirmación de conexión (on_connect seteará _connected)
                self._wait_for_connection(timeout=5.0)

                if self._connected:
                    logger.info("MQTT connection established | service=%s", self.service_name)
                    return

            except OSError as exc:
                delay = retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Connection attempt %d failed: %s | retrying in %.1fs",
                    attempt, exc, delay,
                )
                if attempt < max_retries:
                    time.sleep(delay)

        raise ConnectionError(
            f"[{self.service_name}] Could not connect to MQTT broker at "
            f"{self.broker_host}:{self.broker_port} after {max_retries} attempts."
        )

    def publish(
        self,
        topic:      str,
        payload:    Dict[str, Any],
        event_type: Optional[str] = None,
        trace_id:   Optional[str] = None,
        qos:        int = 1,
    ) -> None:
        """
        Publica un evento en el bus con el envelope canónico.

        El mensaje resultante en MQTT siempre tiene la forma:
            {
                "trace_id":   "<uuid4>",
                "timestamp":  "<ISO8601-UTC>",
                "event_type": "<tipo>",
                "source":     "<service_name>",
                "payload":    { ... }
            }

        Args:
            topic:      Tópico MQTT de destino (usar constantes de Topics).
            payload:    Diccionario con los datos del evento.
            event_type: Si es None, se infiere del último segmento del tópico.
            trace_id:   UUID de trazabilidad. Se genera automáticamente si es None.
            qos:        Nivel de calidad de servicio MQTT (0, 1 o 2). Default 1.

        Raises:
            RuntimeError: Si el bus no está conectado o si paho retorna error.
            TypeError:    Si el payload no es serializable a JSON.
        """
        if not self._connected:
            raise RuntimeError(
                f"[{self.service_name}] Cannot publish to '{topic}': not connected."
            )

        inferred_type = event_type or topic.split("/")[-1]
        envelope = build_event(
            event_type=inferred_type,
            payload=payload,
            source=self.service_name,
            trace_id=trace_id,
        )

        try:
            raw_message = json.dumps(envelope, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            logger.error(
                "Payload serialization failed | topic=%s error=%s", topic, exc
            )
            raise

        result = self._client.publish(topic, raw_message, qos=qos)

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"[{self.service_name}] Publish to '{topic}' failed "
                f"with MQTT error code {result.rc}."
            )

        logger.debug(
            "Event published | topic=%s event_type=%s trace_id=%s",
            topic, inferred_type, envelope["trace_id"],
        )

    def subscribe(
        self,
        topic:    str,
        callback: Callable[[Dict[str, Any]], None],
        qos:      int = 1,
    ) -> None:
        """
        Suscribe un callback a un tópico MQTT.

        El callback recibe el envelope completo ya deserializado como dict:
            callback({"trace_id": ..., "event_type": ..., "payload": {...}})

        Soporta wildcards de MQTT:
            + → un nivel    (ej. "parking/events/+")
            # → multinivel  (ej. "parking/#")

        Si se llama antes de connect(), la suscripción queda registrada
        y se envía al broker cuando se establezca la conexión.

        Args:
            topic:    Tópico MQTT (con o sin wildcards).
            callback: Función que recibe el mensaje como dict.
            qos:      Nivel de calidad de servicio MQTT.
        """
        with self._lock:
            self._subscriptions[topic] = callback

        if self._connected:
            self._client.subscribe(topic, qos=qos)
            logger.info("Subscribed | topic=%s service=%s", topic, self.service_name)
        else:
            logger.warning(
                "Subscription queued (bus not connected yet) | topic=%s", topic
            )

    def disconnect(self) -> None:
        """Cierre limpio: detiene el loop y desconecta del broker."""
        logger.info("Disconnecting EventBus | service=%s", self.service_name)
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -----------------------------------------------------------------------
    # Callbacks internos de paho-mqtt
    # -----------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc: int) -> None:
        if rc == 0:
            self._connected = True
            logger.info(
                "MQTT on_connect OK | service=%s flags=%s", self.service_name, flags
            )
            # Re-suscribir todos los tópicos registrados (crítico tras reconexión)
            with self._lock:
                for topic in self._subscriptions:
                    client.subscribe(topic, qos=1)
                    logger.debug("Re-subscribed after connect | topic=%s", topic)
        else:
            logger.error(
                "MQTT connection refused | rc=%d reason=%s",
                rc, mqtt.connack_string(rc),
            )

    def _on_disconnect(self, client, userdata, rc: int) -> None:
        self._connected = False
        if rc != 0:
            # rc != 0 significa desconexión inesperada; paho intentará reconectar
            # automáticamente si loop_start() está activo.
            logger.warning(
                "Unexpected MQTT disconnection | rc=%d service=%s",
                rc, self.service_name,
            )
        else:
            logger.info("MQTT disconnected cleanly | service=%s", self.service_name)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic

        try:
            envelope: Dict[str, Any] = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error(
                "Failed to decode MQTT message | topic=%s error=%s", topic, exc
            )
            return

        callback = self._find_callback(topic)
        if callback is None:
            logger.debug("No callback registered for topic | topic=%s", topic)
            return

        try:
            callback(envelope)
        except Exception as exc:
            logger.exception(
                "Unhandled exception in message callback | topic=%s trace_id=%s error=%s",
                topic, envelope.get("trace_id", "N/A"), exc,
            )

    # -----------------------------------------------------------------------
    # Utilidades internas
    # -----------------------------------------------------------------------

    def _wait_for_connection(self, timeout: float) -> None:
        """Bloquea hasta que _connected sea True o se agote el timeout."""
        elapsed = 0.0
        step    = 0.05
        while not self._connected and elapsed < timeout:
            time.sleep(step)
            elapsed += step

    def _find_callback(
        self, topic: str
    ) -> Optional[Callable[[Dict[str, Any]], None]]:
        """
        Retorna el callback para un tópico dado.
        Prioridad: match exacto > primer wildcard que coincida.
        """
        with self._lock:
            if topic in self._subscriptions:
                return self._subscriptions[topic]

            for pattern, callback in self._subscriptions.items():
                if mqtt.topic_matches_sub(pattern, topic):
                    return callback

        return None
