# Guía de Desarrollo para Integrante A – Sistema de Parqueadero Inteligente

## Introducción
Este documento es la hoja de ruta completa para el **Integrante A** del proyecto educativo de parqueadero inteligente sobre BeaglePlay. Está organizado por fases y contiene:
- Los módulos que te corresponden.
- Los archivos que debes crear o modificar.
- Los parámetros de configuración relevantes.
- Las librerías necesarias.
- Las pruebas que debes realizar para validar cada componente.

Todo el desarrollo se apoya en el **Blueprint Técnico v2.0** del proyecto. Se recomienda trabajar cada sección con asistencia de IA (por ejemplo, pidiéndole que genere el esqueleto de una función o que explique un concepto), siempre teniendo el blueprint como referencia. Al inicio de cada módulo se incluye un **prompt sugerido** para facilitar la interacción con la IA.

---

## Fase 0: Entorno común y primer encendido

### Objetivo
Dejar lista la BeaglePlay, las herramientas de compilación y verificar que podemos cargar firmware en el Cortex-M4.

### Tareas específicas del Integrante A
- Instalar el toolchain para el M4 (`ti-cgt-armllvm` o `gcc-arm-none-eabi`).
- Instalar el PRU C Compiler (si se usa más adelante).
- Configurar la consola serie (USB-TTL) y verificar el arranque.
- Crear un firmware mínimo que haga parpadear un LED del M4.
- Cargar el firmware usando `load_m4_fw.sh` y verificar que el parpadeo funciona.

### Archivos y carpetas involucradas

| Ruta | Descripción |
|------|-------------|
| `firmware/m4/` | Directorio base para el firmware del M4 |
| `firmware/m4/CMakeLists.txt` | Build system (por ahora un simple Makefile) |
| `firmware/m4/src/main.c` | Punto de entrada, enciende LED en bucle |
| `scripts/load_m4_fw.sh` | Script para cargar el firmware (ya existente en el repo) |

### Librerías / Herramientas
- Compilador ARM para Cortex-M4: `gcc-arm-none-eabi` (recomendado por simplicidad) o `ti-cgt-armllvm`.
- `make` o `cmake`.
- `screen` / `minicom` para la consola serie.
- Driver de RPMsg (viene en el kernel de la BeaglePlay, no necesitas instalarlo).

### Parámetros de configuración
Ninguno en esta fase. Solo rutas de compilación.

### Pruebas
- El LED conectado a un GPIO del M4 parpadea cada 500 ms.
- En la consola serie de Linux aparecen los mensajes de arranque del M4 (si el firmware los imprime).

### Cómo usar IA en esta fase
Pide al asistente:
> "Genera un programa en C para un Cortex-M4F que configure un GPIO como salida y haga parpadear un LED cada 500 ms. Incluye comentarios y la inicialización del sistema básico."

Luego solo debes ajustar el pin según tu conexión y compilar.

---

## Fase 1: Control de Hardware – Firmware M4 y Comunicación RPMsg

### Objetivo
El M4 leerá un sensor de presencia (simulado con un botón), enviará eventos al A53 por RPMsg y podrá recibir comandos para abrir/cerrar una barrera (servomotor/LED). También implementará un watchdog que cierra la barrera si no recibe heartbeat del A53.

### Estructura de archivos

```
firmware/m4/
├── CMakeLists.txt
├── src/
│   ├── main.c                # Inicialización y bucle principal
│   ├── sensor_driver.c       # Lectura del GPIO de presencia (con debounce)
│   ├── sensor_driver.h
│   ├── rpmsg_interface.c     # Inicialización de RPMsg, envío/recepción de mensajes
│   ├── rpmsg_interface.h
│   ├── watchdog.c            # Temporizador de heartbeat, control de seguridad
│   └── watchdog.h
```

Además, en el sistema Linux:

```
systemd/
└── m4-firmware.service       # (ya existente, verificar que use el script correcto)
```

### Librerías necesarias
- FreeRTOS (kernel de tiempo real para el M4). Puedes usar la que viene en el SDK de TI o una descarga independiente.
- Drivers de TI para GPIO, RPMsg.
- `ti-rpmsg-library` (ya incluida en el sistema de la BeaglePlay para el lado A53, pero en el M4 necesitas la biblioteca de RPMsg del SDK).

### Parámetros de configuración (en `firmware/config.h` o macros)
- `SENSOR_GPIO_PIN` : número de pin donde se conecta el sensor/botón.
- `DEBOUNCE_MS` : tiempo de debounce (por defecto 50 ms).
- `HEARTBEAT_TIMEOUT_MS` : tiempo máximo sin recibir heartbeat del A53 antes de activar el watchdog (por defecto 5000 ms).
- `RPMsg_ENDPOINT` : identificador del endpoint (por ejemplo, 14).

### Diseño de mensajes RPMsg
Define dos tipos de mensaje simples (puedes usar cadenas de texto cortas o un struct binario):
- **M4 → A53** : `"PRESENCE_DETECTED"`
- **A53 → M4** : `"OPEN"`, `"CLOSE"`, `"HEARTBEAT"`

### Tareas concretas del Integrante A
1. Crear la estructura de archivos vacía.
2. Implementar `main.c`:
   - Inicializar FreeRTOS, GPIO, RPMsg.
   - Crear una tarea que lea el sensor y envíe `"PRESENCE_DETECTED"` cuando se active.
   - Crear una tarea que espere mensajes de RPMsg: si recibe `"OPEN"` activa el servo/LED de barrera; si recibe `"CLOSE"` lo desactiva.
3. Implementar `sensor_driver.c`:
   - Leer el pin GPIO cada 10 ms, aplicar debounce, devolver estado estable.
4. Implementar `rpmsg_interface.c`:
   - Inicializar el canal RPMsg.
   - Función `send_message(const char* msg)`.
   - Callback para recepción que encola los comandos.
5. Implementar `watchdog.c`:
   - Un timer de FreeRTOS que se reinicia cada vez que llega un mensaje `"HEARTBEAT"`.
   - Si el timer expira, poner la barrera en posición cerrada y detener cualquier movimiento.
6. Actualizar el script `load_m4_fw.sh` si es necesario (normalmente usa remoteproc para cargar el firmware compilado).
7. Escribir pruebas unitarias del firmware (opcional, usando un emulador o testing on-target):
   - Enviar manualmente mensajes de prueba desde Linux (usando `echo` sobre el dispositivo RPMsg) y verificar que el servo se mueve.

### Pruebas de integración (con ayuda del Integrante B)
- Presionar el botón → el M4 imprime por serie "PRESENCE_DETECTED" y el Integrante B ve el evento en el bus de Linux.
- Desde Linux, el Integrante B envía un comando "OPEN" → el servo se activa.
- Matar el servicio en Linux que envía el heartbeat → después de 5 segundos el M4 pone la barrera en posición segura.

### Cómo usar IA
Pídele al asistente (por partes):
> "Escribe una tarea de FreeRTOS en C que lea un pin GPIO cada 10 ms, aplique un debounce de 50 ms y, al detectar flanco de subida, envíe el mensaje 'PRESENCE_DETECTED' usando una función rpmsg_send(). Incluye manejo de errores."

> "Implementa una función de inicialización de RPMsg para un Cortex-M4F que cree un endpoint de comunicación y registre un callback de recepción."

Luego integras las piezas.

---

## Fase 2: Visión Artificial – Captura y Preprocesamiento

### Objetivo
Cuando el sistema reciba un trigger (proveniente de la detección de presencia), tomar una foto con la cámara USB, seleccionar el mejor frame si hay varios, calcular su nitidez y recortar una región de interés donde se espera la placa.

### Archivos que debes crear/modificar

```
services/vision-service/app/
├── capture.py          # Lógica de captura de cámara (V4L2 con OpenCV)
├── frame_selector.py   # Selección del frame más nítido (varianza Laplaciana)
├── quality.py          # Cálculo de métricas de calidad (Laplaciana, etc.)
└── test_vision.py      # Pruebas unitarias
```

### Librerías necesarias
- OpenCV (`cv2`): captura de video, procesamiento.
- NumPy (`numpy`): cálculos de varianza.

### Parámetros de configuración (en `policies.yaml` o variables)
- `camera_id` : índice de la cámara (por defecto 0).
- `capture_width`, `capture_height` : resolución (640x480 recomendada para empezar).
- `num_capture_frames` : cuántos frames capturar por evento (ej. 3).
- `sharpness_threshold` : umbral mínimo de varianza Laplaciana para considerar un frame aceptable.
- `roi_x, roi_y, roi_w, roi_h` : coordenadas de la región de interés para recortar (fijas al inicio; más adelante se podrá hacer detección automática).

### Tareas del Integrante A
1. **`capture.py`**:
   - Función `capture_frames(num_frames)` que devuelve una lista de imágenes (arrays NumPy).
   - Si la cámara no está disponible, lanza una excepción controlada.
2. **`frame_selector.py`**:
   - Función `select_best_frame(frames)` que calcula la varianza Laplaciana de cada uno y devuelve el índice y el valor máximo.
   - La métrica estándar: convertir a grises, aplicar Laplaciano, calcular varianza.
3. **`quality.py`**:
   - Implementa `calculate_laplacian_variance(image)`.
   - Puedes añadir otras métricas como contraste o desenfoque más adelante.
4. **Recorte de ROI**:
   - Función `extract_roi(image, x, y, w, h)` en el mismo `capture.py` o en un módulo aparte.
   - Si la ROI se sale de la imagen, lanzar advertencia.
5. **Pruebas unitarias (`test_vision.py`)**:
   - Usar imágenes de prueba guardadas (una nítida, una borrosa, una oscura) y verificar que la selección elige la correcta.
   - Probar el recorte con coordenadas fijas.
   - Simular fallo de cámara (mock) y verificar el manejo de errores.

### Integración con el sistema
El trigger de captura lo recibirás mediante un mensaje en el bus interno (que el Integrante B pondrá en marcha). Por ahora, puedes probar tu código directamente ejecutando `capture.py` y viendo las imágenes generadas.

### Cómo usar IA
Sugiere al asistente:
> "Escribe una función en Python usando OpenCV que capture 3 frames de la cámara 0 y los devuelva como lista de arrays. Maneja el caso de que la cámara no esté disponible lanzando una excepción RuntimeError con un mensaje descriptivo."

> "Implementa una función que reciba una lista de imágenes en formato BGR y devuelva el índice de la más nítida, usando la varianza del Laplaciano como métrica."

Puedes pedir que genere también las pruebas unitarias con pytest.

---

## Fase 3: Base de Datos y Almacenamiento

### Objetivo
Crear la base de datos SQLite local con las tablas necesarias para registrar eventos, whitelist, etc. Además, guardar las imágenes de evidencia con nombres basados en el `trace_id`.

### Archivos a crear

```
db/
├── schema.sql                  # Esquema SQL inicial
├── migrations/
│   └── 001_initial.sql         # Primera migración (opcional, si usan migraciones)
services/common/
└── database.py                 # Módulo Python para conexión y consultas

systemd/
└── database.service            # Servicio oneshot que ejecuta schema.sql al arrancar
```

También añadirás en el código de visión (o en un módulo de utilidad) la lógica para guardar evidencias.

### Librerías
- `sqlite3` (viene en la biblioteca estándar de Python).

### Parámetros de configuración
- `DB_PATH` : ruta del archivo SQLite (por ejemplo, `/opt/parking-edge/data/parking.db`).
- `EVIDENCE_PATH` : directorio donde se guardan las imágenes (ej. `/opt/parking-edge/data/evidence`).

### Tareas del Integrante A

1. **`schema.sql`**:
   - Tabla `events`:
     ```sql
     CREATE TABLE events (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         trace_id TEXT NOT NULL UNIQUE,
         timestamp TEXT NOT NULL,   -- ISO8601
         event_type TEXT NOT NULL,
         payload TEXT,              -- JSON
         created_at TEXT DEFAULT (datetime('now'))
     );
     ```
   - Tabla `whitelist`:
     ```sql
     CREATE TABLE whitelist (
         plate TEXT PRIMARY KEY,
         valid_until TEXT,
         description TEXT
     );
     ```
   - Índices adicionales si se consideran necesarios.

2. **`database.py`**:
   - Función `get_connection()` que devuelva una conexión a la BD.
   - Función `init_db()` que ejecute `schema.sql` si la BD no existe.
   - Funciones CRUD mínimas:
     - `insert_event(trace_id, event_type, payload)`
     - `get_whitelist(plate)`
   - Usar siempre consultas parametrizadas para evitar inyección SQL.

3. **`database.service`**:
   - Unidad systemd oneshot que ejecute `init_db()` al inicio (puede ser un script Python corto que llame a `database.init_db()`).

4. **Almacenamiento de evidencias** (modificar o agregar en vision-service):
   - Función `save_evidence(image, trace_id, evidence_dir)`:
     - Guardar la imagen ROI con el nombre `{trace_id}.jpg`.
     - Registrar el evento en la BD con tipo `EVIDENCE_STORED` o simplemente confiar en que el orquestador lo hará.
     - Asegurar que el directorio exista y tenga permisos de escritura.

### Pruebas
- Ejecutar `init_db()` y verificar que se crean las tablas.
- Insertar un evento y comprobar que se puede recuperar por `trace_id`.
- Consultar la whitelist con una placa existente y verificar que devuelve los datos.
- Simular guardar una imagen de prueba y comprobar que el archivo existe con el nombre correcto.

### Cómo usar IA
Pide al asistente:
> "Genera un módulo Python database.py que utilice sqlite3 para conectarse a una base de datos SQLite. Incluye una función init_db() que ejecute un archivo schema.sql, y funciones insert_event(trace_id, event_type, payload) y get_whitelist(plate). Usa consultas parametrizadas."

> "Escribe un archivo de servicio systemd tipo oneshot que ejecute un script de inicialización de base de datos antes de que arranquen los demás servicios."

---

## Fase 4: Mock de Pagos e Integración Resiliente

### Objetivo
Crear un servidor simulado que haga las veces de proveedor de pagos externo, e implementar el módulo `payment-integration` con circuit breaker, cola offline y garantía de idempotencia.

### Archivos del Integrante A

Servidor mock (puede ser un proyecto aparte):

```
mock_payment_server/
├── app.py                  # Aplicación Flask simple
└── requirements.txt
```

Servicio de integración de pagos:

```
services/payment-integration/app/
├── payment_client.py       # Cliente HTTP hacia el proveedor
├── circuit_breaker.py      # Lógica de circuit breaker
├── local_store.py          # Cola de transacciones offline (archivo JSON)
└── tests/
    ├── test_payment_client.py
    ├── test_circuit_breaker.py
    └── test_local_store.py
```

### Librerías necesarias
- Flask (para el mock).
- `requests` (para el cliente HTTP).
- `tenacity` (opcional, para reintentos con backoff) o implementación manual.

### Parámetros de configuración
- `PAYMENT_API_URL` : URL del mock (ej. `http://localhost:5001/validate`).
- `PAYMENT_TIMEOUT_MS` : timeout de la petición (por defecto 2000 ms).
- `MAX_RETRIES` : intentos máximos (por defecto 2).
- `BACKOFF_BASE_MS` : tiempo base para backoff incremental.
- `CIRCUIT_FAIL_THRESHOLD` : número de fallos consecutivos para abrir el circuito (por defecto 5).
- `CIRCUIT_RESET_TIMEOUT_S` : tiempo hasta intentar cerrar el circuito de nuevo (por defecto 30 s).
- `OFFLINE_QUEUE_PATH` : ruta del archivo JSON para la cola offline.

### Tareas

1. **Mock payment server (`app.py`)**:
   - Endpoint `POST /validate` que reciba un JSON con `plate` y `trace_id`.
   - Responda `{"status": "approved"}` si la placa empieza por `"A"` (por ejemplo) o `{"status": "denied"}` en otro caso.
   - Simular fallos aleatorios o bajo demanda (agregar un endpoint `/toggle_failure`).

2. **`payment_client.py`**:
   - Función `validate_payment(plate, trace_id)` que hace POST al mock.
   - Manejar timeout y errores de red, lanzando excepciones específicas.

3. **`circuit_breaker.py`**:
   - Implementar una clase `CircuitBreaker` con estados `CLOSED`, `OPEN`, `HALF_OPEN`.
   - Contabilizar fallos consecutivos y cambiar de estado cuando se supera el umbral.
   - Programar un temporizador para pasar de `OPEN` a `HALF_OPEN` después del tiempo de reset.

4. **`local_store.py`**:
   - Funciones para encolar transacciones offline (guardar en archivo JSON) y para procesarlas cuando se recupere la conexión.
   - Asegurar idempotencia: antes de procesar una transacción, verificar que su `trace_id` no esté ya en la BD de eventos (esto último en coordinación con el Integrante B).

5. **Pruebas**:
   - Con el mock en ejecución, probar un pago aprobado y uno denegado.
   - Forzar la caída del mock (detenerlo) y verificar que después de 5 fallos el circuit breaker se abre y no se intenta más.
   - Simular varias transacciones offline y luego levantar el mock para ver la reconciliación.

### Integración con el orquestador (Integrante B)
El orquestador llamará a `payment_client.validate_payment()` y según el resultado decidirá `OPEN`/`DENY`. Debes documentar bien la interfaz (excepciones que lanza, formato de respuesta) para que el Integrante B pueda consumirla.

### Cómo usar IA
> "Crea un servidor Flask con un endpoint POST '/validate' que reciba JSON con 'plate' y 'trace_id', y devuelva {'status': 'approved'} si plate empieza con 'A', si no {'status': 'denied'}."

> "Implementa una clase CircuitBreaker en Python con estados CLOSED, OPEN, HALF_OPEN. Usa un contador de fallos y un timer para pasar a HALF_OPEN después de un tiempo configurable."

> "Escribe un módulo local_store.py que guarde transacciones de pago en un archivo JSON y las recupere como cola. Cada transacción debe tener plate, trace_id y timestamp."

---

## Fase 5: Integración y Pruebas (trabajo conjunto)

En esta fase solo se realizan pruebas completas del sistema y documentación, que harán en equipo. Tu responsabilidad como Integrante A es asegurarte de que todos tus módulos funcionan correctamente de manera aislada y de proporcionar al Integrante B las interfaces claras para la integración.
