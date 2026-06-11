# 🎨 Dashboard - Sistema de Parqueadero Inteligente

Dashboard web moderno y minimalista para controlar y monitorear el sistema de parqueadero en BeaglePlay.

## ✨ Características

### 📹 Visualización de Cámara
- **Stream en vivo** de la cámara CSI
- **Botón de activación/desactivación** para economizar energía
- **Indicador de estado** de la cámara
- **Información de resolución** y FPS

### 🚪 Control de Barrera
- **Botón ABRIR** - Abre la barrera manualmente
- **Botón CERRAR** - Cierra la barrera manualmente
- **Indicador visual** del estado (abierta/cerrada)
- **Auto-cierre** después de 10 segundos (seguridad)

### 📋 Registro de Vehículos
- **Formulario manual** para registrar placas
- **Selector de tipo** (entrada/salida)
- **Log en tiempo real** de todos los vehículos
- **Historial persistente** guardado en JSON

### 📊 Estadísticas
- **Vehículos hoy** - Total registrado en el día
- **Entradas totales** - Número de entradas
- **Salidas totales** - Número de salidas
- **Estados del sistema** - M4, barrera, cámara

---

## 🚀 Instalación

### 1. Instalar dependencias

```bash
# Instalar Flask y dependencias web
pip3 install -r requirements.txt

# Específicamente:
pip3 install Flask Flask-CORS
```

### 2. Estructura de carpetas

```
Proyecto_final/
├── dashboard.py           ← Servidor Flask
├── templates/
│   └── dashboard.html     ← Frontend
├── static/
│   ├── css/
│   │   └── style.css      ← Estilos
│   └── js/
│       └── app.js         ← Lógica del cliente
└── requirements.txt
```

---

## ▶️ Ejecutar Dashboard

### Opción 1: Desarrollo (local)

```bash
# Desde el directorio del proyecto
python3 dashboard.py

# O especificar host y puerto
python3 dashboard.py --host 0.0.0.0 --port 5000
```

**Acceder en:** `http://localhost:5000`

### Opción 2: Producción en BeaglePlay

```bash
# Instalar gunicorn (WSGI server)
pip3 install gunicorn

# Ejecutar con 4 workers
gunicorn -w 4 -b 0.0.0.0:5000 dashboard:app

# O con more verbosity
gunicorn -w 4 -b 0.0.0.0:5000 --log-level debug dashboard:app
```

**Acceder desde otra máquina:** `http://<IP_BEAGLEPLAY>:5000`

### Opción 3: Como servicio systemd (recomendado)

Crear archivo `/etc/systemd/system/dashboard.service`:

```ini
[Unit]
Description=Dashboard Parqueadero Inteligente
After=m4-firmware.service network.target
Wants=m4-firmware.service

[Service]
Type=simple
WorkingDirectory=/opt/parking
Environment="PYTHONUNBUFFERED=1"
Environment="PYTHONPATH=/opt/parking"
ExecStart=/usr/bin/python3 dashboard.py
Restart=on-failure
RestartSec=10

StandardOutput=journal
StandardError=journal
SyslogIdentifier=parking-dashboard

User=root
Group=root

[Install]
WantedBy=multi-user.target
```

Activar servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl enable dashboard.service
sudo systemctl start dashboard.service

# Ver logs
sudo journalctl -u dashboard.service -f
```

---

## 🎯 Uso del Dashboard

### Panel Principal (Izquierda)

```
┌─────────────────────────┐
│   CÁMARA EN VIVO        │
│  ┌─────────────────┐    │
│  │   [Video]       │    │
│  │   640x480       │    │
│  └─────────────────┘    │
│  [Activar Cámara]       │
│  Resolución: 1280x720   │
│  FPS: 30                │
│  Estado: Activo         │
└─────────────────────────┘
```

**Funciones:**
- Click en `[Activar Cámara]` para encender/apagar
- Muestra stream en vivo de la CSI
- Información de configuración en tiempo real

### Panel Control (Centro)

```
┌─────────────────────────┐
│   CONTROL BARRERA       │
│   ┌───────────────┐     │
│   │   🚪 CERRADA  │     │
│   └───────────────┘     │
│  [ABRIR]    [CERRAR]    │
│                         │
│  Hoy: 12 | Entr: 45     │
│           | Sal: 43     │
└─────────────────────────┘
```

**Funciones:**
- `[ABRIR]` - Envía comando OPEN al M4
- `[CERRAR]` - Envía comando CLOSE al M4
- Auto-cierre a los 10 segundos
- Muestra estadísticas rápidas

### Panel Registro (Derecha)

```
┌─────────────────────────┐
│   REGISTRO VEHÍCULOS    │
│ ┌─────────────────────┐ │
│ │ Placa: [ABC-123]    │ │
│ │ Tipo:  [Entrada  ▼] │ │
│ │        [Registrar]  │ │
│ └─────────────────────┘ │
│                         │
│ 14:32 ABC-123 📥 Ent.   │
│ 14:15 XYZ-789 📤 Sal.   │
│ 14:00 DEF-456 📥 Ent.   │
│ (más...)                │
└─────────────────────────┘
```

**Funciones:**
- Formulario para registrar placas manualmente
- Selector de tipo (entrada/salida)
- Log automático de registros
- Historial scrolleable

---

## 🔌 API REST

El dashboard proporciona las siguientes APIs:

### Estado del Sistema

```bash
GET /api/status
# Respuesta:
{
  "barrier_status": "closed",
  "camera_enabled": false,
  "m4_status": "running",
  "vehicles_today": 12
}
```

### Control de Barrera

```bash
# Abrir
POST /api/barrier/open
# Respuesta: {"status": "success"}

# Cerrar
POST /api/barrier/close
# Respuesta: {"status": "success"}

# Estado
GET /api/barrier/status
# Respuesta: {"status": "closed"}
```

### Control de Cámara

```bash
POST /api/camera/toggle
# Body: {"enable": true}
# Respuesta: {"status": "success", "camera_enabled": true}
```

### Vehículos

```bash
# Listar vehículos
GET /api/vehicles
# Respuesta: [{"placa": "ABC-123", "tipo": "entrada", "timestamp": "2026-06-10T14:32:00"}]

# Registrar vehículo
POST /api/vehicles
# Body: {"placa": "ABC-123", "tipo": "entrada"}
# Respuesta: {"status": "success"}
```

### Estadísticas

```bash
GET /api/dashboard/stats
# Respuesta:
{
  "vehicles_today": 12,
  "total_entries": 45,
  "total_exits": 43,
  "barrier_status": "closed",
  "camera_enabled": false,
  "m4_status": "running"
}
```

### Heartbeat

```bash
POST /api/heartbeat
# Envía heartbeat al M4
# Respuesta: {"status": "success"}
```

---

## 🎨 Diseño

### Paleta de Colores

```
Primary:      #2563eb (Azul)
Secondary:    #1e40af (Azul oscuro)
Accent:       #10b981 (Verde)
Danger:       #ef4444 (Rojo)
Warning:      #f59e0b (Naranja)
Background:   #0f172a (Negro-azul)
Surface:      #1e293b (Gris oscuro)
Text:         #e2e8f0 (Blanco frío)
```

### Características de Diseño

- ✅ **Tema oscuro** - Menos fatiga visual
- ✅ **Minimalista** - Solo lo esencial
- ✅ **Responsivo** - Funciona en móvil
- ✅ **Moderno** - Gradientes, sombras, animaciones
- ✅ **Accesible** - Contraste suficiente
- ✅ **Rápido** - Carga en < 2 segundos

---

## 🔧 Configuración

### Variables de Entorno

```bash
# En dashboard.py o .env

# RPMsg device
RPMSG_DEVICE = "/dev/rpmsg0"

# Directorio de logs
LOG_PATH = Path("/opt/parking/logs")

# Archivo de registro de vehículos
VEHICLE_LOG_FILE = LOG_PATH / "vehicles.json"

# URL del stream de cámara (mjpeg)
CAMERA_STREAM_URL = "http://localhost:8081"
```

### Puerto

Por defecto: `5000`

Cambiar en `dashboard.py`:

```python
if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,  # ← Cambiar aquí
        debug=False,
        threaded=True
    )
```

---

## 📝 Logs

Los logs se guardan en `/opt/parking/logs/`:

```bash
# Ver logs en vivo
tail -f /opt/parking/logs/dashboard.log

# Ver último registro de vehículos
cat /opt/parking/logs/vehicles.json

# Ver todos los registros
journalctl -u dashboard.service
```

---

## 🐛 Troubleshooting

### Dashboard no abre

```bash
# Verificar que Flask está escuchando
netstat -an | grep 5000

# Verificar puerto
lsof -i :5000

# Matar proceso anterior
kill -9 $(lsof -t -i :5000)
```

### API no responde

```bash
# Verificar RPMsg
ls /dev/rpmsg*

# Test manual
echo "HEARTBEAT" > /dev/rpmsg0

# Ver logs
tail -f /opt/parking/logs/dashboard.log
```

### Cámara no se activa

```bash
# Verificar cámara
v4l2-ctl --list-devices

# Verificar stream
curl http://localhost:8081
```

### Registro vacío

```bash
# Ver archivo de registro
cat /opt/parking/logs/vehicles.json

# Verificar permisos
ls -la /opt/parking/logs/
```

---

## 📊 Ejemplos de Uso

### Test de API con curl

```bash
# Ver estado
curl http://localhost:5000/api/status

# Abrir barrera
curl -X POST http://localhost:5000/api/barrier/open

# Registrar vehículo
curl -X POST http://localhost:5000/api/vehicles \
  -H "Content-Type: application/json" \
  -d '{"placa":"ABC-123","tipo":"entrada"}'

# Ver vehículos
curl http://localhost:5000/api/vehicles
```

### Test de API con Python

```python
import requests

API = "http://localhost:5000/api"

# Abrir barrera
response = requests.post(f"{API}/barrier/open")
print(response.json())

# Registrar vehículo
data = {"placa": "ABC-123", "tipo": "entrada"}
response = requests.post(f"{API}/vehicles", json=data)
print(response.json())

# Estadísticas
response = requests.get(f"{API}/dashboard/stats")
print(response.json())
```

---

## 🚀 Desarrollo Futuro

- [ ] WebSocket para actualizaciones en tiempo real
- [ ] Gráficos de ocupación
- [ ] Reporte de ingresos
- [ ] Integración con BD
- [ ] Autenticación de usuarios
- [ ] Export de datos (CSV/PDF)
- [ ] Notificaciones push
- [ ] App móvil nativa
- [ ] Análisis de patrones

---

## 📞 Soporte

Para problemas:

1. Verificar logs: `journalctl -u dashboard.service -f`
2. Ejecutar debug: `python3 dashboard.py --debug`
3. Probar APIs manualmente
4. Ver documentación en `CHANGES_AND_FLOW.md`

---

**Dashboard v1.0.0 - 2026-06-10**  
🅿️ Sistema de Parqueadero Inteligente BeaglePlay
