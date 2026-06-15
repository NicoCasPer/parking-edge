/*
 * watchdog.c — Watchdog de software sobre FreeRTOS timer.
 *
 * Cierra la barrera (MCU_GPIO0_8 = LOW) si el dominio Linux no envía
 * HEARTBEAT dentro de HEARTBEAT_TIMEOUT_MS ms.
 *
 * CORRECCIÓN v1.1: el fallback sin mutex ha sido eliminado. Si no se puede
 * adquirir el mutex en el callback de emergencia, se registra el fallo y
 * se intenta de nuevo en el siguiente ciclo del timer. Escribir GPIO sin
 * sincronización en un sistema RTOS multitarea introduce carreras que pueden
 * dejar la barrera en estado indeterminado.
 */
#include "config.h"
#include "watchdog.h"
#include "sensor_driver.h"

#include <drivers/gpio.h>
#include <kernel/dpl/DebugP.h>

#include "FreeRTOS.h"
#include "timers.h"
#include "semphr.h"

extern SemaphoreHandle_t xBarrierMutex;

static TimerHandle_t xWatchdogTimer    = NULL;
static volatile uint8_t gWDInitialized = 0U;

static void prvWatchdogCallback(TimerHandle_t xTimer)
{
    (void)xTimer;

    /* Intentar adquirir mutex con timeout corto */
    if (xBarrierMutex != NULL &&
        xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(200U)) == pdTRUE)
    {
        GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
        xSemaphoreGive(xBarrierMutex);
        DebugP_log("[Watchdog] TIMEOUT — barrera cerrada por seguridad.\r\n");
    }
    else
    {
        /*
         * No se pudo adquirir el mutex: registrar fallo pero NO escribir
         * GPIO sin sincronización. El timer one-shot no se reinicia; Linux
         * debe enviar HEARTBEAT para restablecer operación normal.
         */
        DebugP_log("[Watchdog] TIMEOUT — mutex no disponible. "
                   "Barrera NO modificada. Requiere intervención.\r\n");
    }
}

void watchdog_init(void)
{
    if (gWDInitialized != 0U) { return; }

    GPIO_setDirMode(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM, GPIO_DIRECTION_OUTPUT);
    GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);

    xWatchdogTimer = xTimerCreate(
        "LinuxWatchdog",
        pdMS_TO_TICKS(HEARTBEAT_TIMEOUT_MS),
        pdFALSE,
        (void *)0,
        prvWatchdogCallback
    );

    if (xWatchdogTimer != NULL && xTimerStart(xWatchdogTimer, 0) == pdPASS)
    {
        gWDInitialized = 1U;
        DebugP_log("[Watchdog] Iniciado. Timeout=%d ms\r\n", HEARTBEAT_TIMEOUT_MS);
    }
    else
    {
        DebugP_log("[Watchdog] ERROR: no se pudo crear/iniciar timer.\r\n");
    }
}

uint8_t watchdog_is_initialized(void)
{
    return gWDInitialized;
}

void watchdog_feed(void)
{
    if (xWatchdogTimer == NULL || gWDInitialized == 0U)
    {
        DebugP_log("[Watchdog] WARN: feed ignorado, watchdog no inicializado.\r\n");
        return;
    }

    if (xTimerReset(xWatchdogTimer, pdMS_TO_TICKS(100U)) == pdPASS)
    {
        DebugP_log("[Watchdog] Heartbeat recibido. Timer reiniciado.\r\n");
    }
    else
    {
        DebugP_log("[Watchdog] WARN: xTimerReset falló.\r\n");
    }
}
