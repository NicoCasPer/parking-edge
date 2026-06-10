#!/bin/bash

#################################################################
# test_rpmsg.sh
# Script simple para testear comunicación RPMsg
#
# Envía mensajes de prueba al M4 y verifica respuestas
#################################################################

set -e

RPMSG_DEVICE="${1:-/dev/rpmsg0}"
TEST_MESSAGE="HEARTBEAT"
OUTPUT_FILE="/tmp/rpmsg_test.log"

# =====================================================================

log() {
    echo "[$(date +'%H:%M:%S')] $*" | tee -a "$OUTPUT_FILE"
}

error() {
    echo "[ERROR] $*" | tee -a "$OUTPUT_FILE" >&2
    exit 1
}

# =====================================================================

log "=== Test de RPMsg ==="

if [[ ! -e "$RPMSG_DEVICE" ]]; then
    error "Dispositivo RPMsg no encontrado: $RPMSG_DEVICE"
fi

log "Dispositivo RPMsg: $RPMSG_DEVICE"

# =====================================================================

log "Test 1: Enviar HEARTBEAT"
echo "$TEST_MESSAGE" > "$RPMSG_DEVICE"
log "✅ Mensaje enviado"

sleep 1

# =====================================================================

log "Test 2: Enviar OPEN"
echo "OPEN" > "$RPMSG_DEVICE"
log "✅ Comando OPEN enviado (barrera debe abrirse)"

sleep 1

# =====================================================================

log "Test 3: Enviar CLOSE"
echo "CLOSE" > "$RPMSG_DEVICE"
log "✅ Comando CLOSE enviado (barrera debe cerrarse)"

sleep 1

# =====================================================================

log "Test 4: Enviar HEARTBEAT múltiples veces"
for i in {1..5}; do
    echo "$TEST_MESSAGE" > "$RPMSG_DEVICE"
    log "  Heartbeat $i enviado"
    sleep 0.5
done

log "✅ Secuencia completada"

# =====================================================================

log ""
log "╔════════════════════════════════════════╗"
log "║  ✅ TEST COMPLETADO                  ║"
log "║  Ver logs: $OUTPUT_FILE"
log "╚════════════════════════════════════════╝"
log ""
