#!/usr/bin/env bash
# healthcheck.sh — Verifica el estado de todos los servicios y recursos del sistema.
# Uso: bash scripts/healthcheck.sh
#      EXIT 0 = todo OK, EXIT 1 = uno o más fallos.

set -uo pipefail

PASS=0
FAIL=0
WARN=0

# ── Color helpers ─────────────────────────────────────────────────────────────
ok()   { echo "  [✓] $*"; ((PASS++)) || true; }
fail() { echo "  [✗] $*"; ((FAIL++)) || true; }
warn() { echo "  [!] $*"; ((WARN++)) || true; }
section() { echo ""; echo "── $* ──────────────────────────────"; }

# ── Systemd service check ─────────────────────────────────────────────────────
check_service() {
    local name="$1"
    if systemctl is-active --quiet "$name" 2>/dev/null; then
        ok "$name activo"
    else
        fail "$name inactivo ($(systemctl is-active "$name" 2>/dev/null || echo 'desconocido'))"
    fi
}

# ── MQTT broker check ─────────────────────────────────────────────────────────
check_mqtt() {
    if mosquitto_pub -h localhost -t "parking/healthcheck" \
                     -m "ping" -q 0 --quiet 2>/dev/null; then
        ok "MQTT broker accesible (localhost:1883)"
    else
        fail "MQTT broker NO accesible en localhost:1883"
    fi
}

# ── SQLite check ──────────────────────────────────────────────────────────────
check_db() {
    local db="/var/lib/parking/parking.db"
    if [[ -f "$db" ]]; then
        local count
        count=$(sqlite3 "$db" "SELECT COUNT(*) FROM whitelist;" 2>/dev/null || echo "-1")
        if [[ "$count" -ge 0 ]]; then
            ok "Base de datos OK ($count placas en whitelist)"
        else
            fail "Base de datos no responde: $db"
        fi
    else
        fail "Base de datos no encontrada: $db"
    fi
}

# ── RPMsg device check ────────────────────────────────────────────────────────
check_rpmsg() {
    if [[ "${RPMSG_SIMULATED:-false}" == "true" ]]; then
        ok "RPMsg: modo simulado (RPMSG_SIMULATED=true)"
        return
    fi
    local dev="${RPMSG_DEVICE:-/dev/rpmsg0}"
    if [[ -c "$dev" ]]; then
        ok "RPMsg device: $dev"
    else
        warn "RPMsg device no encontrado: $dev (¿M4 cargado?)"
    fi
}

# ── Cámara check ──────────────────────────────────────────────────────────────
check_camera() {
    local idx="${CAMERA_INDEX:-0}"
    if [[ -c "/dev/video${idx}" ]]; then
        ok "Cámara /dev/video${idx} disponible"
    else
        warn "Cámara /dev/video${idx} no encontrada"
    fi
}

# ── Modelo YOLO check ─────────────────────────────────────────────────────────
check_model() {
    local model="${MODEL_PATH:-/opt/parking-edge/Modelo/best_plate_yolo11m_int8.tflite}"
    if [[ -f "$model" ]]; then
        local size
        size=$(du -sh "$model" 2>/dev/null | cut -f1)
        ok "Modelo YOLO: $model ($size)"
    else
        fail "Modelo YOLO no encontrado: $model"
    fi
}

# ── NTP check ─────────────────────────────────────────────────────────────────
check_ntp() {
    if timedatectl status 2>/dev/null | grep -q "synchronized: yes"; then
        ok "NTP sincronizado"
    else
        warn "NTP no sincronizado (los timestamps de eventos pueden ser imprecisos)"
    fi
}

# ── Disco check ───────────────────────────────────────────────────────────────
check_disk() {
    local usage
    usage=$(df /var/lib/parking 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%')
    if [[ -z "$usage" ]]; then
        warn "No se puede verificar uso de disco en /var/lib/parking"
        return
    fi
    if [[ $usage -lt 80 ]]; then
        ok "Disco /var/lib/parking: ${usage}% usado"
    elif [[ $usage -lt 90 ]]; then
        warn "Disco /var/lib/parking: ${usage}% usado (cerca del límite)"
    else
        fail "Disco /var/lib/parking: ${usage}% usado (CRÍTICO)"
    fi
}

# ── Memoria check ─────────────────────────────────────────────────────────────
check_memory() {
    local used_pct
    used_pct=$(free | awk '/^Mem:/ { printf "%.0f", $3/$2*100 }')
    if [[ $used_pct -lt 80 ]]; then
        ok "Memoria: ${used_pct}% usada"
    elif [[ $used_pct -lt 90 ]]; then
        warn "Memoria: ${used_pct}% usada"
    else
        fail "Memoria: ${used_pct}% usada (CRÍTICO)"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
# Cargar variables de entorno si existe app.env
[[ -f /opt/parking-edge/config/app.env ]] && source /opt/parking-edge/config/app.env 2>/dev/null || true

echo "parking-edge — Health Check"
echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

section "Servicios systemd"
check_service "mosquitto.service"
check_service "hardware-controller.service"
check_service "vision-service.service"
check_service "access-orchestrator.service"
check_service "payment-integration.service"
check_service "connectivity-service.service"
check_service "web-dashboard.service"

section "Conectividad"
check_mqtt

section "Almacenamiento"
check_db
check_disk

section "Hardware"
check_rpmsg
check_camera
check_model

section "Sistema"
check_ntp
check_memory

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════"
echo "  Resultado: ${PASS} OK  ${WARN} advertencias  ${FAIL} fallos"
echo "══════════════════════════════════════"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1
