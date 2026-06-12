/*
 * barrier.cpp — Control de la barrera como SERVO con PWM (LEDC), protegido por mutex.
 *
 * Sustituye el control digital on/off por un movimiento fijo de 90°:
 *   - barrier_close() -> 0°  (SERVO_CLOSE_US): posición de reposo.
 *   - barrier_open()  -> 90° (SERVO_OPEN_US): barrera levantada.
 * El servo mantiene la posición de forma estable (sin el tembleque de abrir/cerrar
 * que producía el GPIO digital). El mutex protege el periférico ante acceso
 * concurrente (listener UART y watchdog), igual que el xBarrierMutex del M4.
 */

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "config.h"
#include "barrier.h"

static SemaphoreHandle_t xBarrierMutex = NULL;

/* Convierte un ancho de pulso (us) al valor de duty del LEDC a la resolución dada. */
static uint32_t us_to_duty(uint32_t pulse_us)
{
    const uint32_t max_duty = (1UL << SERVO_LEDC_RES_BITS) - 1UL;
    return (uint32_t)(((uint64_t)pulse_us * max_duty) / SERVO_PERIOD_US);
}

void barrier_init(void)
{
    /* Configurar el canal LEDC y asociarlo al pin de señal del servo. */
    ledcSetup(SERVO_LEDC_CHANNEL, SERVO_LEDC_FREQ_HZ, SERVO_LEDC_RES_BITS);
    ledcAttachPin(SERVO_BARRIER_PIN_NUM, SERVO_LEDC_CHANNEL);

    /* Posición segura al arranque: cerrada (0°). */
    ledcWrite(SERVO_LEDC_CHANNEL, us_to_duty(SERVO_CLOSE_US));

    if (xBarrierMutex == NULL)
    {
        xBarrierMutex = xSemaphoreCreateMutex();
    }
    Serial.printf("[Barrera] Servo init. GPIO%d a 0 grados (cerrada).\n",
                  SERVO_BARRIER_PIN_NUM);
}

/* Mueve el servo al ancho de pulso indicado de forma sincronizada. */
static bool barrier_set_us(uint32_t pulse_us)
{
    if (xBarrierMutex == NULL) { return false; }

    if (xSemaphoreTake(xBarrierMutex, pdMS_TO_TICKS(100)) != pdTRUE)
    {
        return false;   /* no se pudo tomar el mutex */
    }

    ledcWrite(SERVO_LEDC_CHANNEL, us_to_duty(pulse_us));
    xSemaphoreGive(xBarrierMutex);
    return true;
}

bool barrier_open(void)  { return barrier_set_us(SERVO_OPEN_US);  }   /* 90° */
bool barrier_close(void) { return barrier_set_us(SERVO_CLOSE_US); }   /* 0°  */
