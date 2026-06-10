#!/bin/bash

#################################################################
# debug_system.sh
# Script para debugging del sistema BeaglePlay Parking
#
# Proporciona información del estado del sistema, M4, RPMsg, etc.
#################################################################

# =====================================================================
# Funciones de color
# =====================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
}

print_ok() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# =====================================================================
# Verificaciones
# =====================================================================

print_header "1. INFORMACIÓN DEL SISTEMA"

echo "Board: $(cat /proc/device-tree/model 2>/dev/null || echo 'N/A')"
echo "Kernel: $(uname -r)"
echo "Uptime: $(uptime -p 2>/dev/null || uptime)"
echo "CPU Temp: $(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{printf "%.1f°C", $1/1000}' || echo 'N/A')"

# =====================================================================

print_header "2. ESTADO DEL M4 (remoteproc)"

REMOTEPROC_PATH="/sys/class/remoteproc"

if [[ ! -d "$REMOTEPROC_PATH" ]]; then
    print_error "remoteproc no disponible"
else
    for rproc_dir in "$REMOTEPROC_PATH"/remoteproc*/; do
        if [[ -f "${rproc_dir}name" ]]; then
            RPROC_NAME=$(cat "${rproc_dir}name")
            STATE=$(cat "${rproc_dir}state")
            
            if [[ "$RPROC_NAME" == "m4fss0_core0" ]]; then
                echo "Core M4: $RPROC_NAME"
                if [[ "$STATE" == "running" ]]; then
                    print_ok "Estado: RUNNING"
                else
                    print_error "Estado: $STATE"
                fi
                
                # Uptime del M4
                if [[ -f "${rproc_dir}uptime" ]]; then
                    echo "Uptime: $(cat ${rproc_dir}uptime) segundos"
                fi
                
                # Traces/logs
                if [[ -f "${rproc_dir}trace0" ]]; then
                    echo ""
                    echo "Últimas líneas de log del M4:"
                    tail -5 "${rproc_dir}trace0" | sed 's/^/  /'
                fi
            fi
        fi
    done
fi

# =====================================================================

print_header "3. CANALES RPMsg"

if [[ -d "/dev/rpmsg0" ]] || [[ -c "/dev/rpmsg0" ]]; then
    print_ok "Canal RPMsg disponible"
    ls -la /dev/rpmsg* 2>/dev/null | sed 's/^/  /'
else
    print_warn "Canal RPMsg no detectado"
    echo "Esperando que se inicialice..."
fi

# =====================================================================

print_header "4. SERVICIOS systemd"

echo ""
echo "m4-firmware.service:"
if systemctl is-active --quiet m4-firmware.service; then
    print_ok "ACTIVO"
else
    STATE=$(systemctl is-active m4-firmware.service)
    print_error "INACTIVO ($STATE)"
fi

echo ""
echo "m4-parking-service.service:"
if systemctl is-active --quiet m4-parking-service.service; then
    print_ok "ACTIVO"
else
    STATE=$(systemctl is-active m4-parking-service.service)
    print_error "INACTIVO ($STATE)"
fi

# =====================================================================

print_header "5. LOGS RECIENTES"

echo ""
echo "m4-firmware.service (últimos 10 eventos):"
journalctl -u m4-firmware.service -n 10 --no-pager 2>/dev/null | sed 's/^/  /' || \
    print_warn "No hay logs disponibles"

echo ""
echo "m4-parking-service.service (últimos 10 eventos):"
journalctl -u m4-parking-service.service -n 10 --no-pager 2>/dev/null | sed 's/^/  /' || \
    print_warn "No hay logs disponibles"

# =====================================================================

print_header "6. GPIO DEL MCU"

MCU_GPIO0_PATH="/sys/class/gpio/gpio32"  # GPIO0_0 (TRIGGER)
MCU_GPIO2_PATH="/sys/class/gpio/gpio34"  # GPIO0_2 (ECHO)
MCU_GPIO8_PATH="/sys/class/gpio/gpio40"  # GPIO0_8 (SERVO)

echo "Estados GPIO del M4:"

for GPIO_PATH in "$MCU_GPIO0_PATH" "$MCU_GPIO2_PATH" "$MCU_GPIO8_PATH"; do
    if [[ -d "$GPIO_PATH" ]]; then
        GPIO_NAME=$(basename "$GPIO_PATH")
        GPIO_VALUE=$(cat "$GPIO_PATH/value" 2>/dev/null || echo "?")
        GPIO_DIR=$(cat "$GPIO_PATH/direction" 2>/dev/null || echo "?")
        echo "  $GPIO_NAME: value=$GPIO_VALUE, direction=$GPIO_DIR"
    fi
done

# =====================================================================

print_header "7. VERIFICACIÓN DE INSTALACIÓN"

echo ""
INSTALL_PATH="/opt/parking"

if [[ -d "$INSTALL_PATH" ]]; then
    print_ok "Directorio de instalación existe: $INSTALL_PATH"
    echo ""
    echo "Contenido:"
    ls -la "$INSTALL_PATH/" | tail -n +4 | sed 's/^/  /'
else
    print_error "Directorio no encontrado: $INSTALL_PATH"
fi

# =====================================================================

print_header "8. INFORMACIÓN DE RED"

echo "Interfaces de red:"
ip link show | grep -E '^[0-9]+:' | sed 's/^/  /'

echo ""
echo "Dirección IP:"
hostname -I | sed 's/^/  /'

# =====================================================================

print_header "RESUMEN"

echo ""
echo "Para más información:"
echo "  • Ver logs en vivo: journalctl -u m4-firmware.service -f"
echo "  • Reiniciar M4: sudo systemctl restart m4-firmware.service"
echo "  • Detener M4: sudo systemctl stop m4-firmware.service"
echo "  • Test manual: sudo /opt/parking/scripts/load_m4_fw.sh"
echo ""
