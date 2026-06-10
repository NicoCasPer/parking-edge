#ifndef SENSOR_DRIVER_H
#define SENSOR_DRIVER_H

#include <stdint.h>

/* -------------------------------------------------------------------------
 * PINES DEL HC-SR04 en la BeaglePlay (MCU Domain Header J5)
 *
 *  Pin físico J5-1  -> MCU_GPIO0_0  (TRIGGER) — "MCU_HEADER_PIN_1"
 *  Pin físico J5-3  -> MCU_GPIO0_2  (ECHO)    — "MCU_HEADER_PIN_3"
 *  Pin físico J5-5  -> GND
 *  Pin físico J5-7  -> 3V3 (alimentar HC-SR04 con regulador externo 5V→3V3 en ECHO)
 *
 *  IMPORTANTE: el HC-SR04 opera a 5 V; su pin ECHO entrega 5 V.
 *  Usar un divisor resistivo (1kΩ/2kΩ) o level-shifter antes de conectar
 *  al MCU_GPIO0_2 (3.3 V tolerante).
 *
 *  Base address del GPIO MCU domain (MCU_GPIO0):  0x04201000
 * -------------------------------------------------------------------------
 *
 * PARA EL SERVO / LED DE BARRERA  (ver watchdog.h / rpmsg_interface.h)
 *  Pin físico J5-9  -> MCU_GPIO0_8  (SERVO_BARRIER / LED_BARRERA)
 *
 * Referencia: BeaglePlay schematic, net MCU_GPIO0_x, hoja MCU_HEADER (J5).
 * Referencia SDK: <drivers/gpio.h>  — MCU+ SDK AM62x
 * -------------------------------------------------------------------------
 */

/* Dirección base del banco MCU_GPIO0 */
#define MCU_GPIO0_BASE_ADDR     (0x04201000U)

/* Números de pin dentro del banco MCU_GPIO0 */
#define TRIGGER_PIN_NUM         (0U)   /* MCU_GPIO0_0  — J5 pin 1 */
#define ECHO_PIN_NUM            (2U)   /* MCU_GPIO0_2  — J5 pin 3 */
#define SERVO_BARRIER_PIN_NUM   (8U)   /* MCU_GPIO0_8  — J5 pin 9 */

/* Umbral de detección de presencia */
#define DISTANCE_THRESHOLD_CM   (50U)

/* -------------------------------------------------------------------------
 * API pública
 * -------------------------------------------------------------------------
 */

/** Inicializa los pines TRIGGER y ECHO del HC-SR04 */
void sensor_init(void);

/** Realiza una medición y retorna la distancia en centímetros */
uint32_t medir_distancia_cm(void);

/** Tarea FreeRTOS de monitoreo continuo de presencia */
void vTaskSensorUltrasonido(void *pvParameters);

#endif /* SENSOR_DRIVER_H */