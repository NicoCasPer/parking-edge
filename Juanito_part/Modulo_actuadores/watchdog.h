#ifndef WATCHDOG_H
#define WATCHDOG_H

#include <stdint.h>
#include "sensor_driver.h"   /* para MCU_GPIO0_BASE_ADDR y SERVO_BARRIER_PIN_NUM */

/*
 * watchdog.h
 * Watchdog de software que cierra la barrera si Linux (A53) deja de
 * enviar heartbeats por más de HEARTBEAT_TIMEOUT_MS milisegundos.
 *
 * El pin de la barrera (SERVO_BARRIER_PIN_NUM) está definido en sensor_driver.h
 * y corresponde a MCU_GPIO0_8 (J5 pin 9) del header MCU de la BeaglePlay.
 */

/** Timeout sin heartbeat antes de activar el cierre de emergencia (ms) */
#define HEARTBEAT_TIMEOUT_MS    (5000U)

/** Inicializa el timer FreeRTOS que actúa como watchdog (segura para llamar múltiples veces) */
void watchdog_init(void);

/** Retorna 1 si el watchdog está inicializado correctamente, 0 en caso contrario */
uint8_t watchdog_is_initialized(void);

/** Alimenta al watchdog (debe llamarse cada vez que llega un "HEARTBEAT") */
void watchdog_feed(void);

#endif /* WATCHDOG_H */
