#ifndef BARRIER_H
#define BARRIER_H

#include <stdbool.h>

/*
 * barrier.h — Control de la barrera como servo (PWM/LEDC), movimiento fijo de 90°.
 *
 * El servo se protege con un mutex interno porque lo accionan varias tareas:
 * el listener UART (OPEN/CLOSE/STOP) y el watchdog.
 *   CLOSE -> 0°  (reposo, estado seguro al arranque)
 *   OPEN  -> 90° (barrera levantada)
 */

/** Inicializa el servo (LEDC), lo deja a 0° y crea el mutex. */
void barrier_init(void);

/** Abre la barrera: servo a 90°. Devuelve true si pudo tomar el mutex. */
bool barrier_open(void);

/** Cierra la barrera: servo a 0°. Devuelve true si pudo tomar el mutex. */
bool barrier_close(void);

#endif /* BARRIER_H */
