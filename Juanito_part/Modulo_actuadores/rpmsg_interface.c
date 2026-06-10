/*
 * rpmsg_interface.c
 * Comunicación RPMsg entre el M4F (FreeRTOS) y Linux (A53) en la BeaglePlay.
 *
 * SDK: TI MCU+ SDK AM62x
 * Referencia: examples/drivers/ipc/ipc_rpmsg_echo_linux/
 *
 * API usada:
 *   RPMessage_Object   — handle del canal
 *   RPMessage_CreateParams_init()
 *   RPMessage_construct()
 *   RPMessage_send()
 *   RPMessage_recv()
 *
 * GPIO API (para barrera):
 *   GPIO_pinWriteHigh() / GPIO_pinWriteLow()
 */

#include "rpmsg_interface.h"
#include "watchdog.h"
#include "sensor_driver.h" /* para MCU_GPIO0_BASE_ADDR y SERVO_BARRIER_PIN_NUM */

/* MCU+ SDK */
#include <drivers/ipc_rpmsg.h>
#include <drivers/gpio.h>
#include <kernel/dpl/DebugP.h>

/* FreeRTOS */
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"

#include <string.h>

/* =========================================================================
 * Constantes
 * ========================================================================= */

#define RPMSG_ENDPOINT (14U)
#define RPMSG_RX_BUF_SIZE (64U)
#define RPMSG_SEND_TIMEOUT_MS (1000U)  /* Timeout para envíos: 1 segundo */

/*
 * endpointId del lado Linux (el servicio de parqueadero en A53).
 * El A53 debe registrar un endpoint con el mismo número para recibir mensajes.
 * En el driver rpmsg_chrdev de Linux se accede como /dev/rpmsg0 (o similar).
 */
#define LINUX_CORE_ID (IPC_NOTIFY_CLIENT_ID_LINUX_0)

/* =========================================================================
 * Variables internas
 * ========================================================================= */

static RPMessage_Object gRPMsgEndpoint;
static volatile uint8_t gRPMsgInitialized = 0U;

/* Variable global para el mutex (definida en main.c) */
extern SemaphoreHandle_t xBarrierMutex;

/* =========================================================================
 * Implementación
 * ========================================================================= */

void rpmsg_interface_init(void)
{
    RPMessage_CreateParams params;
    int32_t status;

    if (gRPMsgInitialized != 0U)
    {
        DebugP_log("[RPMsg] Ya inicializado, saltando...\r\n");
        return;
    }

    RPMessage_CreateParams_init(&params);
    params.localEndPt = RPMSG_ENDPOINT;

    status = RPMessage_construct(&gRPMsgEndpoint, &params);

    if (status == SystemP_SUCCESS)
    {
        gRPMsgInitialized = 1U;
        DebugP_log("[RPMsg] Endpoint %d inicializado correctamente.\r\n", RPMSG_ENDPOINT);
    }
    else
    {
        DebugP_log("[RPMsg] ERROR al inicializar endpoint %d (status=%d).\r\n",
                   RPMSG_ENDPOINT, status);
    }
}

uint8_t rpmsg_is_initialized(void)
{
    return gRPMsgInitialized;
}

void rpmsg_notify_presence(void)
{
    const char *msg = "PRESENCE_DETECTED";
    int32_t status;
    uint32_t timeout_ticks = pdMS_TO_TICKS(RPMSG_SEND_TIMEOUT_MS);

    /* Verificar que RPMsg esté listo */
    if (gRPMsgInitialized == 0U)
    {
        DebugP_log("[RPMsg] ERROR: RPMsg no inicializado aún. Descartando PRESENCE_DETECTED.\r\n");
        return;
    }

    status = RPMessage_send(
        &gRPMsgEndpoint,
        LINUX_CORE_ID,  /* core de destino: A53 Linux */
        RPMSG_ENDPOINT, /* remote endpoint en Linux   */
        (void *)msg,
        (uint16_t)strlen(msg),
        timeout_ticks);  /* Timeout en lugar de WAIT_FOREVER */

    if (status == SystemP_SUCCESS)
    {
        DebugP_log("[RPMsg] Enviado: %s\r\n", msg);
    }
    else
    {
        DebugP_log("[RPMsg] ERROR al enviar PRESENCE_DETECTED (status=%d, timeout=%d ms)\r\n", 
                   status, RPMSG_SEND_TIMEOUT_MS);
    }
}

/* =========================================================================
 * Tarea FreeRTOS: escucha comandos de Linux
 * ========================================================================= */

void vTaskRPMsgListener(void *pvParameters)
{
    char rx_buffer[RPMSG_RX_BUF_SIZE];
    uint16_t rx_len;
    uint32_t remote_core_id;
    uint16_t remote_end_pt;
    int32_t status;

    /* Inicializar RPMsg al INICIO de la tarea, antes de cualquier otro código */
    rpmsg_interface_init();

    DebugP_log("[RPMsg] Tarea iniciada. Esperando mensajes de Linux...\r\n");

    while (1)
    {
        rx_len = sizeof(rx_buffer) - 1U;

        /* Bloqueante hasta que llegue un mensaje desde Linux (con timeout de 5 segundos) */
        status = RPMessage_recv(
            &gRPMsgEndpoint,
            (void *)rx_buffer,
            &rx_len,
            &remote_core_id,
            &remote_end_pt,
            pdMS_TO_TICKS(5000U));  /* Timeout: 5 segundos */

        if (status != SystemP_SUCCESS)
        {
            /* Timeout normal, no es error crítico */
            DebugP_log("[RPMsg] Timeout en recepción (status=%d). Continuando...\r\n", status);
            continue;
        }

        /* Asegurar terminación de cadena */
        rx_buffer[rx_len] = '\0';

        DebugP_log("[RPMsg] Mensaje recibido: '%s'\r\n", rx_buffer);

        /* ----- Despacho de comandos ----- */
        if (strcmp(rx_buffer, "HEARTBEAT") == 0)
        {
            watchdog_feed();
        }
        else if (strcmp(rx_buffer, "OPEN") == 0)
        {
            /* Proteger acceso a GPIO con mutex */
            if (xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(100U)) == pdTRUE)
            {
                DebugP_log("[RPMsg] Comando OPEN — Abriendo barrera (MCU_GPIO0_%d = HIGH)\r\n",
                           SERVO_BARRIER_PIN_NUM);
                GPIO_pinWriteHigh(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
                xSemaphoreGive(xBarrierMutex);
            }
            else
            {
                DebugP_log("[RPMsg] WARN: No se pudo adquirir mutex para OPEN\r\n");
            }
        }
        else if (strcmp(rx_buffer, "CLOSE") == 0)
        {
            /* Proteger acceso a GPIO con mutex */
            if (xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(100U)) == pdTRUE)
            {
                DebugP_log("[RPMsg] Comando CLOSE — Cerrando barrera (MCU_GPIO0_%d = LOW)\r\n",
                           SERVO_BARRIER_PIN_NUM);
                GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
                xSemaphoreGive(xBarrierMutex);
            }
            else
            {
                DebugP_log("[RPMsg] WARN: No se pudo adquirir mutex para CLOSE\r\n");
            }
        }
        else
        {
            DebugP_log("[RPMsg] Mensaje desconocido: '%s' (len=%d)\r\n", rx_buffer, rx_len);
        }
    }
}
