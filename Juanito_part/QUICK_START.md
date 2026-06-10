# 🚀 Quick Start - Sistema de Parqueadero Inteligente

Guía rápida para tener el sistema funcionando en 5 minutos.

## ✅ Requisitos Previos (30 segundos)

```bash
# Instalar compilador ARM
sudo apt-get install gcc-arm-none-eabi

# Instalar Python 3.9+
sudo apt-get update && sudo apt-get install python3 python3-pip

# Instalar dependencias
pip3 install -r requirements.txt

# Instalar Tesseract OCR
sudo apt-get install tesseract-ocr
```

## 🔨 Paso 1: Compilar el Firmware M4 (2 minutos)

```bash
cd Modulo_actuadores

# Compilar
make clean build

# Verificar que se crearon los archivos
ls -lh m4_firmware.{elf,bin,hex}
```

**Esperado:**
```
-rw-r--r-- m4_firmware.elf (tamaño ~20KB)
-rw-r--r-- m4_firmware.bin (tamaño ~12KB)
-rw-r--r-- m4_firmware.hex (tamaño ~30KB)
```

## 📦 Paso 2: Instalar en el Sistema (1 minuto)

```bash
cd ../

# Instalar todo
sudo ./scripts/install_m4_fw.sh

# Verificar
ls -la /opt/parking/
```

## ▶️ Paso 3: Cargar Firmware en M4 (1 minuto)

```bash
# Opción A: Via systemd (recomendado)
sudo systemctl start m4-firmware.service

# Opción B: Manual
sudo /opt/parking/scripts/load_m4_fw.sh /opt/parking/firmware/m4_firmware.bin
```

## ✓ Paso 4: Verificar que Funciona (30 segundos)

```bash
# Ver estado del sistema
sudo ./scripts/debug_system.sh

# Debe mostrar:
# ✅ Core M4: m4fss0_core0 - RUNNING
# ✅ Canal RPMsg disponible
# ✅ Servicios activos
```

## 🧪 Paso 5: Test RPMsg (1 minuto)

```bash
# Enviar mensajes de prueba
sudo ./scripts/test_rpmsg.sh

# Debe mostrar:
# ✅ HEARTBEAT enviado
# ✅ OPEN enviado (barrera se abre)
# ✅ CLOSE enviado (barrera se cierra)
```

## 📊 Resultado Final

Si todo pasó, tendrás:
- ✅ Firmware M4 compilado y ejecutando
- ✅ Comunicación RPMsg funcionando
- ✅ Sensor midiendo distancias
- ✅ Barrera controlable via comandos
- ✅ Watchdog de seguridad activo

## 🔄 Próximos Pasos

1. **Conectar hardware:**
   - HC-SR04 (sensor ultrasonico)
   - Servomotor/LED (barrera)
   - Cámara CSI

2. **Ajustar parámetros:**
   - Editar `Modulo_actuadores/config.h`
   - Cambiar umbrales de detección

3. **Iniciar servicio de visión:**
   ```bash
   sudo systemctl start m4-parking-service.service
   ```

4. **Ver logs en vivo:**
   ```bash
   sudo journalctl -u m4-firmware.service -f
   sudo journalctl -u m4-parking-service.service -f
   ```

## 🐛 Si Algo Falla

```bash
# 1. Verificar que el M4 está running
cat /sys/class/remoteproc/remoteproc0/state
# Debe mostrar: running

# 2. Ver logs del M4
cat /sys/class/remoteproc/remoteproc0/trace0

# 3. Ver logs de systemd
journalctl -xe

# 4. Ejecutar debug completo
sudo ./scripts/debug_system.sh
```

## 📚 Documentación Completa

Ver [BUILD_AND_INSTALL.md](BUILD_AND_INSTALL.md) para:
- Instalación manual paso a paso
- Troubleshooting detallado
- Configuración avanzada
- Monitoreo y métricas

---

**¡Listo! El sistema debe estar funcionando ahora.** ✨
