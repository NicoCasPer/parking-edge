#!/usr/bin/env bash
#
# run_demo.sh — Levanta TODO el sistema parking-edge en un solo terminal (sin systemd).
#
# Pensado para demos y desarrollo. Arranca el broker, prepara la base de datos y
# lanza los servicios en orden, todos con config/app.env cargado. Ctrl+C detiene
# todo limpiamente.
#
# Uso:
#   bash scripts/run_demo.sh
#
# Variables opcionales (override desde la línea de comandos):
#   UART_DEVICE=/dev/ttyS0  bash scripts/run_demo.sh   # puerto UART hacia el ESP32
#   WITH_PAYMENTS=0         bash scripts/run_demo.sh   # no arrancar pagos
#   WITH_CONNECTIVITY=1     bash scripts/run_demo.sh   # arrancar telemetría
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── Entorno ──────────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
[[ -f venv/bin/activate ]] && source venv/bin/activate
if [[ -f config/app.env ]]; then
  set -a; source config/app.env; set +a    # carga app.env en TODOS los servicios
fi
export PYTHONPATH="$ROOT"

UART_DEVICE="${UART_DEVICE:-/dev/ttyS2}"
DB_PATH="${DB_PATH:-/var/lib/parking/parking.db}"
WITH_PAYMENTS="${WITH_PAYMENTS:-1}"        # 1 = payment-integration + mock server
WITH_CONNECTIVITY="${WITH_CONNECTIVITY:-0}"
LOG_DIR="${LOG_DIR:-/tmp/parking_logs}"
mkdir -p "$LOG_DIR"

PIDS=()

cleanup() {
  echo
  echo "[run_demo] Deteniendo servicios..."
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  echo "[run_demo] Listo."
}
trap cleanup INT TERM EXIT

start() {   # start <nombre> <comando...>
  local name="$1"; shift
  echo "[run_demo] -> $name"
  ( "$@" ) >"$LOG_DIR/$name.log" 2>&1 &
  PIDS+=("$!")
}

# ── 1. Broker MQTT ───────────────────────────────────────────────────────────
if ! pgrep -x mosquitto >/dev/null 2>&1; then
  echo "[run_demo] Arrancando mosquitto..."
  sudo systemctl start mosquitto 2>/dev/null || mosquitto -d || {
    echo "[run_demo] ERROR: no se pudo arrancar mosquitto. Abortando." >&2; exit 1; }
  sleep 1
fi

# ── 2. Base de datos (crear + migrar + seed solo si no existe) ────────────────
if [[ ! -f "$DB_PATH" ]]; then
  echo "[run_demo] Inicializando base de datos en $DB_PATH..."
  mkdir -p "$(dirname "$DB_PATH")" 2>/dev/null \
    || sudo install -d -m0750 -o "$(id -un)" -g "$(id -gn)" "$(dirname "$DB_PATH")"
  sqlite3 "$DB_PATH" < db/migrations/001_initial.sql
  sqlite3 "$DB_PATH" < db/seeds/simulation_data.sql
fi

# ── 3. Servicios (en orden de dependencia) ───────────────────────────────────
start hardware-controller env UART_DEVICE="$UART_DEVICE" python -m services.hardware_controller.app.main
sleep 1
start vision-service      python -m services.vision_service.app.main
start access-orchestrator python -m services.access_orchestrator.app.main

if [[ "$WITH_PAYMENTS" == "1" ]]; then
  start mock-payment-server python -m services.mock_payment_server.app
  start payment-integration python -m services.payment_integration.app.main
fi
if [[ "$WITH_CONNECTIVITY" == "1" ]]; then
  start connectivity-service python -m services.connectivity_service.app.main
fi

start web-dashboard python -m web_dashboard.backend.app

echo
echo "[run_demo] Todo arriba ($(date +%H:%M:%S))."
echo "[run_demo]   Dashboard : http://<ip-de-la-beagle>:8080"
echo "[run_demo]   Logs      : $LOG_DIR/   (tail -F $LOG_DIR/*.log)"
echo "[run_demo]   UART      : $UART_DEVICE"
echo "[run_demo] Ctrl+C para detener TODO."
wait
