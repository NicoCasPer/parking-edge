# Makefile para compilación del firmware M4 - BeaglePlay
# Alternativa a CMake para compilación rápida

.PHONY: all clean build upload test help

# =====================================================================
# Configuración
# =====================================================================

TOOLCHAIN_PREFIX = arm-none-eabi-
CC = $(TOOLCHAIN_PREFIX)gcc
OBJCOPY = $(TOOLCHAIN_PREFIX)objcopy
NM = $(TOOLCHAIN_PREFIX)nm
SIZE = $(TOOLCHAIN_PREFIX)size

# Directorio de SDK de TI (ajustar según tu instalación)
SDK_PATH ?= /opt/ti/mcu_plus_sdk
FREERTOS_PATH ?= /opt/freertos

# Archivos fuente
SOURCES = src/main.c src/sensor_driver.c scr/rpmsg_interface.c scr/watchdog.c
OBJECTS = $(SOURCES:.c=.o)
TARGET = m4_firmware.elf
TARGET_BIN = m4_firmware.bin
TARGET_HEX = m4_firmware.hex
TARGET_MAP = m4_firmware.map

# Flags de compilación
CFLAGS = -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16
CFLAGS += -Wall -Wextra -pedantic -O2 -g3
CFLAGS += -I. 
CFLAGS += -I$(SDK_PATH)/source/drivers/gpio/v0
CFLAGS += -I$(SDK_PATH)/source/drivers/gpio/v0/am62x
CFLAGS += -I$(SDK_PATH)/source/drivers/ipc_rpmsg
CFLAGS += -I$(SDK_PATH)/source/kernel/dpl
CFLAGS += -I$(SDK_PATH)/source/kernel/dpl/freertos
CFLAGS += -I$(FREERTOS_PATH)/include

# Flags de linkeo
LDFLAGS = -nostartfiles -Wl,--gc-sections

# =====================================================================
# Objetivos
# =====================================================================

all: build

build: $(TARGET_BIN) $(TARGET_HEX) $(TARGET_MAP)
	@echo ""
	@echo "✅ Compilación completada:"
	@$(SIZE) $(TARGET)
	@echo ""
	@echo "Archivos generados:"
	@ls -lh $(TARGET) $(TARGET_BIN) $(TARGET_HEX) $(TARGET_MAP)

$(TARGET): $(OBJECTS)
	@echo "🔗 Enlazando: $@"
	@$(CC) $(LDFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	@echo "📝 Compilando: $<"
	@$(CC) $(CFLAGS) -c $< -o $@

$(TARGET_BIN): $(TARGET)
	@echo "📦 Generando binario: $@"
	@$(OBJCOPY) -O binary $< $@

$(TARGET_HEX): $(TARGET)
	@echo "📦 Generando hex: $@"
	@$(OBJCOPY) -O ihex $< $@

$(TARGET_MAP): $(TARGET)
	@echo "🗺️  Generando mapa de memoria: $@"
	@$(NM) -n $< > $@

clean:
	@echo "🧹 Limpiando archivos compilados..."
	@rm -f $(OBJECTS) $(TARGET) $(TARGET_BIN) $(TARGET_HEX) $(TARGET_MAP)
	@echo "✅ Limpieza completada"

upload: $(TARGET_BIN)
	@echo "📤 Cargando firmware en BeaglePlay..."
	@sudo ../scripts/load_m4_fw.sh $(TARGET_BIN)

test: build
	@echo "🧪 Ejecutando verificaciones básicas..."
	@echo "Tamaño del firmware: $$(stat -f%z $(TARGET_BIN) 2>/dev/null || stat -c%s $(TARGET_BIN)) bytes"
	@echo "Símbolos en el firmware:"
	@$(NM) -C $(TARGET) | head -20

help:
	@echo "Makefile - Firmware M4 BeaglePlay"
	@echo ""
	@echo "Objetivos:"
	@echo "  make build    - Compilar el firmware (por defecto)"
	@echo "  make clean    - Limpiar archivos compilados"
	@echo "  make upload   - Cargar el firmware en BeaglePlay"
	@echo "  make test     - Ejecutar verificaciones básicas"
	@echo "  make help     - Mostrar esta ayuda"
	@echo ""
	@echo "Variables:"
	@echo "  SDK_PATH      - Ruta al SDK de TI (por defecto: $(SDK_PATH))"
	@echo "  FREERTOS_PATH - Ruta a FreeRTOS (por defecto: $(FREERTOS_PATH))"
