#ifndef SENSOR_H
#define SENSOR_H

#include <stdint.h>

/*
 * sensor.h — Driver del HC-SR04 y tarea de monitoreo de presencia.
 *
 * Replica sensor_driver.c del M4: medición trigger 10us + ancho de eco,
 * distancia = us/58, doble debounce (3 lecturas < umbral + 500 ms entre
 * eventos) y emisión de "PRESENCE_DETECTED".
 */

/** Inicializa los pines TRIGGER (salida) y ECHO (entrada). */
void sensor_init(void);

/** Realiza una medición y retorna la distancia en cm (SENSOR_ERROR_CM si falla). */
uint32_t medir_distancia_cm(void);

/** Tarea FreeRTOS de monitoreo continuo de presencia. */
void vTaskSensor(void *pvParameters);

#endif /* SENSOR_H */
