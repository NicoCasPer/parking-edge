/*
 * uart_protocol.cpp — Listener UART y serialización de la salida hacia la Beagle.
 *
 * Equivale a rpmsg_interface.c del M4 (vTaskRPMsgListener), pero sobre UART2.
 * El envío se centraliza en uart_send_line(), protegido por un mutex de TX para
 * que las distintas tareas (sensor, watchdog, este listener) no entrelacen líneas.
 */

#include "uart_protocol.h"
#include "config.h"
#include "barrier.h"
#include "watchdog.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static SemaphoreHandle_t xUartTxMutex = NULL;

void uart_init(void)
{
    Serial2.begin(UART_BEAGLE_BAUD, SERIAL_8N1, UART_BEAGLE_RX_PIN, UART_BEAGLE_TX_PIN);
    if (xUartTxMutex == NULL)
    {
        xUartTxMutex = xSemaphoreCreateMutex();
    }
    Serial.printf("[UART] UART2 listo. RX=GPIO%d TX=GPIO%d @ %d baud.\n",
                  UART_BEAGLE_RX_PIN, UART_BEAGLE_TX_PIN, UART_BEAGLE_BAUD);
}

void uart_send_line(const String &line)
{
    if (xUartTxMutex != NULL)
    {
        xSemaphoreTake(xUartTxMutex, portMAX_DELAY);
    }

    Serial2.print(line);
    Serial2.print('\n');

    if (xUartTxMutex != NULL)
    {
        xSemaphoreGive(xUartTxMutex);
    }
}

/* Extrae el trace_id de "ACTION:trace_id" (todo lo que sigue al primer ':'). */
static String extract_trace_id(const String &line)
{
    int idx = line.indexOf(':');
    if (idx < 0) { return String("unknown"); }
    return line.substring(idx + 1);
}

/* Acciona la barrera y responde ACTION:OK/FAULT:trace_id. STOP se trata como CLOSE. */
static void handle_command(const String &action, const String &trace_id)
{
    bool ok;
    if (action == "OPEN") { ok = barrier_open(); }
    else                  { ok = barrier_close(); }   /* CLOSE y STOP cierran */

    uart_send_line(action + (ok ? ":OK:" : ":FAULT:") + trace_id);
    Serial.printf("[UART] %s trace=%s -> %s\n",
                  action.c_str(), trace_id.c_str(), ok ? "OK" : "FAULT");
}

void vTaskUartListener(void *pvParameters)
{
    (void)pvParameters;
    String line;
    line.reserve(160);

    Serial.println("[UART] Listener iniciado. Esperando ordenes de la BeaglePlay...");

    for (;;)
    {
        while (Serial2.available() > 0)
        {
            char c = (char)Serial2.read();

            if (c == '\n' || c == '\r')
            {
                line.trim();
                if (line.length() > 0)
                {
                    if (line.startsWith("HEARTBEAT"))
                    {
                        watchdog_feed();            /* latido — sin respuesta */
                    }
                    else if (line.startsWith("OPEN:"))
                    {
                        handle_command("OPEN", extract_trace_id(line));
                    }
                    else if (line.startsWith("CLOSE:"))
                    {
                        handle_command("CLOSE", extract_trace_id(line));
                    }
                    else if (line.startsWith("STOP:"))
                    {
                        handle_command("STOP", extract_trace_id(line));
                    }
                    else
                    {
                        Serial.printf("[UART] Linea ignorada: '%s'\n", line.c_str());
                    }
                }
                line = "";
            }
            else
            {
                line += c;
                if (line.length() > 128)   /* protección anti-overflow */
                {
                    line = "";
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
