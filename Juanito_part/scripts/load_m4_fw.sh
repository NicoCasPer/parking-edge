#!/bin/bash

#################################################################
# load_m4_fw.sh
# Script para cargar el firmware del M4F en BeaglePlay
#
# Uso: ./load_m4_fw.sh <firmware.bin>
#
# Requisitos:
#  - Acceso de root (para remoteproc)
#  - Kernel con soporte remoteproc configurado
#################################################################

set -e  # Salir si hay error

# =====================================================================
# Configuración
# =====================================================================

FIRMWARE_BIN="${1:-m4_firmware.bin}"
REMOTEPROC_PATH="/sys/class/remoteproc"
M4_CORE_NAME="m4fss0_core0"  # Nombre del core M4 en remoteproc

# Directorio de trabajo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/m4_fw_load.log"

# =====================================================================
# Funciones
# =====================================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

error() {
    echo "[ERROR] $*" | tee -a "$LOG_FILE" >&2
    exit 1
}

# =====================================================================
# Validaciones previas
# =====================================================================

log "=== Iniciando carga de firmware M4 ==="

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
    error "Este script debe ejecutarse como root (usa: sudo $0)"
fi

# Verificar que el firmware existe
if [[ ! -f "$FIRMWARE_BIN" ]]; then
    error "Archivo de firmware no encontrado: $FIRMWARE_BIN"
fi

# Verificar tamaño del firmware
FIRMWARE_SIZE=$(stat -c%s "$FIRMWARE_BIN")
log "Tamaño del firmware: $FIRMWARE_SIZE bytes"

if [[ $FIRMWARE_SIZE -gt 262144 ]]; then  # 256 KB
    error "Firmware muy grande (max 256 KB). Tamaño actual: $FIRMWARE_SIZE bytes"
fi

# =====================================================================
# Localizar el core M4 en remoteproc
# =====================================================================

log "Buscando core M4 en remoteproc..."

if [[ ! -d "$REMOTEPROC_PATH" ]]; then
    error "remoteproc no disponible en $REMOTEPROC_PATH"
fi

# Buscar el M4 core
M4_REMOTEPROC=""
for rproc_dir in "$REMOTEPROC_PATH"/remoteproc*/; do
    if [[ -f "${rproc_dir}name" ]]; then
        RPROC_NAME=$(cat "${rproc_dir}name")
        if [[ "$RPROC_NAME" == "$M4_CORE_NAME" ]]; then
            M4_REMOTEPROC="${rproc_dir%/}"
            break
        fi
    fi
done

if [[ -z "$M4_REMOTEPROC" ]]; then
    error "No se encontró el core M4 ($M4_CORE_NAME) en remoteproc"
fi

log "Core M4 encontrado en: $M4_REMOTEPROC"

# =====================================================================
# Detener el core M4 si está ejecutándose
# =====================================================================

STATE_FILE="$M4_REMOTEPROC/state"
CURRENT_STATE=$(cat "$STATE_FILE")

log "Estado actual del M4: $CURRENT_STATE"

if [[ "$CURRENT_STATE" == "running" ]]; then
    log "Deteniendo el M4..."
    echo "stop" > "$STATE_FILE"
    sleep 1
    CURRENT_STATE=$(cat "$STATE_FILE")
    if [[ "$CURRENT_STATE" != "stopped" ]]; then
        error "No se pudo detener el M4. Estado: $CURRENT_STATE"
    fi
    log "✅ M4 detenido"
fi

# =====================================================================
# Copiar el firmware
# =====================================================================

FIRMWARE_PATH="$M4_REMOTEPROC/firmware"

log "Copiando firmware a remoteproc..."
cp "$FIRMWARE_BIN" "$FIRMWARE_PATH"

# Verificar que se copió correctamente
if [[ ! -f "$FIRMWARE_PATH" ]]; then
    error "No se pudo copiar el firmware"
fi

log "✅ Firmware copiado"

# =====================================================================
# Iniciar el core M4
# =====================================================================

log "Iniciando el M4..."
echo "start" > "$STATE_FILE"
sleep 2

CURRENT_STATE=$(cat "$STATE_FILE")
log "Estado después de start: $CURRENT_STATE"

if [[ "$CURRENT_STATE" != "running" ]]; then
    error "No se pudo iniciar el M4. Estado: $CURRENT_STATE"
fi

log "✅ M4 iniciado correctamente"

# =====================================================================
# Verificación final
# =====================================================================

log "Esperando 3 segundos para estabilización..."
sleep 3

# Intentar leer logs del remoteproc
if [[ -f "$M4_REMOTEPROC/trace0" ]]; then
    log "=== Logs del M4 ==="
    cat "$M4_REMOTEPROC/trace0" | tail -20 | tee -a "$LOG_FILE"
fi

# =====================================================================
# Verificar RPMsg
# =====================================================================

log "Verificando canal RPMsg..."

RPMSG_DEVICES=$(ls /dev/rpmsg* 2>/dev/null || echo "")

if [[ -z "$RPMSG_DEVICES" ]]; then
    log "⚠️  ADVERTENCIA: No se detectaron dispositivos RPMsg"
    log "El canal RPMsg podría no estar disponible aún"
else
    log "✅ Dispositivos RPMsg detectados: $RPMSG_DEVICES"
fi

# =====================================================================
# Éxito
# =====================================================================

log ""
log "╔══════════════════════════════════════════════════╗"
log "║   ✅ FIRMWARE M4 CARGADO EXITOSAMENTE         ║"
log "║   Firmware: $FIRMWARE_BIN"
log "║   Tamaño: $FIRMWARE_SIZE bytes"
log "║   Estado: $CURRENT_STATE"
log "╚══════════════════════════════════════════════════╝"
log ""

exit 0
