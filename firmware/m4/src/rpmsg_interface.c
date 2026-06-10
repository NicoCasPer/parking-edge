/*
 * rpmsg_interface.c — Canal RPMsg M4F ↔ Linux (A53).
 *
 * Mensajes A53 → M4:
 *   "HEARTBEAT"          — alimenta watchdog
 *   "OPEN"               — abre barrera
 *   "CLOSE"              — cierra barrera
 *
 * Mensajes M4 → A53:
 *   "PRESENCE_DETECTED"  — vehículo detectado por HC-SR04
 *
 * CORRECCIÓN v1.1 (buffer overflow): rx_len se inicializa a sizeof(buffer)-1
 * antes de la llamada a RPMessage_recv, garantizando espacio para '\0'.
 */

#include "rpmsg_interface.h"
#include "watchdog.h"
#include "sensor_driver.h"
#include "config.h"

#include <drivers/ipc_rpmsg.h>
#include <drivers/gpio.h>
#include <kernel/dpl/DebugP.h>

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"

#include <string.h>

extern SemaphoreHandle_t xBarrierMutex;

static RPMessage_Object gRPMsgEndpoint;
static volatile uint8_t gRPMsgInitialized = 0U;

void rpmsg_interface_init(void)
{
    RPMessage_CreateParams params;
    int32_t status;

    if (gRPMsgInitialized != 0U) { return; }

    RPMessage_CreateParams_init(&params);
    params.localEndPt = RPMSG_ENDPOINT;

    status = RPMessage_construct(&gRPMsgEndpoint, &params);
    if (status == SystemP_SUCCESS)
    {
        gRPMsgInitialized = 1U;
        DebugP_log("[RPMsg] Endpoint %d listo.\r\n", RPMSG_ENDPOINT);
    }
    else
    {
        DebugP_log("[RPMsg] ERROR init endpoint %d (status=%d).\r\n",
                   RPMSG_ENDPOINT, status);
    }
}

uint8_t rpmsg_is_initialized(void) { return gRPMsgInitialized; }

void rpmsg_notify_presence(void)
{
    const char *msg = "PRESENCE_DETECTED";
    int32_t status;

    if (gRPMsgInitialized == 0U)
    {
        DebugP_log("[RPMsg] No inicializado. Descartando PRESENCE_DETECTED.\r\n");
        return;
    }

    status = RPMessage_send(
        &gRPMsgEndpoint,
        LINUX_CORE_ID,
        RPMSG_ENDPOINT,
        (void *)msg,
        (uint16_t)strlen(msg),
        pdMS_TO_TICKS(RPMSG_SEND_TIMEOUT_MS));

    if (status == SystemP_SUCCESS)
        DebugP_log("[RPMsg] Enviado: %s\r\n", msg);
    else
        DebugP_log("[RPMsg] ERROR enviando PRESENCE_DETECTED (status=%d)\r\n", status);
}

void vTaskRPMsgListener(void *pvParameters)
{
    /* CORRECCIÓN: rx_len inicial = sizeof-1 para dejar espacio al '\0' */
    char     rx_buf[RPMSG_RX_BUF_SIZE];
    uint16_t rx_len;
    uint32_t remote_core;
    uint16_t remote_ep;
    int32_t  status;

    rpmsg_interface_init();
    DebugP_log("[RPMsg] Tarea iniciada. Esperando mensajes de Linux...\r\n");

    while (1)
    {
        rx_len = (uint16_t)(sizeof(rx_buf) - 1U);   /* reservar 1 byte para '\0' */

        status = RPMessage_recv(
            &gRPMsgEndpoint,
            (void *)rx_buf,
            &rx_len,
            &remote_core,
            &remote_ep,
            pdMS_TO_TICKS(RPMSG_RECV_TIMEOUT_MS));

        if (status != SystemP_SUCCESS) { continue; }   /* timeout normal */

        /* Garantizar terminación de cadena — rx_len <= sizeof(rx_buf)-1 */
        rx_buf[rx_len] = '\0';

        DebugP_log("[RPMsg] Recibido: '%s'\r\n", rx_buf);

        if (strcmp(rx_buf, "HEARTBEAT") == 0)
        {
            watchdog_feed();
        }
        else if (strcmp(rx_buf, "OPEN") == 0)
        {
            if (xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(100U)) == pdTRUE)
            {
                GPIO_pinWriteHigh(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
                xSemaphoreGive(xBarrierMutex);
                DebugP_log("[RPMsg] Barrera ABIERTA.\r\n");
            }
            else { DebugP_log("[RPMsg] WARN: mutex OPEN no disponible.\r\n"); }
        }
        else if (strcmp(rx_buf, "CLOSE") == 0)
        {
            if (xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(100U)) == pdTRUE)
            {
                GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, SERVO_BARRIER_PIN_NUM);
                xSemaphoreGive(xBarrierMutex);
                DebugP_log("[RPMsg] Barrera CERRADA.\r\n");
            }
            else { DebugP_log("[RPMsg] WARN: mutex CLOSE no disponible.\r\n"); }
        }
        else
        {
            DebugP_log("[RPMsg] Mensaje desconocido: '%s'\r\n", rx_buf);
        }
    }
}
