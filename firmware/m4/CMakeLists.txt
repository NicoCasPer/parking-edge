cmake_minimum_required(VERSION 3.15)

# Proyecto: Firmware del M4 para BeaglePlay - Parqueadero Inteligente
project(BeaglePlay_M4_Firmware C)

# =====================================================================
# Configuración del compilador
# =====================================================================

set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_C_FLAGS_INIT "-mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wall -Wextra -O2 -g3")

# =====================================================================
# Directorios
# =====================================================================

set(SDK_PATH "/opt/ti/mcu_plus_sdk"
    CACHE PATH "Path to TI MCU+ SDK AM62x")
set(FREERTOS_PATH "/opt/freertos"
    CACHE PATH "Path to FreeRTOS")

# =====================================================================
# Inclusión de directorios
# =====================================================================

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${SDK_PATH}/source/drivers/gpio/v0
    ${SDK_PATH}/source/drivers/gpio/v0/am62x
    ${SDK_PATH}/source/drivers/ipc_rpmsg
    ${SDK_PATH}/source/kernel/dpl
    ${SDK_PATH}/source/kernel/dpl/freertos
    ${FREERTOS_PATH}/include
)

# =====================================================================
# Fuentes del firmware
# =====================================================================

set(FIRMWARE_SOURCES
    main.c
    sensor_driver.c
    rpmsg_interface.c
    watchdog.c
)

# =====================================================================
# Crear ejecutable
# =====================================================================

add_executable(m4_firmware.elf ${FIRMWARE_SOURCES})

# --- SOLUCIÓN A LOS 0 BYTES: FLAGS DEL ENLAZADOR (LINKER) ---
# Se inyecta el script de memoria (.cmd) del SDK v12 y se evita el inicio genérico
target_link_options(m4_firmware.elf PRIVATE
    -nostartfiles
    -Wl,-T,${SDK_PATH}/source/kernel/freertos/config/am62x/m4f/linker.cmd
    -Wl,--gc-sections
)

target_link_libraries(m4_firmware.elf
    # Librerías del SDK de TI (ajustar según instalación)
    -L${SDK_PATH}/lib
    -L${FREERTOS_PATH}/lib
)

# =====================================================================
# Opciones de post-build
# =====================================================================

# Generar .bin desde .elf
add_custom_command(TARGET m4_firmware.elf POST_BUILD
    COMMAND arm-none-eabi-objcopy -O binary
            m4_firmware.elf m4_firmware.bin
    COMMENT "Generando m4_firmware.bin"
)

# Generar .hex desde .elf
add_custom_command(TARGET m4_firmware.elf POST_BUILD
    COMMAND arm-none-eabi-objcopy -O ihex
            m4_firmware.elf m4_firmware.hex
    COMMENT "Generando m4_firmware.hex"
)

# Generar mapa de memoria
add_custom_command(TARGET m4_firmware.elf POST_BUILD
    COMMAND arm-none-eabi-nm -n m4_firmware.elf > m4_firmware.map
    COMMENT "Generando m4_firmware.map"
)

# =====================================================================
# Información de compilación
# =====================================================================

message(STATUS "=== Configuración del Firmware M4 ===")
message(STATUS "Compilador: ${CMAKE_C_COMPILER}")
message(STATUS "SDK Path: ${SDK_PATH}")
message(STATUS "FreeRTOS Path: ${FREERTOS_PATH}")
message(STATUS "Flags: ${CMAKE_C_FLAGS}")
