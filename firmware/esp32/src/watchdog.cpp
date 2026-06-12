/*
 * watchdog.cpp — Watchdog de software sobre un timer FreeRTOS one-shot.
 *
 * Si expira (Linux dejó de mandar HEARTBEAT), cierra la barrera por seguridad y
 * emite "HARDWARE_FAULT:watchdog_timeout" hacia la Beagle. El timer es one-shot
 * (igual que el M4): tras dispararse, sólo vuelve a armarse cuando llega un
 * HEARTBEAT (watchdog_feed lo reinicia).
 */

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/timers.h"

#include "config.h"
#include "watchdog.h"
#include "barrier.h"
#include "uart_protocol.h"

static TimerHandle_t xWatchdogTimer = NULL;

static void prvWatchdogCallback(TimerHandle_t xTimer)
{
    (void)xTimer;

    if (barrier_close())
    {
        uart_send_line("HARDWARE_FAULT:watchdog_timeout");
        Serial.println("[Watchdog] TIMEOUT — barrera cerrada por seguridad.");
    }
    else
    {
        /* No se pudo tomar el mutex: no se escribe el GPIO sin sincronización.
         * Linux debe reanudar HEARTBEAT para restablecer operación normal. */
        Serial.println("[Watchdog] TIMEOUT — mutex no disponible. Barrera NO modificada.");
    }
}

void watchdog_init(void)
{
    if (xWatchdogTimer != NULL) { return; }

    xWatchdogTimer = xTimerCreate(
        "LinuxWatchdog",
        pdMS_TO_TICKS(HEARTBEAT_TIMEOUT_MS),
        pdFALSE,                 /* one-shot */
        (void *)0,
        prvWatchdogCallback);

    if (xWatchdogTimer != NULL && xTimerStart(xWatchdogTimer, 0) == pdPASS)
    {
        Serial.printf("[Watchdog] Iniciado. Timeout=%d ms\n", HEARTBEAT_TIMEOUT_MS);
    }
    else
    {
        Serial.println("[Watchdog] ERROR: no se pudo crear/iniciar el timer.");
    }
}

void watchdog_feed(void)
{
    if (xWatchdogTimer == NULL) { return; }
    xTimerReset(xWatchdogTimer, pdMS_TO_TICKS(100));
}
