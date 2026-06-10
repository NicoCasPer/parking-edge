#ifndef RPMSG_INTERFACE_H
#define RPMSG_INTERFACE_H

#include <stdint.h>

/*
 * rpmsg_interface.h
 * Canal de comunicación RPMsg entre el M4F (FreeRTOS) y el A53 (Linux).
 *
 * Endpoint acordado: 14
 *
 * Mensajes esperados (A53 → M4):
 *   "HEARTBEAT"  — Alimenta el watchdog
 *   "OPEN"       — Abre la barrera (MCU_GPIO0_8 = HIGH)
 *   "CLOSE"      — Cierra la barrera (MCU_GPIO0_8 = LOW)
 *
 * Mensajes enviados (M4 → A53):
 *   "PRESENCE_DETECTED" — Vehículo detectado por el HC-SR04
 */

/** Inicializa el canal RPMsg en el endpoint del M4 (segura para llamar múltiples veces) */
void rpmsg_interface_init(void);

/** Retorna 1 si RPMsg está inicializado, 0 en caso contrario */
uint8_t rpmsg_is_initialized(void);

/** Envía "PRESENCE_DETECTED" al A53 por RPMsg con timeout */
void rpmsg_notify_presence(void);

/**
 * Tarea FreeRTOS que bloquea esperando mensajes entrantes de Linux.
 * Maneja: "HEARTBEAT", "OPEN", "CLOSE"
 * Inicializa RPMsg al principio, así que es segura ser la primera tarea.
 */
void vTaskRPMsgListener(void *pvParameters);

#endif /* RPMSG_INTERFACE_H */
