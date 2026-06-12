# ESP32.md — Migración del firmware M4 → ESP32 WROOM-32 (manejo de GPIOs vía UART)

> **Documento de contexto + prompt.** Está pensado para abrirse en una sesión de
> Claude Code dentro del repo `parking-edge` y pedirle que genere, desde cero, el
> firmware del **ESP32 WROOM-32** que sustituye al firmware del **Cortex-M4** de la
> BeaglePlay, comunicándose con Linux por **UART** en lugar de RPMsg.
>
> Copia/pega la sección [«PROMPT PARA CLAUDE CODE»](#prompt-para-claude-code) al
> final, o simplemente di: *"Lee ESP32.md y constrúyelo"*.

---

## 1. Por qué existe este documento (contexto del problema)

El proyecto **parking-edge** es un parqueadero inteligente sobre una **BeaglePlay
(AM62x)**. La arquitectura original reparte el trabajo así:

- **Linux (núcleo A53)** → servicios Python: visión (lectura de placa con YOLO),
  orquestación de acceso, pagos, dashboard, base de datos. Se comunican entre sí
  por **MQTT**.
- **Cortex-M4 (núcleo de tiempo real, FreeRTOS)** → manejo *bare-metal* de GPIOs:
  sensor ultrasónico HC-SR04, barrera/servo, watchdog de seguridad. Se comunica
  con Linux por **RPMsg** (`/dev/rpmsg0`).

**El problema:** no se logra cargar (*flashear*) el firmware al M4 de la
BeaglePlay. Como solución de último momento, **se reemplaza el M4 por un módulo
ESP32 WROOM-32 externo** que asume todo el manejo de GPIOs y se comunica con la
BeaglePlay por **UART (serial TTL 3.3 V)**.

**El objetivo de la migración:** que para el resto del sistema (los servicios
Python) **nada cambie conceptualmente**. El `hardware-controller` seguirá enviando
las mismas órdenes de texto y recibiendo los mismos eventos; sólo cambia el
*transporte físico*: de RPMsg (`/dev/rpmsg0`) a UART (`/dev/ttyS*`).

```
ANTES:   [Servicios Python] --MQTT--> [hardware-controller] --RPMsg--> [M4 FreeRTOS] --GPIO--> HC-SR04 / Barrera
AHORA:   [Servicios Python] --MQTT--> [hardware-controller] --UART---> [ESP32 FreeRTOS] --GPIO--> HC-SR04 / Barrera
                                                            (/dev/ttyS*)        ▲
                                                                                └── mismo protocolo de texto
```

---

## 2. Qué hacía el firmware M4 (lógica a migrar literalmente)

El firmware original vive en [firmware/m4/src/](firmware/m4/src/). Se debe replicar
su comportamiento **exacto** sobre ESP32. Resumen de cada módulo:

### 2.1 Sensor ultrasónico HC-SR04 — [sensor_driver.c](firmware/m4/src/sensor_driver.c)
- Pin **TRIGGER** = salida; pin **ECHO** = entrada.
- Medición: pulso de **10 µs** en TRIGGER → medir ancho del pulso HIGH en ECHO →
  `distancia_cm = duracion_us / 58`.
- Timeouts de seguridad: si no llega flanco de subida o el pulso es demasiado
  largo (> ~5 m), retorna `999` (fuera de rango / desconectado).
- Rango válido: descarta lecturas > `MAX_DISTANCE_CM` (400 cm).
- **Tarea continua de monitoreo** (`vTaskSensorUltrasonido`):
  - Muestrea cada **60 ms**.
  - **Debounce espacial:** requiere **3 lecturas consecutivas** por debajo de
    `DISTANCE_THRESHOLD_CM` (**50 cm**) para confirmar presencia.
  - **Debounce temporal:** no vuelve a notificar dentro de **500 ms** de la última
    detección (`DETECTION_DEBOUNCE_MS`).
  - Al confirmar vehículo → envía evento **`PRESENCE_DETECTED`** hacia Linux.

### 2.2 Barrera / servo — [main.c](firmware/m4/src/main.c) + [rpmsg_interface.c](firmware/m4/src/rpmsg_interface.c)
- Pin de barrera = salida digital. **Estado seguro al arranque = LOW (cerrada).**
- `OPEN`  → GPIO HIGH (barrera abierta).
- `CLOSE` → GPIO LOW (barrera cerrada).
- El acceso al GPIO de la barrera está protegido por un **mutex** (`xBarrierMutex`)
  porque lo tocan varias tareas (comandos + watchdog).
- En el M4 la barrera se maneja como **salida digital on/off** (relé / LED /
  driver de servo externo). En ESP32 puedes mantenerla digital **o** usar PWM real
  de servo (ver §4.4). Mantener el contrato OPEN/CLOSE idéntico.

### 2.3 Watchdog de seguridad — [watchdog.c](firmware/m4/src/watchdog.c)
- Timer de software con timeout **`HEARTBEAT_TIMEOUT_MS` = 5000 ms**.
- Linux debe mandar **`HEARTBEAT`** periódicamente (cada 1 s, ver
  [main.py](services/hardware_controller/app/main.py)).
- Cada `HEARTBEAT` recibido **reinicia** el timer (`watchdog_feed`).
- Si pasan 5 s sin heartbeat → **cierra la barrera por seguridad** (GPIO LOW),
  tomando el mutex. Esto evita dejar la barrera abierta si Linux se cuelga.

### 2.4 Transporte — [rpmsg_interface.c](firmware/m4/src/rpmsg_interface.c)
- **Esto es lo único que cambia de fondo:** RPMsg → **UART**.
- En M4 corría una tarea `vTaskRPMsgListener` que bloqueaba esperando líneas.
  En ESP32 será una **tarea que lee del puerto UART** línea por línea.

### 2.5 Pines del M4 (referencia, NO usar en ESP32)
Sólo como referencia histórica — los pines reales del ESP32 están en §4:

| Función           | M4 (BeaglePlay J5)      |
|-------------------|-------------------------|
| TRIGGER HC-SR04   | MCU_GPIO0_0 (J5 pin 1)  |
| ECHO HC-SR04      | MCU_GPIO0_2 (J5 pin 3)  |
| Barrera/servo     | MCU_GPIO0_8 (J5 pin 9)  |

---

## 3. Contrato de protocolo (UART) — **no cambiar, es la fuente de verdad**

El lado Python ya está escrito y **define el contrato**. Mira
[rpmsg_client.py](services/hardware_controller/app/rpmsg_client.py) y
[command_dispatcher.py](services/hardware_controller/app/command_dispatcher.py).
El ESP32 debe hablar **exactamente** este protocolo.

- **Codificación:** texto ASCII/UTF-8, una orden/evento **por línea**, terminada en
  `'\n'`. Sin tramas binarias.
- **Baud rate recomendado:** **115200 8N1** (definir igual en ESP32 y en la Beagle).

### 3.1 Linux (BeaglePlay) → ESP32

| Mensaje              | Significado                                  | Acción en ESP32                          |
|----------------------|----------------------------------------------|------------------------------------------|
| `HEARTBEAT\n`        | Latido de vida de Linux (cada ~1 s)          | `watchdog_feed()` (reinicia timer 5 s)   |
| `OPEN:<trace_id>\n`  | Abrir barrera                                | GPIO barrera HIGH + responder `OPEN:OK:<trace_id>`   |
| `CLOSE:<trace_id>\n` | Cerrar barrera                               | GPIO barrera LOW + responder `CLOSE:OK:<trace_id>`   |
| `STOP:<trace_id>\n`  | Parada/estado seguro (tratar como CLOSE)     | GPIO barrera LOW + responder `STOP:OK:<trace_id>`    |

> Nota: el `<trace_id>` es un UUID corto de trazabilidad. El ESP32 **debe
> devolverlo tal cual** en la respuesta. El `HEARTBEAT` que envía Python lleva el
> texto literal `HEARTBEAT:heartbeat\n` (acción `HEARTBEAT`, trace_id `heartbeat`);
> el ESP32 debe reconocer una línea que **empiece por `HEARTBEAT`** como latido y
> NO responder nada a ella (sólo alimentar el watchdog).

### 3.2 ESP32 → Linux (BeaglePlay)

| Mensaje                          | Cuándo                                              | Efecto en Python                          |
|----------------------------------|-----------------------------------------------------|-------------------------------------------|
| `PRESENCE_DETECTED\n`            | Vehículo confirmado por HC-SR04                     | Publica `parking/events/presence_detected` (arranca visión) |
| `OPEN:OK:<trace_id>\n`           | Barrera abierta con éxito                           | Publica `barrier_opened`                  |
| `CLOSE:OK:<trace_id>\n`          | Barrera cerrada con éxito                           | Publica `barrier_closed`                  |
| `<ACTION>:FAULT:<trace_id>\n`    | El comando falló (no se pudo accionar)              | Publica `hardware_fault`                  |
| `HARDWARE_FAULT:<reason>\n`      | Fallo autónomo (p.ej. watchdog, sensor muerto)      | Publica `hardware_fault`                  |

> El parser de Python (`_on_m4_message`) divide por `:`. Reglas que debes respetar:
> - `PRESENCE_DETECTED` se compara como línea exacta.
> - `HARDWARE_FAULT:<reason>` → `parts[0] == "HARDWARE_FAULT"`.
> - Respuestas a comandos son **siempre** `ACTION:STATUS:trace_id` (3 partes mínimo,
>   `STATUS` ∈ {`OK`, `FAULT`}).
> - Cualquier otra línea se ignora con un warning → no envíes ruido por UART
>   (los logs de debug del ESP32 deben ir por **UART0/USB**, NO por el UART de datos).

### 3.3 Eventos de watchdog
Cuando el watchdog cierre la barrera por timeout, el ESP32 **debería** notificar a
Linux con `HARDWARE_FAULT:watchdog_timeout\n` además de cerrar el GPIO, para que el
sistema registre el evento. (El M4 original sólo lo logueaba localmente; aquí lo
mejoramos porque ahora hay un canal de salida fácil.)

---

## 4. Hardware — ESP32 WROOM-32

### 4.1 Asignación de pines propuesta (ESP32 DevKit v1, 30/38 pines)

| Función                | GPIO ESP32 | Notas                                                        |
|------------------------|------------|--------------------------------------------------------------|
| HC-SR04 **TRIGGER**    | **GPIO 5** | Salida digital.                                              |
| HC-SR04 **ECHO**       | **GPIO 18**| Entrada. **Requiere divisor de voltaje 5 V→3.3 V** (ver §4.3)|
| **Barrera / servo**    | **GPIO 19**| Salida digital (o PWM si es servo, §4.4). LOW al arranque.   |
| **UART2 TX** (→ Beagle)| **GPIO 17**| TX2 del ESP32 → RX de la Beagle.                             |
| **UART2 RX** (← Beagle)| **GPIO 16**| RX2 del ESP32 ← TX de la Beagle.                             |
| UART0 TX/RX (debug)    | GPIO 1 / 3 | **Reservado** para logs por USB. No usar para datos.         |
| GND común              | GND        | **Imprescindible**: GND ESP32 ↔ GND Beagle ↔ GND HC-SR04.    |

> Evita los GPIO 6–11 (conectados a la flash SPI) y ten en cuenta que GPIO 34–39
> son **sólo entrada**. Los pines elegidos arriba son seguros.

### 4.2 Cableado UART ESP32 ↔ BeaglePlay (¡cruzado!)

```
   ESP32 (UART2)              BeaglePlay (UART de expansión, 3.3 V TTL)
   ─────────────              ────────────────────────────────────────
   GPIO17 (TX2)  ───────────►  RX
   GPIO16 (RX2)  ◄───────────  TX
   GND           ───────────   GND   (común, obligatorio)
```

- **Ambos lados son 3.3 V TTL** → conexión directa, sin level shifter entre ESP32
  y Beagle.
- **NO conectar 5 V ni VBUS** entre placas; sólo TX, RX y GND.
- En la BeaglePlay hay que **identificar y habilitar el UART** expuesto (header
  Grove/expansión o mikroBUS). El dispositivo en Linux suele ser `/dev/ttyS2`,
  `/dev/ttyS4` u `/dev/ttyO*` según el overlay/pinmux. **Verificar con**
  `dmesg | grep tty` y `ls -l /dev/ttyS*`. Documentar el device real elegido.

### 4.3 HC-SR04 — divisor de voltaje en ECHO (crítico)
El HC-SR04 se alimenta con **5 V** y su pin **ECHO entrega 5 V**, pero los GPIO del
ESP32 **no son tolerantes a 5 V**. Hay que bajar ECHO a ~3.3 V:

```
   ECHO (5V) ──[ R1 = 1 kΩ ]──┬── GPIO18 (ESP32, 3.3V)
                              │
                         [ R2 = 2 kΩ ]
                              │
                             GND
```
- TRIGGER (GPIO5 → HC-SR04) puede ir directo: un 3.3 V se interpreta como HIGH.
- Alimentar el HC-SR04 desde **VIN/5V** del ESP32 (USB) o fuente externa de 5 V con
  GND común.

### 4.4 Barrera: digital vs servo PWM
- **Opción A (fiel al M4, recomendada para empezar):** salida digital on/off en
  GPIO19 → relé o LED indicador. `OPEN`=HIGH, `CLOSE`=LOW.
- **Opción B (servo real SG90/MG90):** usar PWM (librería `ESP32Servo` o `ledc`),
  p.ej. `OPEN`=90°, `CLOSE`=0°. El contrato OPEN/CLOSE no cambia; sólo la capa
  física. Alimentar el servo con 5 V externos (no del 3.3 V) y GND común.

---

## 5. Arquitectura de software del ESP32

**Framework recomendado:** **Arduino-ESP32** (sobre **PlatformIO**, o Arduino IDE
si se prefiere). El ESP32 ya trae **FreeRTOS**, así que se puede replicar el diseño
de tareas del M4 casi 1:1. Es la vía más rápida para una solución de último momento.

### 5.1 Estructura de tareas (FreeRTOS, igual que el M4)

| Tarea                | Prioridad | Responsabilidad                                              |
|----------------------|-----------|--------------------------------------------------------------|
| `TaskUartListener`   | alta      | Lee líneas de UART2, parsea y despacha (HEARTBEAT/OPEN/CLOSE/STOP). |
| `TaskSensor`         | media     | Bucle HC-SR04 cada 60 ms con doble debounce → emite `PRESENCE_DETECTED`. |
| Watchdog (timer SW)  | —         | `xTimerCreate` con timeout 5 s; al expirar cierra barrera + `HARDWARE_FAULT:watchdog_timeout`. |

- **Mutex** `xBarrierMutex` para proteger el GPIO de la barrera (comandos UART vs
  watchdog), igual que en el M4.
- **Mutex/serialización de escritura UART**: todas las respuestas y eventos
  ESP32→Beagle deben escribirse atómicamente (una línea completa) para no
  entrelazar mensajes de distintas tareas. Usar un mutex de TX o centralizar el
  envío en una función `uart_send_line()` protegida.
- Logs de depuración del ESP32 → **`Serial` (UART0/USB)**, nunca por `Serial2`.

### 5.2 Organización de archivos sugerida
```
firmware/esp32/
├── platformio.ini            # entorno esp32dev, framework arduino, monitor 115200
├── src/
│   └── main.cpp              # setup() + creación de tareas FreeRTOS
├── include/
│   ├── config.h             # pines, umbrales, baud, timeouts (espejo de M4 config.h)
│   ├── sensor.h
│   ├── barrier.h
│   ├── watchdog.h
│   └── uart_protocol.h
├── lib/                      # (opcional) si se modulariza
└── README.md                # cómo compilar/flashear y cómo cablear
```
> Mantener constantes en `config.h` con los **mismos nombres y valores** que el M4
> (`DISTANCE_THRESHOLD_CM=50`, `SENSOR_SAMPLE_PERIOD_MS=60`, `DEBOUNCE_READINGS=3`,
> `DETECTION_DEBOUNCE_MS=500`, `HEARTBEAT_TIMEOUT_MS=5000`, `MAX_DISTANCE_CM=400`).

### 5.3 Pseudocódigo del listener UART
```cpp
// TaskUartListener
String line;
while (true) {
  if (readLineFromSerial2(line)) {        // hasta '\n', con timeout no bloqueante
    line.trim();
    if (line.startsWith("HEARTBEAT")) {
      watchdog_feed();                     // NO responder
    } else if (line.startsWith("OPEN:"))  { handleCommand("OPEN",  trace_id(line)); }
    else if  (line.startsWith("CLOSE:")) { handleCommand("CLOSE", trace_id(line)); }
    else if  (line.startsWith("STOP:"))  { handleCommand("STOP",  trace_id(line)); }
    // cualquier otra línea: ignorar (o log por UART0)
  }
}

void handleCommand(action, trace_id) {
  bool ok = takeBarrierMutex(100ms);
  if (ok) {
    if (action == "OPEN") barrier_open(); else barrier_close(); // STOP == close
    giveBarrierMutex();
    uart_send_line(action + ":OK:" + trace_id);
  } else {
    uart_send_line(action + ":FAULT:" + trace_id);
  }
}
```

---

## 6. Cambios en el lado BeaglePlay (Python) para acoplar UART

El transporte cambia de RPMsg a UART, pero el `command_dispatcher` y el protocolo
de texto **no deben cambiar**. Hay dos formas; **elige la opción A** (mínima):

### Opción A — Reutilizar `RPMsgClient` apuntando al UART (cambio casi nulo)
`RPMsgClient` abre el device con `os.open()` y lee/escribe líneas crudas. Un
`/dev/ttyS*` funciona con esa misma API **si antes se configura el baud rate** con
`stty` o `termios`. Pasos:
1. En `app.env`: `RPMSG_DEVICE=/dev/ttyS2` (el UART real de la Beagle).
2. Configurar el puerto una vez al arranque (baud 115200, raw):
   `stty -F /dev/ttyS2 115200 raw -echo` (o equivalente con `termios` en Python).
3. Verificar permisos (`dialout`/`tty` group) para el usuario del servicio.

> ⚠️ Limitación: `os.open` no fija el baud rate; conviene fijarlo con `stty`/overlay
> o migrar a la opción B para que sea autocontenido.

### Opción B — Nuevo `SerialClient` con `pyserial` (más robusto, recomendado)
Crear `services/hardware_controller/app/serial_client.py` con **la misma interfaz
pública** que `RPMsgClient` (`open()`, `close()`, `send_command(action, trace_id)`,
`set_message_callback(cb)`), pero implementado con `pyserial`:
- `serial.Serial(port=UART_DEVICE, baudrate=115200, timeout=...)`.
- Hilo lector que parte por `\n` e invoca el callback (idéntico a `_reader_loop`).
- `send_command` escribe `f"{action.upper()}:{trace_id}\n".encode()`.
- Mantener el **modo simulado** si el puerto no existe (para desarrollo sin ESP32).
- En [main.py](services/hardware_controller/app/main.py): cambiar la instanciación
  `RPMsgClient()` por `SerialClient()` (misma firma → el resto no cambia).
- Añadir `pyserial` a `requirements.txt`.
- Nuevas env: `UART_DEVICE=/dev/ttyS2`, `UART_BAUDRATE=115200`,
  `UART_SIMULATED=false` (espejo de las `RPMSG_*`).

El `CommandDispatcher` **no se toca**: ya envía `OPEN:<trace_id>` y entiende
`PRESENCE_DETECTED`, `ACTION:OK:trace_id`, `HARDWARE_FAULT:...`.

---

## 7. Plan de pruebas / criterios de aceptación

1. **Bring-up UART:** desde la Beagle, `echo "OPEN:test1" > /dev/ttyS2` → el ESP32
   abre la barrera y responde `OPEN:OK:test1` (verlo con `cat /dev/ttyS2` o en el
   monitor del ESP32 por USB).
2. **Heartbeat/watchdog:** con el `hardware-controller` corriendo (manda HEARTBEAT
   cada 1 s) la barrera permanece controlable. Al **cortar** el heartbeat, a los 5 s
   el ESP32 cierra la barrera y emite `HARDWARE_FAULT:watchdog_timeout`.
3. **Presencia:** acercar un objeto a < 50 cm del HC-SR04 durante ≥ 3 lecturas →
   el ESP32 emite **una sola** `PRESENCE_DETECTED` (respetando el debounce de
   500 ms), y el dashboard/visión reacciona.
4. **OPEN/CLOSE end-to-end:** publicar `parking/events/access_granted` en MQTT →
   `hardware-controller` manda `OPEN:<trace_id>` → ESP32 abre → responde
   `OPEN:OK:<trace_id>` → se publica `barrier_opened`.
5. **Robustez de parseo:** líneas vacías, parciales o ruido no deben colgar el
   listener ni accionar la barrera por error.
6. **Modo simulado Python** sigue funcionando sin ESP32 conectado.

---

## 8. PROMPT PARA CLAUDE CODE

> Pega esto (o di *"haz lo que dice ESP32.md"*) en una sesión nueva de Claude Code
> abierta en la raíz del repo `parking-edge`.

```
Lee ESP32.md completo y también el firmware M4 original en firmware/m4/src/
(main.c, config.h, sensor_driver.c/.h, watchdog.c/.h, rpmsg_interface.c/.h) y el
lado Python en services/hardware_controller/app/ (main.py, rpmsg_client.py,
command_dispatcher.py).

Tarea: migrar TODO el manejo de GPIOs del Cortex-M4 a un ESP32 WROOM-32 que se
comunica con la BeaglePlay por UART (115200 8N1, líneas terminadas en '\n'),
respetando EXACTAMENTE el protocolo de texto descrito en la sección 3 de ESP32.md
(es el contrato que el lado Python ya espera; no lo cambies).

Entregables:
1. Firmware ESP32 en firmware/esp32/ usando PlatformIO + framework Arduino-ESP32,
   con FreeRTOS, replicando 1:1 la lógica del M4:
   - Driver HC-SR04 (trigger 10us, medición de eco, distancia=us/58, timeouts,
     retorno 999 fuera de rango).
   - Tarea de sensor cada 60 ms con doble debounce (3 lecturas < 50 cm + 500 ms
     entre eventos) que emite PRESENCE_DETECTED.
   - Control de barrera digital (GPIO19, LOW al arranque) protegido por mutex,
     comandos OPEN/CLOSE/STOP con respuesta ACTION:OK:trace_id (o ACTION:FAULT:...).
   - Watchdog de software (timeout 5 s): si no llega HEARTBEAT, cierra barrera y
     emite HARDWARE_FAULT:watchdog_timeout.
   - Tarea listener UART2 (RX=GPIO16, TX=GPIO17) que parsea líneas; logs de debug
     SOLO por UART0/USB, jamás por el UART de datos.
   - Mantén las constantes de config.h con los mismos nombres/valores que el M4.
   - Incluye firmware/esp32/README.md con cableado (incluido el divisor de voltaje
     del ECHO), cómo compilar y cómo flashear.
2. Acople en la BeaglePlay (Python): implementa la Opción B de la sección 6 — crea
   services/hardware_controller/app/serial_client.py con pyserial y la MISMA
   interfaz pública que RPMsgClient (open/close/send_command/set_message_callback,
   con modo simulado), cambia main.py para usarlo, añade pyserial a requirements,
   y agrega las variables UART_DEVICE/UART_BAUDRATE/UART_SIMULATED a
   config/app.env.example. NO modifiques command_dispatcher.py.

Restricciones:
- No rompas el modo simulado de Python (debe seguir arrancando sin ESP32).
- Comenta el código en español, igual que el resto del repo.
- Al terminar, dame los pasos exactos de flasheo del ESP32 y de configuración del
  UART en la BeaglePlay (stty/permisos), y la checklist de pruebas de la sección 7.
```

---

## 9. Referencias rápidas del repo

| Qué                          | Dónde                                                                 |
|------------------------------|-----------------------------------------------------------------------|
| Firmware M4 (origen)         | [firmware/m4/src/](firmware/m4/src/)                                  |
| Cliente transporte (Python)  | [rpmsg_client.py](services/hardware_controller/app/rpmsg_client.py)  |
| Despachador de comandos      | [command_dispatcher.py](services/hardware_controller/app/command_dispatcher.py) |
| Arranque hardware-controller | [main.py](services/hardware_controller/app/main.py)                  |
| Tópicos/eventos MQTT         | [event_models.py](services/common/event_models.py)                   |
| Variables de entorno         | [config/app.env.example](config/app.env.example)                     |
