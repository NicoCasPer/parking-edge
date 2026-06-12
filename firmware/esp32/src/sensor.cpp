/*
 * sensor.cpp — HC-SR04 sobre ESP32. Equivalente a sensor_driver.c del M4.
 *
 * Diferencia técnica: en el ESP32 se usa pulseIn() para medir el ancho del pulso
 * ECHO (más fiable que el bucle manual del M4), pero la lógica de umbrales,
 * debounce y notificación es idéntica.
 */

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "config.h"
#include "sensor.h"
#include "uart_protocol.h"

void sensor_init(void)
{
    pinMode(TRIGGER_PIN_NUM, OUTPUT);
    digitalWrite(TRIGGER_PIN_NUM, LOW);
    pinMode(ECHO_PIN_NUM, INPUT);

    Serial.printf("[Sensor] HC-SR04 init. TRIGGER=GPIO%d ECHO=GPIO%d\n",
                  TRIGGER_PIN_NUM, ECHO_PIN_NUM);
}

uint32_t medir_distancia_cm(void)
{
    /* 1. Pulso TRIGGER: 10 us en HIGH */
    digitalWrite(TRIGGER_PIN_NUM, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIGGER_PIN_NUM, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIGGER_PIN_NUM, LOW);

    /* 2. Medir ancho del pulso ECHO en HIGH. Timeout ~30 ms (~5 m). */
    unsigned long duration = pulseIn(ECHO_PIN_NUM, HIGH, 30000UL);
    if (duration == 0UL)
    {
        return SENSOR_ERROR_CM;   /* timeout: fuera de rango o desconectado */
    }

    /* 3. Convertir a cm: t(us)/58 */
    uint32_t distancia = (uint32_t)(duration / 58UL);

    /* 4. Sanidad: descartar 0 o > 4 m */
    if (distancia == 0U || distancia > MAX_DISTANCE_CM)
    {
        return SENSOR_ERROR_CM;
    }
    return distancia;
}

void vTaskSensor(void *pvParameters)
{
    (void)pvParameters;

    uint8_t    lecturas_consecutivas = 0U;
    TickType_t ultima_deteccion      = 0U;
    const TickType_t DEBOUNCE_TICKS  = pdMS_TO_TICKS(DETECTION_DEBOUNCE_MS);

    sensor_init();

    for (;;)
    {
        uint32_t distancia = medir_distancia_cm();

        /* Debounce espacial: 3 lecturas válidas bajo el umbral = detección */
        if (distancia < DISTANCE_THRESHOLD_CM && distancia != SENSOR_ERROR_CM)
        {
            lecturas_consecutivas++;
        }
        else
        {
            lecturas_consecutivas = 0U;
        }

        if (lecturas_consecutivas >= DEBOUNCE_READINGS)
        {
            TickType_t ahora = xTaskGetTickCount();

            /* Debounce temporal: no repetir dentro de DETECTION_DEBOUNCE_MS */
            if ((ahora - ultima_deteccion) >= DEBOUNCE_TICKS)
            {
                Serial.printf("[Sensor] Vehiculo detectado a %u cm. Notificando...\n",
                              distancia);
                uart_send_line("PRESENCE_DETECTED");

                lecturas_consecutivas = 0U;
                ultima_deteccion      = ahora;
            }
        }

        /* Muestreo cada 60 ms (recomendado HC-SR04 para evitar eco propio) */
        vTaskDelay(pdMS_TO_TICKS(SENSOR_SAMPLE_PERIOD_MS));
    }
}
