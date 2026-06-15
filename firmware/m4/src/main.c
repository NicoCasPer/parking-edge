/*
 * main.c — Punto de entrada del firmware M4 del parqueadero inteligente.
 *
 * Flujo:
 *   1. Inicializar GPIO de barrera (salida LOW = cerrada)
 *   2. Crear mutex de sincronización para barrera
 *   3. Inicializar watchdog de software
 *   4. Crear tareas FreeRTOS con stacks explícitos (SENSOR_TASK_STACK_SIZE,
 *      RPMSG_TASK_STACK_SIZE definidos en config.h)
 *   5. Iniciar scheduler
 */
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "config.h"
#include "watchdog.h"
#include "sensor_driver.h"
#include "rpmsg_interface.h"

SemaphoreHandle_t xBarrierMutex = NULL;

int main(void)
{
    BaseType_t status;

    DebugP_log("[Main] Firmware v%s build %s %s\r\n",
               FW_VERSION_STR, FW_BUILD_DATE, FW_BUILD_TIME);

    /* 1. Barrera: salida, LOW = estado seguro al arranque */
/* Por esto (en v12 la constante correcta es sin la palabra 'PUT'): */
    GPIO_setDirMode(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM, GPIO_DIRECTION_OUTPUT);
    GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);

    /* 2. Mutex de barrera — protege el GPIO ante acceso concurrente */
    xBarrierMutex = xSemaphoreCreateMutex();
    if (xBarrierMutex == NULL)
    {
        DebugP_log("[Main] FATAL: no se pudo crear xBarrierMutex.\r\n");
        while (1) { /* never reached */ }
    }

    /* 3. Watchdog — cierra barrera si Linux deja de enviar heartbeats */
    watchdog_init();

    /* 4. Tarea: sensor HC-SR04 (prioridad media, stack explícito) */
    status = xTaskCreate(
        vTaskSensorUltrasonido,
        "SensorTask",
        SENSOR_TASK_STACK_SIZE,
        NULL,
        SENSOR_TASK_PRIORITY,
        NULL
    );
    if (status != pdPASS)
    {
        DebugP_log("[Main] FATAL: no se pudo crear SensorTask.\r\n");
        while (1) { /* never reached */ }
    }

    /* 4b. Tarea: listener RPMsg (prioridad alta, stack explícito) */
    status = xTaskCreate(
        vTaskRPMsgListener,
        "RPMsgTask",
        RPMSG_TASK_STACK_SIZE,
        NULL,
        RPMSG_TASK_PRIORITY,
        NULL
    );
    if (status != pdPASS)
    {
        DebugP_log("[Main] FATAL: no se pudo crear RPMsgTask.\r\n");
        while (1) { /* never reached */ }
    }

    DebugP_log("[Main] Tareas creadas. Iniciando scheduler FreeRTOS...\r\n");

    /* 5. Scheduler — no retorna en operación normal */
    vTaskStartScheduler();

    DebugP_log("[Main] PANIC: vTaskStartScheduler retornó.\r\n");
    while (1) { /* never reached */ }
    return 0;
}
