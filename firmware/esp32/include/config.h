/*
 * config.h — Configuración centralizada del firmware ESP32 del parqueadero.
 *
 * Espejo de firmware/m4/src/config.h: se conservan los MISMOS nombres y valores
 * de los umbrales/tiempos para mantener idéntico el comportamiento del M4.
 * Lo único que cambia son los pines (ahora del ESP32) y el transporte (UART).
 */

#ifndef CONFIG_H
#define CONFIG_H

/* =========================================================================
 * PINES — ESP32 WROOM-32 (DevKit v1)
 * ========================================================================= */

/** HC-SR04 TRIGGER — salida digital */
#define TRIGGER_PIN_NUM         (5)

/** HC-SR04 ECHO — entrada. REQUIERE divisor de voltaje 5V->3.3V (ver README) */
#define ECHO_PIN_NUM            (18)

/** Barrera/servo — salida digital. LOW = cerrada (estado seguro al arranque) */
#define SERVO_BARRIER_PIN_NUM   (19)

/** UART2 hacia la BeaglePlay (RX2/TX2). Cableado CRUZADO: TX2->RX_beagle */
#define UART_BEAGLE_RX_PIN      (16)
#define UART_BEAGLE_TX_PIN      (17)
#define UART_BEAGLE_BAUD        (115200)

/* =========================================================================
 * SENSOR ULTRASONIDO (idéntico al M4)
 * ========================================================================= */

/** Umbral de distancia para detectar presencia (cm) */
#define DISTANCE_THRESHOLD_CM   (50U)

/** Distancia máxima considerada válida (cm) */
#define MAX_DISTANCE_CM         (400U)

/** Período de muestreo del sensor (ms) */
#define SENSOR_SAMPLE_PERIOD_MS (60U)

/** Debounce temporal mínimo entre detecciones (ms) */
#define DETECTION_DEBOUNCE_MS   (500U)

/** Lecturas consecutivas bajo umbral para confirmar detección */
#define DEBOUNCE_READINGS       (3U)

/** Valor sentinela de error / fuera de rango */
#define SENSOR_ERROR_CM         (999U)

/* =========================================================================
 * WATCHDOG
 * ========================================================================= */

/** Timeout sin HEARTBEAT antes del cierre de emergencia (ms) */
#define HEARTBEAT_TIMEOUT_MS    (5000U)

/* =========================================================================
 * TAREAS FreeRTOS (en ESP32 el stack se mide en BYTES)
 * ========================================================================= */

#define SENSOR_TASK_STACK       (4096)
#define UART_TASK_STACK         (4096)
#define SENSOR_TASK_PRIORITY    (2)
#define UART_TASK_PRIORITY      (3)

/* =========================================================================
 * VERSIÓN
 * ========================================================================= */

#define FW_VERSION_STR          "v1.0.0-esp32"

#endif /* CONFIG_H */
