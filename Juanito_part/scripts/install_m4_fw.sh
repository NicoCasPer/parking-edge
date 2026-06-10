#!/bin/bash

#################################################################
# install_m4_fw.sh
# Script de instalación del firmware M4 en BeaglePlay
#
# Instala el firmware en /opt/parking y configura systemd
#################################################################

set -e

# =====================================================================
# Configuración
# =====================================================================

INSTALL_PATH="/opt/parking"
FIRMWARE_BUILD_DIR="./Modulo_actuadores"
FIRMWARE_BIN="$FIRMWARE_BUILD_DIR/m4_firmware.bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# =====================================================================
# Funciones
# =====================================================================

log() {
    echo "[INFO] $*"
}

error() {
    echo "[ERROR] $*" >&2
    exit 1
}

# =====================================================================
# Validaciones
# =====================================================================

log "=== Instalador de Firmware M4 ==="

if [[ $EUID -ne 0 ]]; then
    error "Este script debe ejecutarse como root (usa: sudo $0)"
fi

if [[ ! -f "$FIRMWARE_BIN" ]]; then
    error "Firmware no compilado. Primero ejecuta: cd $FIRMWARE_BUILD_DIR && make"
fi

log "Firmware encontrado: $FIRMWARE_BIN"

# =====================================================================
# Crear directorios
# =====================================================================

log "Creando directorios en $INSTALL_PATH..."
mkdir -p "$INSTALL_PATH/firmware"
mkdir -p "$INSTALL_PATH/scripts"
mkdir -p "$INSTALL_PATH/Modelo"
mkdir -p "$INSTALL_PATH/tmp_captures"
mkdir -p "$INSTALL_PATH/logs"

# =====================================================================
# Copiar archivos
# =====================================================================

log "Copiando firmware..."
cp "$FIRMWARE_BIN" "$INSTALL_PATH/firmware/"

log "Copiando scripts..."
cp "./scripts/load_m4_fw.sh" "$INSTALL_PATH/scripts/"
chmod +x "$INSTALL_PATH/scripts/load_m4_fw.sh"

log "Copiando modelo YOLO..."
cp "./Modelo/best_plate_yolo11m_int8.tflite" "$INSTALL_PATH/Modelo/" 2>/dev/null || \
    log "⚠️  Modelo YOLO no encontrado (se descargará en tiempo de ejecución)"

log "Copiando módulo de visión..."
cp "./Modulo_vision/"*.py "$INSTALL_PATH/" 2>/dev/null || \
    log "⚠️  Módulos de visión no encontrados"

# =====================================================================
# Instalar servicio systemd
# =====================================================================

log "Instalando servicio systemd..."
cp "./systemd/m4-firmware.service" "/etc/systemd/system/"
cp "./systemd/m4-parking-service.service" "/etc/systemd/system/"

log "Recargando daemon de systemd..."
systemctl daemon-reload

# =====================================================================
# Asignar permisos
# =====================================================================

log "Asignando permisos..."
chown -R root:root "$INSTALL_PATH"
chmod 755 "$INSTALL_PATH/scripts"/*

# =====================================================================
# Información final
# =====================================================================

log ""
log "╔══════════════════════════════════════════════════╗"
log "║   ✅ INSTALACIÓN COMPLETADA                    ║"
log "║   Ubicación: $INSTALL_PATH"
log "║   Servicios instalados: 2"
log "╚══════════════════════════════════════════════════╝"
log ""
log "Próximos pasos:"
log "  1. Revisar configuración:"
log "     $ cat /etc/systemd/system/m4-firmware.service"
log ""
log "  2. Iniciar el firmware:"
log "     $ sudo systemctl start m4-firmware.service"
log ""
log "  3. Verificar estado:"
log "     $ sudo systemctl status m4-firmware.service"
log ""
log "  4. Ver logs:"
log "     $ journalctl -u m4-firmware.service -f"
log ""

exit 0
