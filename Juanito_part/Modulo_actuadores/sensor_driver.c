/*
 * sensor_driver.c
 * Manejo del sensor ultrasónico HC-SR04 sobre el M4F de la BeaglePlay.
 *
 * SDK: TI MCU+ SDK AM62x
 * API GPIO: <drivers/gpio.h>
 *   - GPIO_setDirMode(baseAddr, pinNum, dir)
 *   - GPIO_pinWriteHigh(baseAddr, pinNum)
 *   - GPIO_pinWriteLow(baseAddr, pinNum)
 *   - GPIO_pinRead(baseAddr, pinNum)  -> retorna GPIO_PIN_HIGH / GPIO_PIN_LOW
 *
 * Timing: ClockP_usecToTicks() + ClockP_sleep() del DPL (Driver Porting Layer).
 */

#include "sensor_driver.h"
#include "rpmsg_interface.h"

/* MCU+ SDK headers */
#include <drivers/gpio.h>
#include <kernel/dpl/ClockP.h>
#include <kernel/dpl/DebugP.h>

/* FreeRTOS */
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"

/* Variable global para el mutex (definida en main.c) */
extern SemaphoreHandle_t xBarrierMutex;

/* =========================================================================
 * Helpers internos
 * ========================================================================= */

static inline void delay_us(uint32_t us)
{
    /* ClockP_usleep es el equivalente real a delay_us en el DPL de TI */
    ClockP_usleep(us);
}

/* =========================================================================
 * Implementación pública
 * ========================================================================= */

void sensor_init(void)
{
    /* TRIGGER como salida, en LOW */
    GPIO_setDirMode(MCU_GPIO0_BASE_ADDR, TRIGGER_PIN_NUM, GPIO_DIRECTION_OUTPUT);
    GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, TRIGGER_PIN_NUM);

    /* ECHO como entrada */
    GPIO_setDirMode(MCU_GPIO0_BASE_ADDR, ECHO_PIN_NUM, GPIO_DIRECTION_INPUT);

    DebugP_log("[Sensor] HC-SR04 inicializado. TRIGGER=MCU_GPIO0_%d, ECHO=MCU_GPIO0_%d\r\n",
               TRIGGER_PIN_NUM, ECHO_PIN_NUM);
}

uint32_t medir_distancia_cm(void)
{
    uint32_t duration = 0U;
    uint32_t timeout_count;
    uint32_t start_time;

    /* 1. Pulso de TRIGGER: 10 µs en HIGH */
    GPIO_pinWriteHigh(MCU_GPIO0_BASE_ADDR, TRIGGER_PIN_NUM);
    delay_us(10U);
    GPIO_pinWriteLow(MCU_GPIO0_BASE_ADDR, TRIGGER_PIN_NUM);

    /* 2. Esperar flanco de subida en ECHO (timeout: 100 ms para estar seguro) */
    timeout_count = 100000U;  /* ~100 ms a 1 µs por iteración */
    while (GPIO_pinRead(MCU_GPIO0_BASE_ADDR, ECHO_PIN_NUM) == GPIO_PIN_LOW)
    {
        if (--timeout_count == 0U)
        {
            DebugP_log("[Sensor] WARN: Timeout esperando flanco de subida en ECHO\r\n");
            return 999U; /* Sensor fuera de rango o desconectado */
        }
        delay_us(1U);
    }

    /* 3. Guardar tiempo de inicio y medir duración del pulso ECHO en HIGH */
    start_time = ClockP_getTimeInMicrosecs();  /* Usar timer real del sistema si disponible */
    
    timeout_count = 0U;
    while (GPIO_pinRead(MCU_GPIO0_BASE_ADDR, ECHO_PIN_NUM) == GPIO_PIN_HIGH)
    {
        timeout_count++;
        delay_us(1U);
        
        /* Límite de seguridad: ~5 metros = 30 ms de pulso */
        if (timeout_count > 30000U)
        {
            DebugP_log("[Sensor] WARN: Pulso ECHO muy largo (> 5 m)\r\n");
            break;
        }
    }

    duration = timeout_count;

    /* 4. Convertir a cm: velocidad sonido ~340 m/s → t(µs)/58 */
    /* Sanidad check: si duración es 0 o muy pequeña, retornar error */
    if (duration < 10U)
    {
        return 999U;
    }

    uint32_t distancia = duration / 58U;
    
    /* Sanidad check: si distancia es > 4m, retornar error */
    if (distancia > 400U)
    {
        return 999U;
    }

    return distancia;
}

/* =========================================================================
 * Tarea FreeRTOS
 * ========================================================================= */

void vTaskSensorUltrasonido(void *pvParameters)
{
    uint8_t lecturas_consecutivas = 0U;
    uint32_t ultima_deteccion = 0U;
    TickType_t tick_actual;
    const TickType_t DEBOUNCE_TICKS = pdMS_TO_TICKS(500U);  /* No reportar eventos dentro de 500 ms */

    sensor_init();

    while (1)
    {
        uint32_t distancia = medir_distancia_cm();

        /* Debounce espacial: 3 lecturas seguidas bajo el umbral = detección válida */
        if (distancia < DISTANCE_THRESHOLD_CM && distancia != 999U)
        {
            lecturas_consecutivas++;
        }
        else
        {
            lecturas_consecutivas = 0U;
        }

        /* Vehículo detectado: notificar solo si han pasado suficientes ms desde la última detección */
        if (lecturas_consecutivas >= 3U)
        {
            tick_actual = xTaskGetTickCount();
            
            if ((tick_actual - ultima_deteccion) >= DEBOUNCE_TICKS)
            {
                DebugP_log("[Sensor] Vehiculo detectado a %d cm. Notificando...\r\n", distancia);
                rpmsg_notify_presence();
                
                lecturas_consecutivas = 0U;
                ultima_deteccion = tick_actual;
            }
        }

        /* Muestreo cada 60 ms (recomendado HC-SR04 para evitar eco propio) */
        /* IMPORTANTE: no bloquear 5 segundos aquí; continuar monitoreando */
        vTaskDelay(pdMS_TO_TICKS(60U));
    }
}
