/*
 * pru0_pwm.c — Generación de PWM determinístico para el motor de la barrera.
 *
 * ESTADO: STUB — pendiente de implementación.
 *
 * Responsabilidad prevista:
 *   - Generar señal PWM de precisión sub-microsegundo para el servo/motor
 *     de la talanquera usando el PRU-SS del AM62x.
 *   - Recibir comandos de posición desde el M4 vía memoria compartida.
 *   - Reportar posición actual al M4 para interlock anti-colisión.
 *
 * Prerrequisitos:
 *   - TI PRU C compiler (pru-cgt) del MCU+ SDK.
 *   - Definición del canal de memoria compartida con el M4.
 *   - Mapa de pines PRU0 en la BeaglePlay (nets PRU0_GPO*).
 *
 * Referencias:
 *   - AM62x PRU-SS Technical Reference Manual (SPRUJ52)
 *   - examples/drivers/ipc/ipc_rpmsg_echo_linux/ (MCU+ SDK)
 */

/* TODO: implementar en fase PRU del proyecto */
