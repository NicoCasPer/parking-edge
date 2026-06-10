/*
 * main.c
 * Punto de entrada del firmware del M4 en la BeaglePlay.
 *
 * Flujo:
 * 1. Inicializar hardware (GPIO, RPMsg)
 * 2. Crear el watchdog de software
 * 3. Crear tareas FreeRTOS con sincronización
 * 4. Iniciar el scheduler
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "sensor_driver.h"
#include "rpmsg_interface.h"
#include "watchdog.h"

/* MCU+ SDK headers */
#include <kernel/dpl/DebugP.h>
#include <drivers/gpio.h>

/* =========================================================================
 * Variables globales de sincronización
 * ========================================================================= */

/* Mutex para proteger acceso al GPIO de la barrera (SERVO_BARRIER_PIN_NUM) */
SemaphoreHandle_t xBarrierMutex = NULL;

int main(void)
{
    BaseType_t xTaskStatus;

    /* 1. Inicializar Hardware del AM62x */
    DebugP_log("[Main] Inicializando hardware del AM62x...\r\n");
    
    /* El SDK de TI inicializa GPIO automáticamente con Board_init() */
    /* Si es necesario, añadir aquí inicialización explícita */

    /* Configurar pin de barrera como salida (LOW = cerrada) */
    GPIO_setDirMode(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM, GPIO_DIRECTION_OUTPUT);
    GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);

    DebugP_log("[Main] Hardware inicializado. SERVO_BARRIER_PIN_NUM (MCU_GPIO0_%d) configurado como salida.\r\n",
               SERVO_BARRIER_PIN_NUM);

    /* 2. Crear mutex para proteger acceso al GPIO de barrera */
    xBarrierMutex = xSemaphoreCreateMutex();
    if (xBarrierMutex == NULL)
    {
        DebugP_log("[Main] ERROR: No se pudo crear el mutex de barrera. Aborting...\r\n");
        while (1);
    }
    DebugP_log("[Main] Mutex de barrera creado.\r\n");

    /* 3. Inicializar el Watchdog de Software */
    watchdog_init();

    /* 4. Crear las tareas en FreeRTOS */
    
    /* Tarea 1: Monitoreo del sensor ultrasonido HC-SR04 (Prioridad Media) */
    xTaskStatus = xTaskCreate(
        vTaskSensorUltrasonido,
        "UltrasonicTask",
        configMINIMAL_STACK_SIZE + 256,  /* Stack más generoso */
        NULL,
        2,  /* Prioridad media */
        NULL
    );
    if (xTaskStatus != pdPASS)
    {
        DebugP_log("[Main] ERROR: No se pudo crear vTaskSensorUltrasonido.\r\n");
        while (1);
    }

    /* Tarea 2: Escucha de mensajes RPMsg de Linux (Prioridad Alta) */
    xTaskStatus = xTaskCreate(
        vTaskRPMsgListener,
        "RPMsgTask",
        configMINIMAL_STACK_SIZE + 512,  /* Stack más generoso */
        NULL,
        3,  /* Prioridad alta */
        NULL
    );
    if (xTaskStatus != pdPASS)
    {
        DebugP_log("[Main] ERROR: No se pudo crear vTaskRPMsgListener.\r\n");
        while (1);
    }

    DebugP_log("[Main] Todas las tareas creadas. Iniciando scheduler FreeRTOS...\r\n");

    /* 5. Arrancar el Planificador de FreeRTOS */
    vTaskStartScheduler();

    /* Si llega aquí, es porque fallo la inicialización de FreeRTOS */
    DebugP_log("[Main] PANIC: FreeRTOS scheduler falló.\r\n");
    while (1);

    return 0;
}