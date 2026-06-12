#ifndef BARRIER_H
#define BARRIER_H

#include <stdbool.h>

/*
 * barrier.h — Control de la barrera/servo (GPIO digital).
 *
 * El acceso al GPIO está protegido por un mutex interno porque lo accionan
 * varias tareas: el listener UART (OPEN/CLOSE/STOP) y el watchdog.
 * LOW = barrera cerrada (estado seguro). HIGH = barrera abierta.
 */

/** Inicializa el GPIO de la barrera (LOW) y crea el mutex. */
void barrier_init(void);

/** Abre la barrera (GPIO HIGH). Devuelve true si pudo tomar el mutex. */
bool barrier_open(void);

/** Cierra la barrera (GPIO LOW). Devuelve true si pudo tomar el mutex. */
bool barrier_close(void);

#endif /* BARRIER_H */
