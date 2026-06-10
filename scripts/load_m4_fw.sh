#!/usr/bin/env bash
# load_m4_fw.sh — Carga el firmware M4F en el BeaglePlay vía remoteproc.
# Ejecutar como root (systemd m4-firmware.service lo hace automáticamente).

set -euo pipefail

FIRMWARE_BIN="${M4_FIRMWARE_PATH:-/opt/parking-edge/firmware/m4/bin/parking_m4.out}"
REMOTEPROC_DIR="/sys/class/remoteproc/remoteproc0"
FIRMWARE_DEST_DIR="/lib/firmware"
FIRMWARE_NAME="parking_m4.out"
MAX_WAIT=10   # segundos máximos esperando estado "running"

ok()   { echo "[✓] $*"; }
info() { echo "[→] $*"; }
err()  { echo "[✗] $*" >&2; exit 1; }

# ── Verificar privilegios ─────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || err "Se requiere root para controlar remoteproc."

# ── Verificar binario ─────────────────────────────────────────────────────────
[[ -f "$FIRMWARE_BIN" ]] || err "Binario de firmware no encontrado: $FIRMWARE_BIN"
[[ -d "$REMOTEPROC_DIR" ]] || err "remoteproc0 no encontrado. ¿El kernel soporta remoteproc?"

# ── Detener firmware anterior si está corriendo ───────────────────────────────
current_state=$(cat "$REMOTEPROC_DIR/state" 2>/dev/null || echo "unknown")
if [[ "$current_state" == "running" ]]; then
    info "Deteniendo firmware M4 anterior..."
    echo "stop" > "$REMOTEPROC_DIR/state"
    sleep 1
fi

# ── Copiar binario a /lib/firmware (remoteproc busca aquí) ───────────────────
info "Copiando firmware a $FIRMWARE_DEST_DIR/$FIRMWARE_NAME..."
cp "$FIRMWARE_BIN" "$FIRMWARE_DEST_DIR/$FIRMWARE_NAME"
sync

# ── Configurar y arrancar ─────────────────────────────────────────────────────
info "Configurando nombre del firmware..."
echo "$FIRMWARE_NAME" > "$REMOTEPROC_DIR/firmware"

info "Iniciando firmware M4..."
echo "start" > "$REMOTEPROC_DIR/state"

# ── Esperar confirmación ──────────────────────────────────────────────────────
for i in $(seq 1 $MAX_WAIT); do
    state=$(cat "$REMOTEPROC_DIR/state" 2>/dev/null || echo "unknown")
    if [[ "$state" == "running" ]]; then
        ok "Firmware M4 en ejecución (estado: $state)."
        exit 0
    fi
    sleep 1
done

# Si llegamos aquí, algo falló
state=$(cat "$REMOTEPROC_DIR/state" 2>/dev/null || echo "unknown")
err "Firmware M4 no arrancó en ${MAX_WAIT}s. Estado actual: $state"
