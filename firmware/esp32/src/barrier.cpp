/*
 * barrier.cpp — Implementación del control de barrera con mutex.
 *
 * Equivale al manejo de SERVO_BARRIER_PIN_NUM del M4 (main.c + rpmsg_interface.c
 * + watchdog.c), donde xBarrierMutex protegía el GPIO ante acceso concurrente.
 */

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "config.h"
#include "barrier.h"

static SemaphoreHandle_t xBarrierMutex = NULL;

void barrier_init(void)
{
    pinMode(SERVO_BARRIER_PIN_NUM, OUTPUT);
    digitalWrite(SERVO_BARRIER_PIN_NUM, LOW);   /* estado seguro al arranque */

    if (xBarrierMutex == NULL)
    {
        xBarrierMutex = xSemaphoreCreateMutex();
    }
    Serial.printf("[Barrera] Init. GPIO%d = LOW (cerrada).\n", SERVO_BARRIER_PIN_NUM);
}

/* Escribe el GPIO de la barrera de forma sincronizada. */
static bool barrier_set(int level)
{
    if (xBarrierMutex == NULL) { return false; }

    if (xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(100)) != pdTRUE)
    {
        return false;   /* no se pudo tomar el mutex */
    }

    digitalWrite(SERVO_BARRIER_PIN_NUM, level);
    xSemaphoreGive(xBarrierMutex);
    return true;
}

bool barrier_open(void)  { return barrier_set(HIGH); }
bool barrier_close(void) { return barrier_set(LOW); }
