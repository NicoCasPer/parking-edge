# README — Integrante B: Módulos, Diseño e Instrucciones (parking-edge)

Este documento describe con detalle la parte del proyecto a cargo del **Integrante B**. Está pensado como README para subir al repositorio y facilitar la integración con la parte del Integrante A.

Contenido rápido:
- **Alcance**: lista de módulos y responsabilidades.
- **Estructura del repositorio**: archivos y rutas principales (mis entregables).
- **Arquitectura y protocolos**: MQTT, formato de mensajes, tópicos, RPMsg, DB.
- **Configuración y políticas**: `config/policies.yaml` y umbrales.
- **Cómo correr pruebas**: comandos para tests unitarios (mocked).
- **Guía de integración**: cómo Integrante A debe invocar o conectarse con mis piezas.

**Nota**: los paths referenciados son relativos a la raíz del workspace.

**Alcance (Integrante B)**
- Implementación del bus de eventos y modelos: [services/common/event_bus.py](services/common/event_bus.py), [services/common/event_models.py](services/common/event_models.py).
- Lógica de validación de placas y pipeline de OCR (parte de `vision-service` que coopera con Integrante A): [services/vision-service/app/ocr_pipeline.py](services/vision-service/app/ocr_pipeline.py), [services/vision-service/app/plate_validator.py](services/vision-service/app/plate_validator.py).
- Controlador hardware y cliente RPMsg (comunicación Linux ↔ M4): [services/hardware-controller/app/rpmsg_client.py](services/hardware-controller/app/rpmsg_client.py), [services/hardware-controller/app/command_dispatcher.py](services/hardware-controller/app/command_dispatcher.py), [services/hardware-controller/app/main.py](services/hardware-controller/app/main.py).
- Orquestador de acceso: políticas y flujos de decisión que usan la BD por inyección y publican resultados en MQTT: [services/access-orchestrator/app/policies.py](services/access-orchestrator/app/policies.py), [services/access-orchestrator/app/orchestrator.py](services/access-orchestrator/app/orchestrator.py), [services/access-orchestrator/app/main.py](services/access-orchestrator/app/main.py).
- Servicio de conectividad / telemetría: recolección de métricas y envío de `system_heartbeat`: [services/connectivity-service/app/telemetry.py](services/connectivity-service/app/telemetry.py), [services/connectivity-service/app/main.py](services/connectivity-service/app/main.py).
- Semillas de BD para simulación: [db/seeds/simulation_data.sql](db/seeds/simulation_data.sql).
- Fichero de políticas central: [config/policies.yaml](config/policies.yaml).
- Systemd units para mis servicios: `systemd/*-service` (ya incluidas en repo).

Estructura de archivos (resumen de mis entregables)
- [config/policies.yaml](config/policies.yaml): parámetros globales (umbral OCR, heartbeat interval, umbrales de alerta, política de fallo).
- [db/seeds/simulation_data.sql](db/seeds/simulation_data.sql): dataset de prueba (whitelist, pagos, placas inválidas).
- [services/common/event_bus.py](services/common/event_bus.py): clase `EventBus` para publicar/subscribe MQTT con JSON canónico y reconexión.
- [services/common/event_models.py](services/common/event_models.py): `Topics`, estructuras, y helpers (fábrica de mensajes: `make_event()` etc.).
- [services/vision-service/app/ocr_pipeline.py](services/vision-service/app/ocr_pipeline.py): punto de entrada `process(text, confidence, evidence_id, frame_quality, retries, lane_id, trace_id)` usado por Integrante A.
- [services/vision-service/app/plate_validator.py](services/vision-service/app/plate_validator.py): validación de formato, umbral de confianza y resultado (aceptado/rechazado) según `config/policies.yaml`.
- [services/hardware-controller/app/rpmsg_client.py](services/hardware-controller/app/rpmsg_client.py): cliente RPMsg (API simple para enviar `OPEN:trace-id\\n` y parsear respuesta).
- [services/hardware-controller/app/command_dispatcher.py](services/hardware-controller/app/command_dispatcher.py): traductor de eventos/commands hacia mensajes RPMsg.
- [services/access-orchestrator/app/policies.py](services/access-orchestrator/app/policies.py): carga y representación de `policies.yaml` en objetos usados por el orquestador.
- [services/access-orchestrator/app/orchestrator.py](services/access-orchestrator/app/orchestrator.py): lógica que decide `access_granted` / `access_denied` y registra eventos en BD (por inyección de `DatabaseProtocol`).
- [services/connectivity-service/app/telemetry.py](services/connectivity-service/app/telemetry.py): recolección `psutil` y publicación heartbeat.

Decisiones arquitectónicas y contratos relevantes

- Mensajes MQTT: formato canónico JSON (todos los eventos deben construirse con `make_event(trace_id, event_type, source, payload)` desde `event_models`). Campos obligatorios: `trace_id`, `timestamp` (ISO8601 UTC), `event_type`, `source`, `payload`.
- Tópicos (constantes en `event_models.Topics`):
  - `parking/events/plate_read`
  - `parking/events/plate_unreadable`
  - `parking/events/access_granted`
  - `parking/events/access_denied`
  - `parking/events/assisted_mode`
  - `parking/events/system_heartbeat`
  - `parking/commands/barrier` (usado para enviar comandos desde orquestador al `hardware-controller`)
  - `parking/commands/override`

- OCR & validación:
  - Confianza en escala 0.0–1.0; umbral por defecto `ocr_confidence_threshold: 0.85` (proviene de `config/policies.yaml`).
  - Regex de placa colombiana: `^[A-Z]{3}-[0-9]{3}$` (implementado en `plate_validator.py`).
  - Integrante A ejecuta Tesseract y llama directamente a `ocr_pipeline.process(...)` dentro del mismo servicio; no hay paso adicional por MQTT entre la captura y la validación.

- RPMsg (Linux ↔ M4) — contrato textual:
  - Envío desde Linux hacia M4 para abrir barrera: `OPEN:trace-id\\n` (nota: `trace-id` debe coincidir con el evento que lo originó).
  - Respuestas M4 válidas:
    - `OPEN:OK:trace-id\\n`
    - `OPEN:FAULT:trace-id\\n`
    - `HARDWARE_FAULT:OBSTACLE\\n` (notificación asíncrona de fallo hardware)
  - `rpmsg_client.py` normaliza la comunicación y lanza excepciones específicas en condiciones de error.

- Base de datos: SQLite. El orquestador acepta un objeto que implemente `DatabaseProtocol` (interfaz mínima: `get_whitelist(plate)`, `check_payment(plate)`, `insert_event(event)`) para facilitar mocks en tests.

- Política de fallo global: `FAIL_CLOSED` — si BD, RPMsg o bus de eventos fallan, el orquestador deniega acceso y publica `access_denied` con razón (fail-closed).

Configuración y `policies.yaml`
- Ruta: [config/policies.yaml](config/policies.yaml)
- Contiene (ejemplo resumido):
  - `ocr_confidence_threshold: 0.85`
  - `telemetry`:
    - `heartbeat_interval_s`: 30
    - `cpu_alert_threshold`: 80.0
    - `memory_alert_threshold`: 85.0
    - `disk_alert_threshold`: 90.0
  - `fail_policy`: `FAIL_CLOSED`

Logging y observabilidad
- Uso exclusivo de `logging` estructurado con formato `%(asctime)s %(levelname)s [%(name)s] %(message)s`.
- Todos los servicios exponen logs a stdout/stderr (systemd redirige a journald).
- Los eventos principales se publican también en MQTT para el dashboard.

Tests
- Tests unitarios no dependen de hardware ni broker real (se usan `unittest.mock`).
- Ubicación de tests por componente: `services/*/tests/`.
- Comando para ejecutar todos los tests del repositorio (desde la raíz):

```bash
python -m pytest -q
```

- Ejecutar solo los tests de un servicio, por ejemplo `vision-service`:

```bash
python -m pytest -q services/vision-service/tests
```

- Recomendación: usar `pytest -k <pattern>` para filtrar, y `-q` para salida limpia.

Cómo ejecutar y desarrollar localmente (dev)
- Requisitos principales: Python 3.10+ y dependencias listadas en el `requirements.txt` del repo raíz (si no existe, instalar según imports: `paho-mqtt`, `psutil`, `pytest`).
- Broker MQTT en localhost (para pruebas en integración) — Mosquitto es la opción prevista; en unit tests el `EventBus` se mockea.
- Para probar el flujo completo sin hardware M4:
  1. Levantar Mosquitto local.
  2. Iniciar `hardware-controller` en modo mock (o mockear `rpmsg_client` para devolver `OPEN:OK:trace-id`).
  3. Ejecutar `access-orchestrator` y simular eventos de placa publicando a `parking/events/plate_read` (puede hacerse con `mosquitto_pub` o un script pequeño).

Variables de entorno recomendadas (dev)
- `BROKER_URL` (default `mqtt://localhost:1883`)
- `DATABASE_URL` (default `sqlite:///./parking.db`)
- `LOG_LEVEL` (default `INFO`)

Guía de integración con Integrante A (puntos de contacto)
- OCR pipeline: Integrante A debe llamar directamente a `process()` exportada por [services/vision-service/app/ocr_pipeline.py](services/vision-service/app/ocr_pipeline.py). Firma esperada:

  `process(text: str, confidence: float, evidence_id: str, frame_quality: float, retries: int, lane_id: str, trace_id: str) -> None`

  - `process` realizará validaciones (formato y confianza) con `plate_validator` y publicará `parking/events/plate_read` o `parking/events/plate_unreadable` según corresponda.

- MQTT topics: Integrante A y otros componentes deben usar las constantes en [services/common/event_models.py](services/common/event_models.py) para evitar typos.

- RPMsg: cuando el `orchestrator` decide `access_granted`, el flujo es:
  1. `orchestrator` publica/llama a `hardware-controller` vía `EventBus` o directamente invoca `command_dispatcher` que usa `rpmsg_client`.
  2. `rpmsg_client` envía `OPEN:trace-id\\n` y espera respuesta.
  3. Según la respuesta se publica `parking/events/access_granted` o `parking/events/access_denied`.

Pautas de codificación y pruebas
- Manejar excepciones explícitas en toda operación de I/O (BD, MQTT, RPMsg).
- Inyección de dependencias: el orquestador no debe importar el módulo de BD concretamente; use una interfaz/mocks en tests.
- No usar `print`. Usar únicamente `logging` a nivel estructurado.
- Tests: no depender de servicios externos; usar `unittest.mock` para broker y RPMsg.

Checklist para subir e integrar mi parte
- [ ] Actualizar `README` (este archivo).
- [ ] Ejecutar `python -m pytest` localmente y arreglar posibles fallos unitarios.
- [ ] Proveer instrucciones en la PR sobre cómo arrancar el entorno de integración (Mosquitto, BD, mocks opcionales).

Contacto / notas finales
- Si Integrante A necesita cambiar la firma de `ocr_pipeline.process` o el esquema de mensajes MQTT, coordinar cambios y actualizar `event_models` y `plate_validator`.
- Para dudas sobre RPMsg o fallos hardware, revisar `services/hardware-controller/app/rpmsg_client.py` y los logs systemd de `hardware-controller.service`.


----
Archivo generado: README de la parte del Integrante B. Si quieres, puedo también:
- ejecutar los tests unitarios locales y reportar fallos;
- añadir un `requirements.txt` mínimo;
- crear una nota `INTEGRATION.md` con pasos concretos para que Integrante A y B hagan la integración end-to-end.

