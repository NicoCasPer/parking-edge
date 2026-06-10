#!/usr/bin/env bash
# install.sh — Instalación completa de parking-edge en BeaglePlay / Ubuntu ARM.
# Ejecutar como root: sudo bash scripts/install.sh

set -euo pipefail

INSTALL_DIR="/opt/parking-edge"
DATA_DIR="/var/lib/parking"
LOG_DIR="/var/log/parking"
SERVICE_USER="parking"
PYTHON="python3"

# ── Color helpers ─────────────────────────────────────────────────────────────
ok()   { echo "[✓] $*"; }
info() { echo "[→] $*"; }
err()  { echo "[✗] $*" >&2; exit 1; }

check_root() {
    [[ $EUID -eq 0 ]] || err "Este script debe ejecutarse como root (sudo)."
}

# ── 1. Dependencias del sistema ───────────────────────────────────────────────
install_system_deps() {
    info "Instalando dependencias del sistema..."
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        mosquitto mosquitto-clients \
        sqlite3 \
        tesseract-ocr \
        libopencv-dev \
        ntp \
        curl wget
    ok "Dependencias del sistema instaladas."
}

# ── 2. Usuario de servicio ────────────────────────────────────────────────────
create_service_user() {
    if ! id "$SERVICE_USER" &>/dev/null; then
        info "Creando usuario '$SERVICE_USER'..."
        useradd --system --no-create-home \
                --shell /usr/sbin/nologin \
                --groups dialout,video \
                "$SERVICE_USER"
        ok "Usuario '$SERVICE_USER' creado."
    else
        info "Usuario '$SERVICE_USER' ya existe."
    fi
}

# ── 3. Directorios ────────────────────────────────────────────────────────────
setup_dirs() {
    info "Creando directorios..."
    install -d -m 0755 "$INSTALL_DIR"
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR"
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$LOG_DIR"
    install -d -m 1777 /tmp/parking_captures
    ok "Directorios creados."
}

# ── 4. Código fuente ──────────────────────────────────────────────────────────
deploy_code() {
    info "Copiando código fuente a $INSTALL_DIR..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
    rsync -a --delete \
          --exclude='.git' \
          --exclude='__pycache__' \
          --exclude='*.pyc' \
          --exclude='.DS_Store' \
          --exclude='venv' \
          --exclude='*.egg-info' \
          "$PROJECT_DIR/" "$INSTALL_DIR/"
    ok "Código desplegado."
}

# ── 5. Entorno virtual Python ─────────────────────────────────────────────────
setup_python_env() {
    info "Creando entorno virtual Python..."
    $PYTHON -m venv "$INSTALL_DIR/venv"
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
    ok "Entorno Python listo."

    # Actualizar ExecStart de los servicios para usar el venv
    VENV_PYTHON="$INSTALL_DIR/venv/bin/python3"
    for f in "$INSTALL_DIR"/systemd/*.service; do
        sed -i "s|/usr/bin/python3|$VENV_PYTHON|g" "$f"
    done
}

# ── 6. Configuración de entorno ───────────────────────────────────────────────
setup_env() {
    local env_file="$INSTALL_DIR/config/app.env"
    if [[ ! -f "$env_file" ]]; then
        info "Creando app.env desde plantilla..."
        cp "$INSTALL_DIR/config/app.env.example" "$env_file"
        chmod 0640 "$env_file"
        chown root:"$SERVICE_USER" "$env_file"
        ok "app.env creado. EDÍTALO antes de iniciar los servicios."
    else
        info "app.env ya existe — no se sobreescribe."
    fi
}

# ── 7. Base de datos ──────────────────────────────────────────────────────────
init_database() {
    info "Inicializando base de datos..."
    local db="$DATA_DIR/parking.db"
    if [[ ! -f "$db" ]]; then
        sqlite3 "$db" < "$INSTALL_DIR/db/migrations/001_initial.sql"
        chown "$SERVICE_USER":"$SERVICE_USER" "$db"
        ok "Base de datos creada en $db."
    else
        info "Base de datos ya existe — omitiendo."
    fi
}

# ── 8. Reglas udev ────────────────────────────────────────────────────────────
install_udev_rules() {
    local rules_src="$INSTALL_DIR/config/99-parking-system.rules"
    if [[ -f "$rules_src" ]]; then
        info "Instalando reglas udev..."
        cp "$rules_src" /etc/udev/rules.d/99-parking-system.rules
        udevadm control --reload-rules
        udevadm trigger
        ok "Reglas udev instaladas."
    else
        info "Sin reglas udev personalizadas — omitiendo."
    fi
}

# ── 9. Servicios systemd ──────────────────────────────────────────────────────
install_systemd_services() {
    info "Instalando servicios systemd..."
    for f in "$INSTALL_DIR"/systemd/*.service; do
        name="$(basename "$f")"
        cp "$f" "/etc/systemd/system/$name"
    done
    systemctl daemon-reload

    local services=(
        mosquitto.service
        database.service
        m4-firmware.service
        hardware-controller.service
        vision-service.service
        access-orchestrator.service
        payment-integration.service
        connectivity-service.service
        web-dashboard.service
    )
    for svc in "${services[@]}"; do
        systemctl enable "$svc" 2>/dev/null || true
    done
    ok "Servicios systemd instalados y habilitados."
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    check_root
    echo "========================================="
    echo " parking-edge — Instalación"
    echo "========================================="
    install_system_deps
    create_service_user
    setup_dirs
    deploy_code
    setup_python_env
    setup_env
    init_database
    install_udev_rules
    install_systemd_services

    echo ""
    echo "========================================="
    ok "Instalación completada."
    echo ""
    echo "Próximos pasos:"
    echo "  1. Editar /opt/parking-edge/config/app.env con credenciales reales."
    echo "  2. Cargar firmware M4: sudo systemctl start m4-firmware.service"
    echo "  3. Iniciar todos los servicios: sudo systemctl start parking-edge.target"
    echo "  4. Verificar: sudo bash /opt/parking-edge/scripts/healthcheck.sh"
    echo "========================================="
}

main "$@"
