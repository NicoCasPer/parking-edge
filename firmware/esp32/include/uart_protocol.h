#ifndef UART_PROTOCOL_H
#define UART_PROTOCOL_H

#include <Arduino.h>

/*
 * uart_protocol.h — Canal UART ESP32 <-> BeaglePlay (reemplaza a RPMsg).
 *
 * Protocolo de texto (líneas terminadas en '\n'), IDÉNTICO al contrato que el
 * lado Python (rpmsg_client.py / command_dispatcher.py) ya espera:
 *
 *   BeaglePlay -> ESP32:
 *     "HEARTBEAT..."        alimenta el watchdog (sin respuesta)
 *     "OPEN:<trace_id>"     abre barrera  -> responde "OPEN:OK:<trace_id>"
 *     "CLOSE:<trace_id>"    cierra barrera -> responde "CLOSE:OK:<trace_id>"
 *     "STOP:<trace_id>"     estado seguro (== CLOSE) -> "STOP:OK:<trace_id>"
 *
 *   ESP32 -> BeaglePlay:
 *     "PRESENCE_DETECTED"            vehículo detectado por HC-SR04
 *     "<ACTION>:OK:<trace_id>"       comando ejecutado
 *     "<ACTION>:FAULT:<trace_id>"    comando falló
 *     "HARDWARE_FAULT:<reason>"      fallo autónomo (p.ej. watchdog_timeout)
 *
 * IMPORTANTE: los logs de depuración van por Serial (UART0/USB), NUNCA por
 * Serial2, para no contaminar el canal de datos con ruido.
 */

/** Inicializa Serial2 (UART2) y el mutex de transmisión. */
void uart_init(void);

/** Escribe una línea completa ('\n' incluido) de forma atómica hacia la Beagle. */
void uart_send_line(const String &line);

/** Tarea FreeRTOS que lee líneas de UART2, parsea y despacha comandos. */
void vTaskUartListener(void *pvParameters);

#endif /* UART_PROTOCOL_H */
