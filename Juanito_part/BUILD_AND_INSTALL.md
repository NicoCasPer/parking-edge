# 🅿️  Sistema de Parqueadero Inteligente - BeaglePlay

Sistema distribuido de control de acceso a parqueaderos basado en BeaglePlay (AM62x dual-core).

## 📋 Estructura del Proyecto

```
Proyecto_final/
├── Modulo_actuadores/          # Firmware para Cortex-M4
│   ├── CMakeLists.txt
│   ├── Makefile
│   ├── main.c
│   ├── sensor_driver.c/h        # Driver del sensor HC-SR04
│   ├── rpmsg_interface.c/h      # Comunicación IPC con Linux
│   ├── watchdog.c/h             # Watchdog de seguridad
│   └── config.h                 # Configuración centralizada
│
├── Modulo_vision/               # Pipeline de visión (Python)
│   ├── capture.py              # Captura de frames
│   └── vision_pipeline.py       # Procesamiento YOLO + OCR
│
├── Modelo/
│   └── best_plate_yolo11m_int8.tflite
│
├── systemd/                     # Servicios systemd
│   ├── m4-firmware.service
│   └── m4-parking-service.service
│
├── scripts/                     # Scripts de deployment
│   ├── load_m4_fw.sh           # Carga el firmware en M4
│   ├── install_m4_fw.sh        # Instala todo el sistema
│   ├── test_rpmsg.sh           # Tests de RPMsg
│   └── debug_system.sh         # Debugging del sistema
│
└── Juanito.md                  # Documentación del proyecto
```

---

## 🛠️  Requisitos Previos

### Hardware
- **BeaglePlay** con AM62x (A53 + M4F)
- Cable USB para console serial
- Sensor HC-SR04 (ultrasonico)
- Servomotor o LED para barrera
- Cámara CSI

### Software - Linux (A53)
```bash
# Herramientas de compilación
sudo apt-get install build-essential cmake

# Python 3.9+
sudo apt-get install python3 python3-pip

# Dependencias de visión
pip3 install opencv-python ultralytics pytesseract

# Tesseract OCR
sudo apt-get install tesseract-ocr

# SDK de TI MCU+ (descargar desde ti.com)
# Se asume instalado en /opt/ti/mcu_plus_sdk
```

### Compilador ARM
```bash
# Opción 1: gcc-arm-none-eabi (recomendado)
sudo apt-get install gcc-arm-none-eabi

# Opción 2: TI CodeGen Compiler (LLVM)
# Descargar desde ti.com
```

---

## 🔨 Compilación

### 1. Compilar el firmware M4

#### Usando Makefile (rápido)
```bash
cd Modulo_actuadores
make clean
make build
# Genera: m4_firmware.elf, m4_firmware.bin, m4_firmware.hex
```

#### Usando CMake
```bash
cd Modulo_actuadores
mkdir build
cd build
cmake ..
make
```

**Salida esperada:**
```
✅ Compilación completada:
   text    data     bss     dec     hex filename
  12345     678    9012   22035    5613 m4_firmware.elf

Archivos generados:
-rw-r--r-- 1 user user 12345 Jun 10 12:34 m4_firmware.elf
-rw-r--r-- 1 user user  8901 Jun 10 12:34 m4_firmware.bin
-rw-r--r-- 1 user user 24678 Jun 10 12:34 m4_firmware.hex
```

### 2. Verificar compilación

```bash
# Ver símbolos
arm-none-eabi-nm m4_firmware.elf | head -20

# Ver tamaño
arm-none-eabi-size m4_firmware.elf

# Ver secciones
arm-none-eabi-objdump -h m4_firmware.elf
```

---

## 📦 Instalación

### 1. Instalación automática

```bash
# Desde el directorio raíz del proyecto
sudo ./scripts/install_m4_fw.sh
```

Esto:
- Crea `/opt/parking/` con estructura
- Copia firmware, scripts y modelo
- Instala servicios systemd
- Asigna permisos correctos

### 2. Instalación manual

```bash
# Crear directorios
sudo mkdir -p /opt/parking/{firmware,scripts,Modelo,tmp_captures,logs}

# Copiar archivos
sudo cp Modulo_actuadores/m4_firmware.bin /opt/parking/firmware/
sudo cp scripts/*.sh /opt/parking/scripts/
sudo chmod +x /opt/parking/scripts/*.sh

# Copiar modelo (si existe)
sudo cp Modelo/best_plate_yolo11m_int8.tflite /opt/parking/Modelo/

# Instalar servicios
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

---

## ▶️  Ejecución

### 1. Cargar firmware M4

```bash
# Opción A: Via systemd (recomendado)
sudo systemctl start m4-firmware.service
sudo systemctl enable m4-firmware.service  # Para autostart

# Opción B: Manual
sudo /opt/parking/scripts/load_m4_fw.sh /opt/parking/firmware/m4_firmware.bin
```

### 2. Verificar estado del M4

```bash
# Ver estado remoteproc
cat /sys/class/remoteproc/remoteproc0/state

# Ver logs del M4
cat /sys/class/remoteproc/remoteproc0/trace0

# Ver dispositivos RPMsg
ls /dev/rpmsg*
```

### 3. Iniciar servicio de parking (A53)

```bash
sudo systemctl start m4-parking-service.service
sudo systemctl enable m4-parking-service.service
```

### 4. Ver logs

```bash
# Firmware M4
sudo journalctl -u m4-firmware.service -f

# Servicio de parking
sudo journalctl -u m4-parking-service.service -f

# Sistema completo
journalctl -f
```

---

## 🧪 Testing

### 1. Test del sistema completo

```bash
# Ver estado de todo
sudo ./scripts/debug_system.sh

# Output esperado:
# ✅ Información del sistema
# ✅ Estado del M4 (RUNNING)
# ✅ Canales RPMsg disponibles
# ✅ Servicios activos
# ✅ GPIO del MCU
```

### 2. Test de RPMsg

```bash
# Enviar mensajes de prueba
sudo ./scripts/test_rpmsg.sh /dev/rpmsg0

# Enviará:
#  - HEARTBEAT (alimenta watchdog)
#  - OPEN (abre barrera)
#  - CLOSE (cierra barrera)
```

### 3. Test del sensor

```bash
# Poner un objeto a 30cm del HC-SR04
# Ver logs en tiempo real
sudo journalctl -u m4-firmware.service -f

# Esperado:
# [Sensor] Vehiculo detectado a 30 cm. Notificando...
# [RPMsg] Enviado: PRESENCE_DETECTED
```

### 4. Test de visión

```bash
cd Modulo_vision

# Ejecutar pipeline manualmente
python3 -c "
from capture import capturar_rafaga_vehiculo
from vision_pipeline import procesar_imagenes_parqueadero

rutas = capturar_rafaga_vehiculo()
placa, roi = procesar_imagenes_parqueadero(rutas)
print(f'Placa detectada: {placa}')
"
```

---

## 🐛 Troubleshooting

### El M4 no inicia

```bash
# Verificar remoteproc
ls -la /sys/class/remoteproc/

# Ver estado
cat /sys/class/remoteproc/remoteproc0/state

# Ver error en logs
sudo dmesg | tail -20
journalctl -xe
```

### No hay comunicación RPMsg

```bash
# Verificar que el M4 está running
cat /sys/class/remoteproc/remoteproc0/state
# Debe mostrar: running

# Verificar dispositivo RPMsg
ls /dev/rpmsg*

# Si no aparece, reiniciar M4
echo stop > /sys/class/remoteproc/remoteproc0/state
sleep 1
echo start > /sys/class/remoteproc/remoteproc0/state
```

### Sensor no detecta objetos

```bash
# Ver logs del sensor
sudo journalctl -u m4-firmware.service -f

# Verificar GPIO
cat /sys/class/gpio/gpio32/value  # TRIGGER (MCU_GPIO0_0)
cat /sys/class/gpio/gpio34/value  # ECHO (MCU_GPIO0_2)

# Verificar wiring del HC-SR04
# - VCC → 5V
# - GND → GND
# - TRIG → MCU_GPIO0_0 (J5 pin 1)
# - ECHO → MCU_GPIO0_2 con divisor resistivo (J5 pin 3)
```

### Problemas de OCR

```bash
# Verificar que Tesseract está instalado
tesseract --version

# Verificar modelo del lenguaje
ls /usr/share/tesseract-ocr/*/

# Reinstalar si es necesario
sudo apt-get install tesseract-ocr-eng
```

---

## 📊 Monitoreo

### Ver estado en tiempo real

```bash
# Dashboard de systemd
systemctl status m4-firmware.service m4-parking-service.service

# Logs en vivo
sudo journalctl -f

# Uso de recursos
top  # Buscar procesos Python
free # Memoria libre
```

### Métricas de rendimiento

```bash
# Uptime del M4
cat /sys/class/remoteproc/remoteproc0/uptime

# Temperatura CPU
cat /sys/class/thermal/thermal_zone0/temp

# Estadísticas de red
netstat -s
```

---

## 🔧 Configuración

### Parámetros principales

Editar `Modulo_actuadores/config.h`:

```c
// Distancia de detección (cm)
#define DISTANCE_THRESHOLD_CM   (50U)

// Timeout del watchdog (ms)
#define HEARTBEAT_TIMEOUT_MS    (5000U)

// Debounce de detección (ms)
#define DETECTION_DEBOUNCE_MS   (500U)
```

### Parámetros de servicios systemd

Editar `/etc/systemd/system/m4-firmware.service`:

```ini
# Cambiar timeout de startup
TimeoutStartSec=30

# Cambiar máximo de reintentos
StartLimitBurst=3
StartLimitIntervalSec=600
```

Luego recargar:
```bash
sudo systemctl daemon-reload
sudo systemctl restart m4-firmware.service
```

---

## 📝 Logs y Debugging

### Ubicaciones de logs

```
Firmware M4:          systemd journal (journalctl)
Servicio parking:     systemd journal + /opt/parking/logs/
Scripts:              /opt/parking/logs/m4_fw_load.log
```

### Habilitar debug verbose

```bash
# En tiempo de compilación (editar CMakeLists.txt)
set(DEBUG_ENABLED 1)

# En tiempo de ejecución (via dmesg)
echo 8 > /proc/sys/kernel/printk
sudo dmesg -w
```

---

## 🚀 Deployment

### Producción

```bash
# 1. Compilar release
cd Modulo_actuadores
CFLAGS="-O2 -DNDEBUG" make clean build

# 2. Instalar
sudo ./scripts/install_m4_fw.sh

# 3. Habilitar autostart
sudo systemctl enable m4-firmware.service
sudo systemctl enable m4-parking-service.service

# 4. Reboot para verificar
sudo reboot

# 5. Verificar después del reboot
sudo systemctl status m4-firmware.service
sudo ./scripts/debug_system.sh
```

---

## 📚 Documentación

- [BeaglePlay Docs](https://beagleboard.org/docs)
- [TI AM62x Reference Manual](https://www.ti.com/product/AM6254)
- [FreeRTOS Documentation](https://www.freertos.org/Documentation/161204_Atmel_SAM4L_FreeRTOS.html)
- [YOLO Docs](https://docs.ultralytics.com/)

---

## ✅ Checklist de Setup

- [ ] Compilar firmware M4 sin errores
- [ ] Instalar archivos de sistema
- [ ] Cargar firmware en M4
- [ ] Verificar estado con `debug_system.sh`
- [ ] Test de RPMsg
- [ ] Test del sensor
- [ ] Captura de frames funcionando
- [ ] OCR detectando placas
- [ ] Servicios con autostart habilitado

---

## 📞 Soporte

Para problemas:
1. Revisar `/opt/parking/logs/`
2. Ejecutar `./scripts/debug_system.sh`
3. Consultar logs: `journalctl -xe`
4. Verificar hardware: sensor, servo, conexiones

---

**Última actualización:** 2026-06-10  
**Versión firmware:** v1.0.0
