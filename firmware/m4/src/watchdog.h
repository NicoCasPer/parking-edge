#ifndef WATCHDOG_H
#define WATCHDOG_H

#include <stdint.h>

/* Declaraciones estándar para el Perro Guardián del Cortex-M4 */
void watchdog_init(void);
uint8_t watchdog_is_initialized(void);
void watchdog_feed(void);

#endif /* WATCHDOG_H */