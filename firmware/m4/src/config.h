/*
 * config.h
 * Configuración centralizada para el proyecto de Parqueadero Inteligente
 *
 * Incluir este archivo en todos los módulos que necesiten constantes
 * compartidas.
 */

#ifndef CONFIG_H
#define CONFIG_H

/* =========================================================================
 * CONFIGURACIÓN DEL SENSOR ULTRASONIDO
 * ========================================================================= */

/** Puerto del HC-SR04: MCU_GPIO0_0 */
#define TRIGGER_PIN_NUM         (0U)

/** Puerto de entrada del HC-SR04: MCU_GPIO0_2 */
#define ECHO_PIN_NUM            (2U)

/** Umbral de distancia para detectar presencia (en cm) */
#define DISTANCE_THRESHOLD_CM   (50U)

/** Distancia máxima considerada válida (en cm) */
#define MAX_DISTANCE_CM         (400U)

/** Período de muestreo del sensor (en ms) */
#define SENSOR_SAMPLE_PERIOD_MS (60U)

/** Debounce temporal mínimo entre detecciones (en ms) */
#define DETECTION_DEBOUNCE_MS   (500U)

/** Número de lecturas consecutivas para confirmar detección */
#define DEBOUNCE_READINGS       (3U)

/* =========================================================================
 * CONFIGURACIÓN DEL SERVO/BARRERA
 * ========================================================================= */

/** Puerto del servo/barrera: MCU_GPIO0_8 */
#define SERVO_BARRIER_PIN_NUM   (8U)

/** Dirección base del GPIO MCU0 */
#define MCU_GPIO0_BASE_ADDR     (0x04201000U)

/* =========================================================================
 * CONFIGURACIÓN DE RPMsg
 * ========================================================================= */

/** Endpoint RPMsg del M4 */
#define RPMSG_ENDPOINT          (14U)

/** Core destino: Linux A53 */
#define LINUX_CORE_ID           (IPC_NOTIFY_CLIENT_ID_LINUX_0)

/** Tamaño del buffer de recepción RPMsg */
#define RPMSG_RX_BUF_SIZE       (64U)

/** Timeout de envío RPMsg (en ms) */
#define RPMSG_SEND_TIMEOUT_MS   (1000U)

/** Timeout de recepción RPMsg (en ms) */
#define RPMSG_RECV_TIMEOUT_MS   (5000U)

/* =========================================================================
 * CONFIGURACIÓN DEL WATCHDOG
 * ========================================================================= */

/** Timeout sin heartbeat antes de cierre de emergencia (en ms) */
#define HEARTBEAT_TIMEOUT_MS    (5000U)

/* =========================================================================
 * CONFIGURACIÓN DE DEBUG
 * ========================================================================= */

/** Habilitar logs detallados de debug */
#define DEBUG_ENABLED           (1)

/** Habilitar logs del sensor */
#define DEBUG_SENSOR            (1)

/** Habilitar logs de RPMsg */
#define DEBUG_RPMSG             (1)

/** Habilitar logs del watchdog */
#define DEBUG_WATCHDOG          (1)

/* =========================================================================
 * CONFIGURACIÓN DE STACK/MEMORIA (FreeRTOS)
 * ========================================================================= */

/** Stack size para tarea del sensor (en palabras) */
#define SENSOR_TASK_STACK_SIZE  (512)

/** Stack size para tarea de RPMsg (en palabras) */
#define RPMSG_TASK_STACK_SIZE   (768)

/** Prioridad de la tarea del sensor */
#define SENSOR_TASK_PRIORITY    (2)

/** Prioridad de la tarea de RPMsg */
#define RPMSG_TASK_PRIORITY     (3)

/* =========================================================================
 * VERSIÓN DEL FIRMWARE
 * ========================================================================= */

#define FW_VERSION_MAJOR        (1)
#define FW_VERSION_MINOR        (0)
#define FW_VERSION_PATCH        (0)
#define FW_BUILD_DATE           (__DATE__)
#define FW_BUILD_TIME           (__TIME__)

/* =========================================================================
 * MACROS ÚTILES
 * ========================================================================= */

/** Concatenación de versión */
#define FW_VERSION_STR \
    "v" \
    #FW_VERSION_MAJOR "." \
    #FW_VERSION_MINOR "." \
    #FW_VERSION_PATCH

#endif /* CONFIG_H */
