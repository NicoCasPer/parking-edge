# parking-edge

Sistema de control de acceso para parqueadero inteligente.
**BeaglePlay (TI AM625)** actúa como gateway Linux (visión + lógica de negocio + dashboard) y un **ESP32 WROOM-32** maneja el tiempo real del hardware (sensor, barrera, watchdog), comunicados por **UART**.
Combina visión por computadora (TensorFlow Lite — YOLO11m INT8 cuantizado + Tesseract OCR, cámara USB) y microservicios Python comunicados por **MQTT**.

---

## Arquitectura

```
Sensor ultrasónico HC-SR04
      │
      ▼
┌──────────────────┐   UART    ┌─────────────────────┐
│  ESP32 WROOM-32  │◄────────►│ hardware-controller  │
│  (FreeRTOS:      │  115200   │ (Python / UART↔MQTT) │
│   watchdog,      │           └────────┬────────────┘
│   sensor HC-SR04,│                    │ MQTT
│   barrera servo) │                    ▼
└──────────────────┘            ┌──────────────┐
                                │ vision-service│  ◄── Cámara USB
                                │ TFLite + OCR │
                                └──────┬───────┘
                                       │ MQTT plate_read
                                       ▼
                             ┌──────────────────┐
                             │access-orchestrator│
                             │ whitelist/pago    │
                             └────────┬──────────┘
                                      │ MQTT access_granted/denied
                                      ▼
                             ┌──────────────────┐
                             │hardware-controller│ → UART → ESP32 → barrera servo
                             └──────────────────┘

    payment-integration  ─── HTTPS ──► Proveedor externo (+ circuit breaker)
    connectivity-service ─── telemetría del sistema
    web-dashboard        ─── Flask + WebSocket (panel de control)
```

**Flujo completo de un acceso:**
`Vehículo llega → ESP32 detecta presencia (HC-SR04) → UART → hardware-controller → MQTT → vision-service → YOLO+OCR (TFLite) → MQTT → access-orchestrator → whitelist/pago → MQTT → hardware-controller → UART → ESP32 abre barrera (servo)`

---

## Estructura del repositorio

```
parking-edge/
├── firmware/
│   ├── esp32/           # ACTIVO — PlatformIO: main, sensor HC-SR04, barrera servo PWM,
│   │   └── src/         #          watchdog, uart_protocol (FreeRTOS sobre ESP32)
│   └── m4/              # LEGADO histórico — FreeRTOS M4F/RPMsg, ya no se usa
├── services/
│   ├── common/          # event_bus, event_models, database (compartidos)
│   ├── hardware_controller/      # SerialClient (UART ↔ ESP32) ↔ MQTT
│   ├── vision_service/           # TensorFlow Lite Interpreter + cámara USB
│   ├── access_orchestrator/
│   ├── payment_integration/      # circuit breaker + store-and-forward
│   ├── connectivity_service/
│   └── mock_payment_server/      # servidor de pagos local para pruebas
├── web_dashboard/
│   ├── backend/         # Flask + Socket.IO + RBAC
│   ├── frontend/        # HTML/CSS/JS (eventos en tiempo real, whitelist, override)
│   └── nginx/           # Configuración proxy inverso
├── config/
│   ├── policies.yaml    # Umbrales y políticas de negocio
│   └── app.env.example  # Plantilla de variables de entorno
├── db/
│   ├── schema.sql
│   ├── migrations/001_initial.sql
│   └── seeds/simulation_data.sql
├── systemd/             # unit files listos para instalar
├── scripts/
│   ├── install.sh       # Instalación completa en BeaglePlay
│   └── healthcheck.sh   # Verifica todos los servicios
├── Modelo/              # best_plate_yolo11m_int8.tflite (no en git, ver abajo)
└── requirements.txt
```

---

## Requisitos

### En el BeaglePlay (destino)
- BeaglePlay con Debian 12 o Ubuntu 22.04 LTS ARM
- Python 3.10+
- Tesseract OCR: `sudo apt install tesseract-ocr`
- Mosquitto: `sudo apt install mosquitto`
- SQLite 3: `sudo apt install sqlite3`
- UART habilitado hacia el ESP32 (por defecto `/dev/ttyS2` a 115200 baudios)

### Hardware externo
- **ESP32 WROOM-32** conectado por UART al BeaglePlay (TX/RX cruzados, GND común)
- Sensor ultrasónico **HC-SR04** (ECHO con divisor de 5 V → 3.3 V)
- Servo para la barrera (PWM)
- Cámara **USB** (V4L2)

### En la PC de desarrollo
- Git
- Acceso SSH al BeaglePlay
- **PlatformIO** (para compilar y flashear el firmware del ESP32)

---

## Instalación en el BeaglePlay

### 1. Clonar el repositorio

```bash
git clone <url-del-repo> /opt/parking-edge
cd /opt/parking-edge
```

### 2. Agregar el modelo YOLO

El modelo no está en git por su tamaño. Copiarlo manualmente:

```bash
# Desde la PC de desarrollo:
scp Modelo/best_plate_yolo11m_int8.tflite beagle:/opt/parking-edge/Modelo/
```

### 3. Ejecutar el instalador

```bash
sudo bash scripts/install.sh
```

Esto instala dependencias del sistema, crea el usuario `parking`, configura el entorno virtual Python, inicializa la base de datos y registra los servicios en systemd.

### 4. Configurar variables de entorno

```bash
sudo nano /opt/parking-edge/config/app.env
```

Ajustar al menos:
```env
UART_DEVICE=/dev/ttyS2
UART_BAUDRATE=115200
PAYMENT_PROVIDER_URL=https://tu-proveedor.com
PAYMENT_API_KEY=tu-api-key-real
DASHBOARD_SECRET_KEY=una-clave-aleatoria-larga
DASHBOARD_ADMIN_PASSWORD=contraseña-segura
```

> **Nunca versionar `app.env`** — está en `.gitignore`.

### 5. Compilar y flashear el firmware del ESP32

El firmware del ESP32 se construye con PlatformIO (ver detalles en [firmware/esp32/README.md](firmware/esp32/README.md)):

```bash
cd /opt/parking-edge/firmware/esp32
pio run --target upload     # compila y flashea por USB
```

Pines (definidos en `firmware/esp32/include/config.h`):

| Función              | Pin ESP32 |
|----------------------|-----------|
| HC-SR04 TRIGGER      | GPIO5     |
| HC-SR04 ECHO         | GPIO18 (con divisor 5 V → 3.3 V) |
| Barrera (servo PWM)  | GPIO19    |
| UART2 TX → RX Beagle | GPIO17    |
| UART2 RX ← TX Beagle | GPIO16    |

### 6. Iniciar todos los servicios

```bash
sudo systemctl start mosquitto
sudo systemctl start database
sudo systemctl start hardware-controller vision-service access-orchestrator
sudo systemctl start payment-integration connectivity-service web-dashboard
```

O habilitar para que arranquen solos al iniciar el sistema:

```bash
sudo systemctl enable hardware-controller vision-service access-orchestrator \
    payment-integration connectivity-service web-dashboard
```

### 7. Verificar que todo esté corriendo

```bash
sudo bash /opt/parking-edge/scripts/healthcheck.sh
```

---

## Desarrollo local (sin hardware físico)

Para probar sin ESP32 ni cámara, activar el modo simulado:

```bash
export UART_SIMULATED=true
export MOCK_PAYMENT_SERVER=true
export CAMERA_INDEX=0        # cámara USB local
export DB_PATH=/tmp/parking.db
```

Iniciar servicios individualmente:

```bash
source venv/bin/activate
python -m services.hardware_controller.app.main &
python -m services.vision_service.app.main &
python -m services.access_orchestrator.app.main &
python -m services.payment_integration.app.main &
python -m services.mock_payment_server.app &
python -m web_dashboard.backend.app
```

Cargar datos de prueba en la base de datos:

```bash
sqlite3 /tmp/parking.db < db/migrations/001_initial.sql
sqlite3 /tmp/parking.db < db/seeds/simulation_data.sql
```

---

## Dashboard web

Acceder desde el navegador:

```
http://<ip-del-beagleplay>:8080
```

| Usuario   | Contraseña (default) | Permisos                            |
|-----------|----------------------|-------------------------------------|
| `admin`   | var. de entorno      | Todo: whitelist, override, logs     |
| `operator`| `operator`           | Override de barrera + lectura       |
| `viewer`  | `viewer`             | Solo lectura                        |

> Cambiar contraseñas antes de poner en producción.

**Funcionalidades del dashboard:**
- Eventos de acceso en tiempo real (WebSocket)
- **Vista en vivo de la cámara**: al detectarse un vehículo, el vision-service
  abre una sesión de cámara y transmite los frames (`latest.jpg` refrescado), más
  una galería con la evidencia de cada detección
- Estadísticas del día (accesos / denegados / whitelist)
- Tabla de pagos (placas que pagaron y su estado)
- Override manual de barrera (OPEN / STOP / CLOSE)
- Gestión de whitelist (agregar / actualizar placas)

> La evidencia de cámara se guarda en `EVIDENCE_PATH` (por defecto
> `/var/lib/parking/evidence`). **Debe estar fuera de `/tmp`**: los servicios usan
> `PrivateTmp=yes` en systemd, así que un `/tmp` no es compartido entre el
> vision-service y el dashboard.

---

## Servicios y puertos

| Servicio              | Puerto | Descripción                               |
|-----------------------|--------|-------------------------------------------|
| Mosquitto (MQTT)      | 1883   | Bus de eventos interno                    |
| web-dashboard         | 8080   | Panel de control HTTP                     |
| mock-payment-server   | 5050   | Solo en desarrollo (`MOCK_PAYMENT_SERVER=true`) |

---

## Tópicos MQTT

| Tópico                              | Productor              | Consumidor              |
|-------------------------------------|------------------------|-------------------------|
| `parking/events/presence_detected`  | hardware-controller    | vision-service          |
| `parking/events/plate_read`         | vision-service         | access-orchestrator, payment-integration |
| `parking/events/access_granted`     | access-orchestrator    | hardware-controller     |
| `parking/events/access_denied`      | access-orchestrator    | —                       |
| `parking/events/payment`            | payment-integration    | —                       |
| `parking/commands/barrier`          | access-orchestrator, dashboard | hardware-controller |

---

## Base de datos (SQLite)

Ubicación: `/var/lib/parking/parking.db`

| Tabla           | Contenido                              |
|-----------------|----------------------------------------|
| `whitelist`     | Placas autorizadas con vigencia        |
| `payment_events`| Historial de cobros                    |
| `access_events` | Auditoría completa de cada acceso      |

Cola de pagos offline: `/var/lib/parking/payment_queue.db`

---

## Políticas configurables

Editar `config/policies.yaml` (se lee al arrancar los servicios):

```yaml
access:
  min_confidence: 0.75      # OCR mínimo para aceptar una placa
  fault_policy: deny        # FAIL-CLOSED: cualquier error → deniega acceso

hardware:
  esp32_heartbeat_timeout_s: 5 # Watchdog ESP32: si Linux no responde en 5s, cierra barrera

circuit_breaker:
  fail_threshold: 5         # Fallos para abrir circuito de pagos
  reset_timeout_s: 30       # Segundos antes de reintentar
```

---

## Tests

```bash
source venv/bin/activate
pytest services/ -v
```

---

## Bugs corregidos respecto a las versiones originales

| ID  | Descripción                                                          |
|-----|----------------------------------------------------------------------|
| C1  | Los dos proyectos no se integraban — ahora conectados por MQTT       |
| C2  | Errores de OCR abrían la barrera — corregido con política FAIL-CLOSED|
| C3  | Heartbeat bloqueado por visión — ahora en hilo dedicado              |
| A1  | Buffer overflow en la interfaz de mensajería — corregido            |
| A4  | GPIO sin mutex en watchdog — eliminado el fallback inseguro          |
| A5  | `tmp_captures/` crecía sin límite — limpieza en `finally`            |
| A6  | Confianza Tesseract en escala 0–100 vs 0.0–1.0 — normalizada         |

---

## Nota sobre la barrera (servo → LED)

La interfaz de la barrera es siempre la misma a nivel de software: el orchestrator
ordena `OPEN`/`CLOSE` y el `hardware-controller` lo envía por UART al ESP32
(`barrier_open()` / `barrier_close()`). Para la maqueta de demostración, el actuador
físico se simula con un **LED controlado por PWM** en vez de un servo: el LED hace
una animación tipo "respiración" durante ~5 s al abrir, queda **encendido fijo**
mientras está abierto, y vuelve a "respirar" ~5 s al cerrar hasta apagarse. El
cierre automático tras 5 s sin vehículo se resuelve en el propio ESP32 con su
sensor HC-SR04. El protocolo UART y el lado Python **no cambian**.

## Nota sobre el firmware M4 (legado)

El directorio `firmware/m4/` contiene la primera versión del firmware de tiempo real, que corría en el núcleo **M4F del AM625** y se comunicaba con Linux vía **RPMsg**. Se migró a un **ESP32 WROOM-32 por UART** (commit `cff7e0e`) por simplicidad de cableado, depuración y flasheo. El código M4 se conserva solo como referencia histórica y **no forma parte del flujo actual**.
