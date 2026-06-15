# 📌 PINES UTILIZADOS - ESP32 C6

**Proyecto:** Parqueadero Inteligente  
**Hardware:** ESP32 C6  
**Periféricos:** HC-SR04 (sensor ultrasónico), Servo (barrera), UART (comunicación)

---

## 🔌 Tabla Resumen de Pines

### Entrada/Salida de GPIOs

| Puerto | GPIO | Función | Tipo | Descripción |
|--------|------|---------|------|-------------|
| **1** | GPIO 4 | HC-SR04 TRIGGER | Salida digital | Pulso de 10 µs para medir distancia |
| **2** | GPIO 5 | HC-SR04 ECHO | Entrada digital | Recibe ancho de pulso (requiere divisor 5V→3.3V) |
| **3** | GPIO 6 | Servo BARRIER PWM | Salida PWM (LEDC) | Control de barrera (0°=cerrado, 90°=abierto) |

### Comunicación Serial (UART)

| Puerto | GPIO | Función | Descripción |
|--------|------|---------|-------------|
| **UART1 TX** | GPIO 2 | Transmisión a BeaglePlay | Envía ordenes confirmadas y eventos |
| **UART1 RX** | GPIO 3 | Recepción desde BeaglePlay | Recibe HEARTBEAT, OPEN, CLOSE, STOP |

### Depuración (UART0 USB)

| Puerto | GPIO | Función | Descripción |
|--------|------|---------|-------------|
| **UART0 TX** | GPIO 21 | Depuración | Logs en Serial Monitor (115200 baud) |

---

## 🔋 Alimentación y Tierra

| Señal | Descripción |
|-------|-------------|
| **GND** | Tierra común (ESP32 ↔ BeaglePlay ↔ HC-SR04 ↔ Servo) |
| **5V (VIN)** | Alimenta HC-SR04 (desde USB del ESP32 o fuente externa) |
| **3.3V (3V3)** | Alimenta periféricos digitales del ESP32 |

> ⚠️ **Servo:** Requiere **5V de POTENCIA externa** (no del 3.3V del ESP32)

---

## 📐 Esquema de Conexiones

### HC-SR04 Sensor Ultrasónico

```
HC-SR04                          ESP32 C6
  │
  ├─ VCC ────────────────────► 5V (VIN)
  ├─ GND ────────────────────► GND
  ├─ TRIG ────────────────────► GPIO 4
  └─ ECHO (5V) ────┬───────────► GPIO 5 (con divisor)
                   │
                 [ R1=1kΩ ]
                   │
                   ├─►GPIO 5 (3.3V)
                 [ R2=2kΩ ]
                   │
                  GND
```

### Servo Barrera

```
Servo SG90/MG90          ESP32 C6
  │
  ├─ Signal (amarillo)─────► GPIO 6 (PWM)
  ├─ VCC (rojo) ───────────► 5V EXTERNO (NOT 3.3V)
  └─ GND (negro/marrón)────► GND (común)
```

### UART Beagle ↔ ESP32 (Cableado Cruzado)

```
BeaglePlay                    ESP32 C6
  │
  ├─ TX ──────────────────► GPIO 3 (RX1)
  ├─ RX ◄────────────────── GPIO 2 (TX1)
  └─ GND ─────────────────── GND (común)

Baud Rate: 115200 bps
Formato: 8N1 (8 bits, sin paridad, 1 stop)
```

---

## 📋 Configuración de Software (config.h)

```c
/* HC-SR04 */
#define TRIGGER_PIN_NUM         (4)      // GPIO 4
#define ECHO_PIN_NUM            (5)      // GPIO 5 (con divisor)

/* Servo PWM */
#define SERVO_BARRIER_PIN_NUM   (6)      // GPIO 6
#define SERVO_LEDC_CHANNEL      (0)      // LEDC Channel 0
#define SERVO_LEDC_FREQ_HZ      (50)     // 50 Hz para servo
#define SERVO_CLOSE_US          (1000)   // 0° en 1000 µs
#define SERVO_OPEN_US           (1500)   // 90° en 1500 µs

/* UART1 */
#define UART_BEAGLE_RX_PIN      (3)      // GPIO 3 (RX1)
#define UART_BEAGLE_TX_PIN      (2)      // GPIO 2 (TX1)
#define UART_BEAGLE_BAUD        (115200) // Baudrate
```

---

## ✅ Validación de Pines

| Criterio | Estado |
|----------|--------|
| GPIO 2-6 disponibles en ESP32 C6 | ✅ SÍ |
| No son strapping pins | ✅ SÍ |
| Soportan las funcionalidades necesarias | ✅ SÍ |
| LEDC PWM en GPIO 6 | ✅ SÍ |
| UART1 en GPIO 2/3 | ✅ SÍ |
| Divisor 5V→3.3V para ECHO | ✅ REQUERIDO |
| GND común en todas las conexiones | ✅ OBLIGATORIO |

---

## 🔧 Compilación y Flasheo

```bash
# Compilar para ESP32 C6
pio run -e esp32c6dev -t upload

# Monitorear UART0 (depuración)
pio device monitor -b 115200
```

---

## 📖 Referencias

- **Datasheet ESP32 C6:** https://www.espressif.com/sites/default/files/documentation/esp32-c6_datasheet_en.pdf
- **HC-SR04 Datasheet:** https://cdn.sparkfun.com/datasheets/Sensors/Proximity/HCSR04.pdf
- **Servo SG90 Pinout:** https://components101.com/motors/servo-motor-pinout-connection

---

## 📝 Historial

| Fecha | Cambio | GPIO Anterior | GPIO Nuevo |
|-------|--------|---------------|------------|
| 2026-06-15 | Migración WROOM→C6 | GPIO 5,18,19,16,17 | GPIO 4,5,6,2,3 |

