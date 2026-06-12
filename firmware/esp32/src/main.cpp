/*
 * main.cpp — Punto de entrada del firmware ESP32 del parqueadero inteligente.
 *
 * Reemplaza al firmware del Cortex-M4 de la BeaglePlay. Maneja los GPIOs y se
 * comunica con Linux por UART (Serial2) en vez de RPMsg.
 *
 * Flujo de arranque:
 *   1. Serial (UART0/USB) para logs de depuración.
 *   2. barrier_init()  — GPIO barrera en LOW (estado seguro) + mutex.
 *   3. uart_init()     — Serial2 hacia la BeaglePlay + mutex de TX.
 *   4. watchdog_init() — timer de 5 s que cierra la barrera sin heartbeats.
 *   5. Tareas FreeRTOS: sensor HC-SR04 y listener UART.
 *
 * En ESP32, Arduino crea su propio loopTask; toda la lógica vive en las tareas.
 */

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "config.h"
#include "barrier.h"
#include "sensor.h"
#include "watchdog.h"
#include "uart_protocol.h"

void setup()
{
    Serial.begin(115200);    /* UART0 / USB — SOLO depuración */
    delay(200);

    Serial.printf("\n[Main] Firmware parking-edge ESP32 %s build %s %s\n",
                  FW_VERSION_STR, __DATE__, __TIME__);

    barrier_init();    /* 2 */
    uart_init();       /* 3 */
    watchdog_init();   /* 4 */

    /* 5. Tareas */
    xTaskCreate(vTaskSensor, "SensorTask", SENSOR_TASK_STACK, NULL,
                SENSOR_TASK_PRIORITY, NULL);
    xTaskCreate(vTaskUartListener, "UartTask", UART_TASK_STACK, NULL,
                UART_TASK_PRIORITY, NULL);

    Serial.println("[Main] Tareas creadas. Sistema operativo.");
}

void loop()
{
    /* Toda la lógica ocurre en las tareas FreeRTOS. */
    vTaskDelay(pdMS_TO_TICKS(1000));
}
