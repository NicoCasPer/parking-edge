#ifndef WATCHDOG_H
#define WATCHDOG_H

/*
 * watchdog.h — Watchdog de software (timer FreeRTOS).
 *
 * Cierra la barrera si la BeaglePlay deja de enviar "HEARTBEAT" durante más de
 * HEARTBEAT_TIMEOUT_MS ms. Equivale a watchdog.c del M4, con la mejora de que
 * además notifica "HARDWARE_FAULT:watchdog_timeout" a Linux por UART.
 */

/** Crea e inicia el timer del watchdog. */
void watchdog_init(void);

/** Reinicia el timer (debe llamarse cada vez que llega un HEARTBEAT). */
void watchdog_feed(void);

#endif /* WATCHDOG_H */
