# 📊 Dashboard - Resumen Completo

## 🎯 Objetivo

Crear un dashboard web **moderno, minimalista y funcional** para controlar y monitorear el sistema de parqueadero en BeaglePlay con:
- ✅ Visualización de cámara en vivo
- ✅ Control manual de barrera (abrir/cerrar)
- ✅ Registro de entradas/salidas
- ✅ Estadísticas en tiempo real
- ✅ Diseño responsivo y moderno

---

## 📁 Archivos Creados

### Backend (Python/Flask)

```
dashboard.py (250+ líneas)
├── Servidor Flask en puerto 5000
├── API REST con 10+ endpoints
├── Gestión de RPMsg
├── Persistencia JSON
└── Logging completo
```

**Funciones principales:**
- `abrir_barrera()` - Envía OPEN al M4
- `cerrar_barrera()` - Envía CLOSE al M4
- `registrar_vehiculo()` - Guarda placa en JSON
- Heartbeat automático (cada 1 segundo)
- Auto-cierre de barrera después de 10s

### Frontend (HTML/CSS/JS)

```
templates/dashboard.html (140+ líneas)
├── Layout en 3 secciones
├── Cámara (izquierda)
├── Controles (centro)
└── Registro (derecha)
```

```
static/css/style.css (500+ líneas)
├── Tema oscuro moderno
├── Gradientes y sombras
├── Responsivo (mobile/tablet/desktop)
├── Animaciones suaves
└── Paleta: Azul/Verde/Rojo
```

```
static/js/app.js (300+ líneas)
├── API client
├── Event listeners
├── Auto-refresh (5s stats, 10s vehículos)
├── Notificaciones toasts
└── Estado global
```

---

## 🎨 Diseño Visual

### Layout Principal

```
┌─────────────────────────────────────────────────────────────┐
│ 🅿️ PARQUEADERO INTELIGENTE    M4:🟢  Barrera:🔴  Cámara:⚪ │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────┐  ┌──────────────┐   │
│  │ 📹 CÁMARA       │  │ 🚪 BARRERA  │  │ 📋 REGISTRO  │   │
│  │ ┌─────────────┐ │  │   [ABIERTA] │  │ ┌──────────┐ │   │
│  │ │  [VIDEO]    │ │  │  [ABRIR]    │  │ │Placa:    │ │   │
│  │ │  640x480    │ │  │  [CERRAR]   │  │ │[ABC-123] │ │   │
│  │ └─────────────┘ │  │             │  │ │Tipo:     │ │   │
│  │ [Act. Cámara]   │  │ Hoy: 12     │  │ │[Entrada] │ │   │
│  │ Res: 1280x720   │  │ Entr: 45    │  │ │[Registr]│ │   │
│  │ FPS: 30         │  │ Sal: 43     │  │ └──────────┘ │   │
│  │ Estado: Activo  │  │             │  │              │   │
│  └─────────────────┘  └─────────────┘  │ 📝 ÚLTIMOS:  │   │
│                                        │ 14:32 ABC-123│   │
│                                        │ 14:15 XYZ-789│   │
│                                        │ 14:00 DEF-456│   │
│                                        └──────────────┘   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ 🅿️ v1.0.0 | Última actualización: 14:32:15                 │
└─────────────────────────────────────────────────────────────┘
```

### Colores y Estilo

| Elemento | Color | Uso |
|----------|-------|-----|
| Primary | #2563eb (Azul) | Botones, iconos |
| Accent | #10b981 (Verde) | Éxito, abrir |
| Danger | #ef4444 (Rojo) | Cerrar, error |
| Background | #0f172a | Fondo oscuro |
| Surface | #1e293b | Tarjetas |
| Text | #e2e8f0 | Texto principal |

---

## 🔌 API REST Endpoints

| Método | Endpoint | Función |
|--------|----------|---------|
| GET | `/api/status` | Estado del sistema |
| POST | `/api/barrier/open` | Abrir barrera |
| POST | `/api/barrier/close` | Cerrar barrera |
| GET | `/api/barrier/status` | Estado barrera |
| POST | `/api/camera/toggle` | Activar/desactivar cámara |
| GET | `/api/vehicles` | Listar vehículos |
| POST | `/api/vehicles` | Registrar vehículo |
| POST | `/api/heartbeat` | Enviar heartbeat a M4 |
| GET | `/api/dashboard/stats` | Estadísticas |
| GET | `/api/system/m4-status` | Estado M4 |

---

## 🚀 Características Implementadas

### ✅ Visualización de Cámara

```javascript
// Botón de activación
[Activar Cámara] / [Desactivar Cámara]

// Cambios de UI
- Muestra/oculta placeholder
- Inicia/detiene stream
- Actualiza estado en badge
```

### ✅ Control de Barrera

```javascript
// Botones
[ABRIR] → POST /api/barrier/open
[CERRAR] → POST /api/barrier/close

// Comportamiento
- Disable botones mientras se procesa
- Mostrar "Abriendo..." / "Cerrando..."
- Auto-cierre después de 10s
- Visual feedback con iconos
```

### ✅ Registro de Vehículos

```javascript
// Formulario manual
Placa: [ABC-123] Tipo: [Entrada ▼] [Registrar]

// Auto-registro (cuando se detecta)
Automático desde M4 → Vision → Guardado

// Log en tiempo real
- Últimos 20 registros
- Timestamp preciso
- Icono entrada/salida
- Color según tipo
```

### ✅ Estadísticas

```javascript
// Tarjetas rápidas
Hoy: 12 | Entradas: 45 | Salidas: 43

// Badges de estado
M4: 🟢 En línea | Barrera: 🔴 Cerrada | Cámara: ⚪ Inactiva
```

### ✅ Actualización en Tiempo Real

```javascript
// Auto-refresh
- Stats cada 5 segundos
- Vehículos cada 10 segundos
- Timestamp actualizado

// Notificaciones
Toast con iconos y colores
Duran 4 segundos automáticamente
```

---

## 🔄 Flujo de Interacción

### Abrir Barrera Manualmente

```
Usuario hace click [ABRIR]
    ↓
Frontend desactiva botón
    ↓
API: POST /api/barrier/open
    ↓
Backend: enviar_comando_m4("OPEN")
    ↓
RPMsg → M4 recibe OPEN
    ↓
M4: GPIO_pinWriteHigh(SERVO)
    ↓
Barrera se ABRE
    ↓
Frontend muestra ✅ "Barrera abierta"
    ↓
Espera 10 segundos
    ↓
Auto-cierre: API: POST /api/barrier/close
    ↓
Barrera se CIERRA
```

### Registrar Vehículo Manualmente

```
Usuario ingresa:
  Placa: ABC-123
  Tipo: Entrada
    ↓
Click [Registrar]
    ↓
API: POST /api/vehicles
  {placa: "ABC-123", tipo: "entrada"}
    ↓
Backend: registrar_vehiculo()
    ↓
Guardar en /opt/parking/logs/vehicles.json
    ↓
Frontend: loadVehicles()
    ↓
Mostrar en log con timestamp
    ↓
✅ Notificación "Vehículo registrado"
```

---

## 📊 Datos Persistentes

### Archivo de Registro: `vehicles.json`

```json
[
  {
    "timestamp": "2026-06-10T14:32:00",
    "placa": "ABC-123",
    "tipo": "entrada"
  },
  {
    "timestamp": "2026-06-10T14:15:30",
    "placa": "XYZ-789",
    "tipo": "salida"
  },
  {
    "timestamp": "2026-06-10T14:00:15",
    "placa": "DEF-456",
    "tipo": "entrada"
  }
]
```

Ubicación: `/opt/parking/logs/vehicles.json`
Formato: JSON puro
Carga: Al iniciar dashboard
Guarda: Cada vez que se registra un vehículo

---

## 🌐 Acceso

### Desarrollo Local

```bash
python3 dashboard.py
http://localhost:5000
```

### Producción en BeaglePlay

```bash
gunicorn -w 4 -b 0.0.0.0:5000 dashboard:app
http://<IP_BEAGLEPLAY>:5000
```

### Como Servicio

```bash
sudo systemctl start dashboard.service
http://<IP_BEAGLEPLAY>:5000
```

---

## 🎯 Casos de Uso

### 1. Monitor en Vivo (24/7)

```
Ejecutar dashboard en pantalla grande
Monitor el flujo de vehículos
Ver estadísticas en tiempo real
```

### 2. Control Manual

```
Abrir barrera manualmente si falla el sensor
Cerrar barrera manualmente por emergencia
Registrar vehículos que no se detecten
```

### 3. Auditoría

```
Ver historial completo de vehículos
Contar entradas/salidas por hora
Exportar reportes (futuro)
```

### 4. Debugging

```
Ver estado del M4 en tiempo real
Verificar comunicación RPMsg
Confirmar que los comandos se envían
```

---

## 🔐 Seguridad

### Recomendaciones

- [ ] Cambiar puerto 5000 en producción
- [ ] Configurar HTTPS con certificado
- [ ] Agregar autenticación (username/password)
- [ ] Implementar rate limiting
- [ ] Encriptar comunicación RPMsg
- [ ] Backup diario de vehicles.json
- [ ] Logs auditados

### Medidas Actuales

✅ Validación de entrada en formulario
✅ Try/except en todas las APIs
✅ Logging de todas las acciones
✅ No exposición de rutas privadas
✅ CORS habilitado (ajustar en producción)

---

## 📈 Estadísticas de Código

```
Backend (dashboard.py):     ~250 líneas
Frontend (HTML):            ~140 líneas
Estilos (CSS):              ~500 líneas
Lógica (JavaScript):        ~300 líneas
Documentación:              ~200 líneas
────────────────────────────────────────
Total:                      ~1390 líneas
```

---

## 🚀 Mejoras Futuras

- [ ] WebSocket en lugar de polling
- [ ] Gráficos de ocupación (Chart.js)
- [ ] Exportar PDF/CSV de reportes
- [ ] Integración con base de datos
- [ ] Autenticación de usuarios
- [ ] Dark/Light mode toggle
- [ ] Notificaciones por email
- [ ] App móvil nativa (React Native)
- [ ] Predicción de ocupación con ML
- [ ] Integración con sistemas de pago

---

## 🛠️ Mantenimiento

### Limpieza de Logs

```bash
# Rotación de logs cada 7 días
logrotate -f /etc/logrotate.d/parking-dashboard

# Limpiar vehículos antiguos (mantener últimos 10000)
python3 -c "
import json
with open('/opt/parking/logs/vehicles.json') as f:
    data = json.load(f)
with open('/opt/parking/logs/vehicles.json', 'w') as f:
    json.dump(data[-10000:], f)
"
```

### Respaldo

```bash
# Backup diario a las 3am
0 3 * * * cp /opt/parking/logs/vehicles.json /opt/parking/backup/vehicles_$(date +%Y%m%d).json
```

---

## 📞 Contacto y Soporte

Para problemas o mejoras:

1. Ver logs: `journalctl -u dashboard.service -f`
2. Test API: `curl http://localhost:5000/api/status`
3. Verificar RPMsg: `ls -la /dev/rpmsg*`
4. Revisar documentación: `DASHBOARD_README.md`

---

**Dashboard v1.0.0 - 2026-06-10**  
Minimalista • Moderno • Funcional  
🅿️ Sistema de Parqueadero Inteligente BeaglePlay
