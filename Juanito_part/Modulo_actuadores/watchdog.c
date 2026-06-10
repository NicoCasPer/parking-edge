/*
 * watchdog.c
 * Watchdog de software implementado con un timer FreeRTOS one-shot.
 *
 * Si Linux (A53) no envía un mensaje "HEARTBEAT" dentro de
 * HEARTBEAT_TIMEOUT_MS ms, el callback cierra la barrera de forma segura
 * usando las APIs reales del MCU+ SDK de TI.
 *
 * API GPIO usada:
 *   GPIO_pinWriteLow(baseAddr, pinNum)  — cierra la barrera
 *   GPIO_pinWriteHigh(baseAddr, pinNum) — estado OK (opcional LED)
 */

#include "watchdog.h"

/* MCU+ SDK */
#include <drivers/gpio.h>
#include <kernel/dpl/DebugP.h>

/* FreeRTOS */
#include "FreeRTOS.h"
#include "timers.h"
#include "semphr.h"

/* =========================================================================
 * Variables internas
 * ========================================================================= */

static TimerHandle_t xWatchdogTimer = NULL;
static volatile uint8_t gWatchdogInitialized = 0U;

/* Variable global para el mutex (definida en main.c) */
extern SemaphoreHandle_t xBarrierMutex;

/* =========================================================================
 * Callback del watchdog (se ejecuta si el timer expira)
 * ========================================================================= */

static void prvWatchdogCallback(TimerHandle_t xTimer)
{
    (void)xTimer;

    /*
     * ¡EMERGENCIA! Linux no respondió a tiempo.
     * Forzar cierre de barrera → MCU_GPIO0_8 = LOW
     * Usar mutex para sincronización
     */
    if (xBarrierMutex != NULL)
    {
        if (xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(50U)) == pdTRUE)
        {
            GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
            xSemaphoreGive(xBarrierMutex);
        }
        else
        {
            /* Fallback: intentar escribir sin mutex en caso de emergencia */
            GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
        }
    }
    else
    {
        /* Mutex no disponible, escribir directamente */
        GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
    }

    DebugP_log("[Watchdog] TIMEOUT — Linux no responde. Barrera cerrada por seguridad.\r\n");
}

/* =========================================================================
 * API pública
 * ========================================================================= */

void watchdog_init(void)
{
    if (gWatchdogInitialized != 0U)
    {
        DebugP_log("[Watchdog] Ya inicializado, saltando...\r\n");
        return;
    }

    /*
     * Inicializar pin de barrera como salida y ponerlo en LOW
     * (estado seguro: barrera cerrada al arranque).
     */
    GPIO_setDirMode(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM, GPIO_DIRECTION_OUTPUT);
    GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);

    /* Crear timer one-shot de FreeRTOS */
    xWatchdogTimer = xTimerCreate(
        "LinuxWatchdog",
        pdMS_TO_TICKS(HEARTBEAT_TIMEOUT_MS),
        pdFALSE,           /* pdFALSE = one-shot, no auto-reload */
        (void *)0,
        prvWatchdogCallback
    );

    if (xWatchdogTimer != NULL)
    {
        if (xTimerStart(xWatchdogTimer, 0) == pdPASS)
        {
            gWatchdogInitialized = 1U;
            DebugP_log("[Watchdog] Iniciado correctamente. Timeout = %d ms\r\n", HEARTBEAT_TIMEOUT_MS);
        }
        else
        {
            DebugP_log("[Watchdog] ERROR: No se pudo iniciar el timer (xTimerStart falló).\r\n");
        }
    }
    else
    {
        DebugP_log("[Watchdog] ERROR: No se pudo crear el timer FreeRTOS.\r\n");
    }
}

uint8_t watchdog_is_initialized(void)
{
    return gWatchdogInitialized;
}

void watchdog_feed(void)
{
    if (xWatchdogTimer == NULL)
    {
        DebugP_log("[Watchdog] WARN: Timer no inicializado, no se puede alimentar watchdog.\r\n");
        return;
    }

    if (gWatchdogInitialized == 0U)
    {
        DebugP_log("[Watchdog] WARN: Watchdog no inicializado correctamente.\r\n");
        return;
    }

    /* Reiniciar la cuenta regresiva */
    if (xTimerReset(xWatchdogTimer, pdMS_TO_TICKS(100U)) == pdPASS)
    {
        DebugP_log("[Watchdog] Heartbeat recibido. Timer reiniciado.\r\n");
    }
    else
    {
        DebugP_log("[Watchdog] WARN: No se pudo reiniciar el timer.\r\n");
    }
}
