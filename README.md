# parking-edge

Sistema de control de acceso para parqueadero inteligente sobre **BeaglePlay (TI AM625)**.  
Combina visión por computadora (YOLO11m INT8 + Tesseract), firmware de tiempo real en el núcleo M4F (FreeRTOS), y microservicios Python comunicados por MQTT.

---

## Arquitectura

```
Sensor ultrasónico
      │
      ▼
┌─────────────┐   RPMsg   ┌─────────────────────┐
│  M4F / FreeRTOS │◄────────►│ hardware-controller  │
│  (watchdog,     │         │ (Python / RPMsg↔MQTT)│
│   sensor,       │         └────────┬────────────┘
│   barrera GPIO) │                  │ MQTT
└─────────────┘                  ▼
                          ┌──────────────┐
                          │ vision-service│  ◄── Cámara
                          │ YOLO + OCR   │
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
                       │hardware-controller│ → RPMsg → M4 → GPIO barrera
                       └──────────────────┘

    payment-integration  ─── HTTPS ──► Proveedor externo (+ circuit breaker)
    connectivity-service ─── telemetría del sistema
    web-dashboard        ─── Flask + WebSocket (panel de control)
```

**Flujo completo de un acceso:**  
`Vehículo llega → M4 detecta presencia → RPMsg → hardware-controller → MQTT → vision-service → YOLO+OCR → MQTT → access-orchestrator → whitelist/pago → MQTT → hardware-controller → RPMsg → M4 abre barrera`

---

## Estructura del repositorio

```
parking-edge/
├── firmware/
│   ├── m4/src/          # FreeRTOS: main, rpmsg_interface, sensor_driver, watchdog
│   └── pru/src/         # PRU: PWM barrera (stub) e IRQ GPIO (stub)
├── services/
│   ├── common/          # event_bus, event_models, database (compartidos)
│   ├── hardware_controller/
│   ├── vision_service/
│   ├── access_orchestrator/
│   ├── payment_integration/   # circuit breaker + store-and-forward
│   ├── connectivity_service/
│   └── mock_payment_server/   # servidor de pagos local para pruebas
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
├── systemd/             # 9 unit files listos para instalar
├── scripts/
│   ├── install.sh       # Instalación completa en BeaglePlay
│   ├── healthcheck.sh   # Verifica todos los servicios
│   └── load_m4_fw.sh    # Carga el firmware M4 vía remoteproc
├── Modelo/              # best_plate_yolo11m_int8.tflite (no en git, ver abajo)
└── requirements.txt
```

---

## Requisitos

### En el BeaglePlay (destino)
- BeaglePlay con BeaglePlay Debian 12 o Ubuntu 22.04 LTS ARM
- Python 3.10+
- Tesseract OCR: `sudo apt install tesseract-ocr`
- Mosquitto: `sudo apt install mosquitto`
- SQLite 3: `sudo apt install sqlite3`
- Toolchain M4 (para compilar firmware): `sudo apt install gcc-arm-none-eabi`
- TI MCU+ SDK instalado en `/opt/ti/mcu_plus_sdk` (ver [ti.com/tool/MCU-PLUS-SDK-AM62X](https://www.ti.com/tool/MCU-PLUS-SDK-AM62X))

### En la PC de desarrollo (para push al repo)
- Git
- Acceso SSH al BeaglePlay

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
PAYMENT_PROVIDER_URL=https://tu-proveedor.com
PAYMENT_API_KEY=tu-api-key-real
DASHBOARD_SECRET_KEY=una-clave-aleatoria-larga
DASHBOARD_ADMIN_PASSWORD=contraseña-segura
```

> **Nunca versionar `app.env`** — está en `.gitignore`.

### 5. Compilar y cargar el firmware M4

```bash
cd /opt/parking-edge/firmware/m4
make
sudo bash /opt/parking-edge/scripts/load_m4_fw.sh
```

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

## Desarrollo local (sin BeaglePlay)

Para probar sin hardware físico, activar el modo simulado:

```bash
export RPMSG_SIMULATED=true
export MOCK_PAYMENT_SERVER=true
export CAMERA_INDEX=0        # cámara de la laptop
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
- Estadísticas del día (accesos / denegados / whitelist)
- Override manual de barrera (OPEN / STOP / CLOSE)
- Gestión de whitelist (agregar / actualizar placas)

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

Editar `config/policies.yaml` (no requiere reiniciar los servicios en frío, se lee al arrancar):

```yaml
access:
  min_confidence: 0.75      # OCR mínimo para aceptar una placa
  fault_policy: deny        # FAIL-CLOSED: cualquier error → deniega acceso

hardware:
  m4_heartbeat_timeout_s: 5 # Watchdog M4: si Linux no responde en 5s, cierra barrera

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
| A1  | Buffer overflow en `rpmsg_interface.c` — corregido                   |
| A4  | GPIO sin mutex en watchdog — eliminado el fallback inseguro          |
| A5  | `tmp_captures/` crecía sin límite — limpieza en `finally`            |
| A6  | Confianza Tesseract en escala 0–100 vs 0.0–1.0 — normalizada         |
