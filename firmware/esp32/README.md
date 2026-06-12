# Firmware ESP32 WROOM-32 — parking-edge

Reemplaza al firmware del **Cortex-M4** de la BeaglePlay (que no se podía flashear).
El ESP32 asume **todo el manejo de GPIOs** (HC-SR04, barrera, watchdog) y se
comunica con la BeaglePlay por **UART** en lugar de RPMsg.

Ver el contexto completo y el contrato de protocolo en [../../ESP32.md](../../ESP32.md).

## Estructura

```
firmware/esp32/
├── platformio.ini        # entorno esp32dev, framework Arduino, 115200
├── include/
│   ├── config.h          # pines, umbrales, timeouts (espejo del M4)
│   ├── sensor.h
│   ├── barrier.h
│   ├── watchdog.h
│   └── uart_protocol.h
└── src/
    ├── main.cpp          # setup() + creación de tareas FreeRTOS
    ├── sensor.cpp        # HC-SR04 + tarea de presencia
    ├── barrier.cpp       # barrera digital con mutex
    ├── watchdog.cpp      # timer de seguridad 5 s
    └── uart_protocol.cpp # listener UART2 + envío serializado
```

## Pines (ESP32 DevKit v1)

| Función                 | GPIO   | Notas                                              |
|-------------------------|--------|----------------------------------------------------|
| HC-SR04 TRIGGER         | GPIO5  | Salida.                                            |
| HC-SR04 ECHO            | GPIO18 | Entrada. **Divisor de voltaje 5 V→3.3 V (abajo).** |
| Barrera (servo PWM)     | GPIO19 | Señal del servo (LEDC 50 Hz). 0°=cerrada, 90°=abierta. |
| UART2 TX → RX Beagle    | GPIO17 |                                                    |
| UART2 RX ← TX Beagle    | GPIO16 |                                                    |
| Debug (UART0/USB)       | GPIO1/3| Logs. No usar para datos.                          |

> Evita GPIO6–11 (flash SPI). GPIO34–39 son sólo entrada.

### Cableado UART (cruzado, ambos 3.3 V TTL)

```
ESP32 GPIO17 (TX2) ───► RX  BeaglePlay
ESP32 GPIO16 (RX2) ◄─── TX  BeaglePlay
ESP32 GND          ────  GND BeaglePlay   (común, obligatorio)
```
No conectar 5 V/VBUS entre placas; sólo TX, RX y GND.

### Divisor de voltaje del ECHO (crítico — el ESP32 NO tolera 5 V)

```
ECHO (5V) ──[ R1 = 1 kΩ ]──┬── GPIO18 (ESP32)
                           │
                      [ R2 = 2 kΩ ]
                           │
                          GND
```
TRIGGER puede ir directo (3.3 V se lee como HIGH). Alimentar el HC-SR04 con 5 V
(VIN/USB del ESP32 o fuente externa) y GND común.

### Barrera = servo (movimiento fijo de 90°)

La barrera es un servo controlado por PWM (LEDC, 50 Hz) en GPIO19:
- `CLOSE` → **0°** (1000 µs), posición de reposo.
- `OPEN`  → **90°** (1500 µs), barrera levantada.

El servo mantiene la posición de forma estable; ya **no** se usa el control digital
on/off que producía el tembleque de abrir/cerrar. Alimenta el servo con **5 V
externos** (no desde el 3.3 V del ESP32) y **GND común**. Si tu servo recorre poco
o demasiado, ajusta `SERVO_CLOSE_US`/`SERVO_OPEN_US` en `include/config.h`.

## Compilar y flashear (PlatformIO)

```bash
# desde firmware/esp32/
pio run                 # compilar
pio run -t upload       # flashear por USB
pio device monitor -b 115200   # ver logs de depuración (UART0)
```

Con Arduino IDE: añade el core "esp32", selecciona "ESP32 Dev Module", copia los
`.cpp`/`.h` a un sketch y compila.

## Protocolo UART (resumen)

- Beagle → ESP32: `HEARTBEAT...`, `OPEN:<id>`, `CLOSE:<id>`, `STOP:<id>` (línea `\n`).
- ESP32 → Beagle: `PRESENCE_DETECTED`, `<ACTION>:OK:<id>`, `<ACTION>:FAULT:<id>`,
  `HARDWARE_FAULT:<reason>`.
- 115200 8N1. Los logs de debug van por USB (UART0), nunca por UART2.

Detalle completo y lado Python en [../../ESP32.md](../../ESP32.md).

## Prueba rápida

```bash
# en la BeaglePlay, con el UART configurado a 115200 raw:
echo "OPEN:test1"  > /dev/ttyS2     # el ESP32 abre y responde OPEN:OK:test1
echo "CLOSE:test1" > /dev/ttyS2     # cierra y responde CLOSE:OK:test1
# acercar un objeto a < 50 cm del HC-SR04 -> el ESP32 emite PRESENCE_DETECTED
# cortar el HEARTBEAT 5 s -> emite HARDWARE_FAULT:watchdog_timeout y cierra
```
