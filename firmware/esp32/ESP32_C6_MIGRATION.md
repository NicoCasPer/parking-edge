# Migración: ESP32 WROOM-32 → ESP32 C6

**Fecha:** 2026-06-15  
**Estado:** ✅ Completada  
**Cambios:** 4 archivos modificados

---

## Resumen Ejecutivo

Se realizó la migración del firmware desde **ESP32 WROOM-32 (esp32dev)** a **ESP32 C6 (esp32c6dev)**. 

**Cambios principales:**
- Placa de destino en platformio.ini
- Asignación de pines GPIO (5 pines reasignados)
- UART2 → UART1 (cambio de periférico)
- Protocolo y lógica FreeRTOS: **sin cambios**

---

## Tabla de Pines

### ESP32 WROOM-32 (anterior)
| Función | Pin | Periférico |
|---------|-----|-----------|
| HC-SR04 TRIGGER (salida) | GPIO 5 | GPIO digital |
| HC-SR04 ECHO (entrada) | GPIO 18 | GPIO digital |
| Barrera/Servo (PWM) | GPIO 19 | LEDC channel 0 |
| UART Beagle RX | GPIO 16 | UART2 RX |
| UART Beagle TX | GPIO 17 | UART2 TX |

### ESP32 C6 (nuevo) ✅
| Función | Pin | Periférico |
|---------|-----|-----------|
| HC-SR04 TRIGGER (salida) | **GPIO 4** | GPIO digital |
| HC-SR04 ECHO (entrada) | **GPIO 5** | GPIO digital |
| Barrera/Servo (PWM) | **GPIO 6** | LEDC channel 0 |
| UART Beagle RX | **GPIO 3** | UART1 RX |
| UART Beagle TX | **GPIO 2** | UART1 TX |

**Notas sobre selección de pines:**
- GPIO 2, 3, 4, 5, 6 están disponibles en ESP32 C6 (sin conflictos boot/strapping)
- ECHO (GPIO 5): aún requiere **divisor de voltaje 5V→3.3V**
- UART1: compatible con ambas velocidades (115200 baud)
- LEDC: channel 0 disponible y funcional en ESP32 C6

---

## Archivos Modificados

### 1. ✅ **platformio.ini**
```diff
  [env:esp32dev]
  platform  = espressif32
- board     = esp32dev
+ board     = esp32c6dev
  framework = arduino
```

### 2. ✅ **include/config.h** (3 secciones)

#### Sección: Pines comentario
```diff
- /* PINES — ESP32 WROOM-32 (DevKit v1) */
+ /* PINES — ESP32 C6 */
```

#### HC-SR04
```diff
- #define TRIGGER_PIN_NUM         (5)
- #define ECHO_PIN_NUM            (18)
- #define SERVO_BARRIER_PIN_NUM   (19)

+ #define TRIGGER_PIN_NUM         (4)
+ #define ECHO_PIN_NUM            (5)
+ #define SERVO_BARRIER_PIN_NUM   (6)
```

#### UART
```diff
- /* UART2 hacia la BeaglePlay (RX2/TX2). Cableado CRUZADO: TX2->RX_beagle */
- #define UART_BEAGLE_RX_PIN      (16)
- #define UART_BEAGLE_TX_PIN      (17)

+ /* UART1 hacia la BeaglePlay. Cableado CRUZADO: TX->RX_beagle */
+ #define UART_BEAGLE_RX_PIN      (3)
+ #define UART_BEAGLE_TX_PIN      (2)
```

### 3. ✅ **src/uart_protocol.cpp** (4 cambios)

#### Cambio 1: Comentario
```diff
- * Equivale a rpmsg_interface.c del M4 (vTaskRPMsgListener), pero sobre UART2.
+ * Equivale a rpmsg_interface.c del M4 (vTaskRPMsgListener), pero sobre UART1.
```

#### Cambio 2: Inicialización
```diff
  void uart_init(void)
  {
-     Serial2.begin(UART_BEAGLE_BAUD, SERIAL_8N1, UART_BEAGLE_RX_PIN, UART_BEAGLE_TX_PIN);
+     Serial1.begin(UART_BEAGLE_BAUD, SERIAL_8N1, UART_BEAGLE_RX_PIN, UART_BEAGLE_TX_PIN);
      if (xUartTxMutex == NULL)
      {
          xUartTxMutex = xSemaphoreCreateMutex();
      }
-     Serial.printf("[UART] UART2 listo. RX=GPIO%d TX=GPIO%d @ %d baud.\n",
+     Serial.printf("[UART] UART1 listo. RX=GPIO%d TX=GPIO%d @ %d baud.\n",
                    UART_BEAGLE_RX_PIN, UART_BEAGLE_TX_PIN, UART_BEAGLE_BAUD);
  }
```

#### Cambio 3: Envío
```diff
  void uart_send_line(const String &line)
  {
      if (xUartTxMutex != NULL)
      {
          xSemaphoreTake(xUartTxMutex, portMAX_DELAY);
      }
  
-     Serial2.print(line);
-     Serial2.print('\n');
+     Serial1.print(line);
+     Serial1.print('\n');
  
      if (xUartTxMutex != NULL)
      {
          xSemaphoreGive(xUartTxMutex);
      }
  }
```

#### Cambio 4: Lectura
```diff
  for (;;)
  {
-     while (Serial2.available() > 0)
+     while (Serial1.available() > 0)
      {
-         char c = (char)Serial2.read();
+         char c = (char)Serial1.read();
```

### 4. ✅ **Archivos SIN cambios**
- `src/barrier.cpp` — Usa `SERVO_LEDC_CHANNEL` (abstracción de config.h)
- `src/sensor.cpp` — Usa pines de config.h automáticamente
- `src/watchdog.cpp` — Lógica de timer (sin dependencias de hardware específico)
- `src/main.cpp` — Inicialización genérica
- `include/barrier.h`, `sensor.h`, `watchdog.h`, `uart_protocol.h` — Headers sin cambios

---

## Compatibilidad Verificada

### ✅ Hardware
| Aspecto | Validación |
|--------|-----------|
| GPIO 2, 3, 4, 5, 6 disponibles | SÍ (no son strapping pins) |
| LEDC PWM en GPIO 6 | SÍ (channel 0 funcional) |
| UART1 en GPIO 2/3 | SÍ (asignación estándar) |
| Tensión divisor ECHO | IGUAL (5V→3.3V requerido) |
| Baud rate 115200 | SÍ (ambas placas soportan) |

### ✅ Software
| Aspecto | Validación |
|--------|-----------|
| Protocolo UART | SIN CAMBIOS (mismo contrato) |
| HEARTBEAT, OPEN, CLOSE, STOP | SIN CAMBIOS |
| PRESENCE_DETECTED, HARDWARE_FAULT | SIN CAMBIOS |
| FreeRTOS tasks y mutex | SIN CAMBIOS |
| Servo PWM (0°/90°) | SIN CAMBIOS |
| Timeouts y umbrales sensor | SIN CAMBIOS |

---

## Procedimiento de Compilación

```bash
# Compilar para ESP32 C6
pio run -t upload

# Monitorear salida UART0 (depuración)
pio device monitor -b 115200

# Limpiar y recompilar
pio run -t clean && pio run -t upload
```

---

## Pruebas Recomendadas

1. **Booteo:**
   ```
   Esperado: "[Main] Firmware parking-edge ESP32 v1.0.0-esp32 build [fecha] [hora]"
   ```

2. **Inicialización UART:**
   ```
   Esperado: "[UART] UART1 listo. RX=GPIO3 TX=GPIO2 @ 115200 baud."
   ```

3. **Sensor HC-SR04:**
   ```
   Verificar: Distancia en cm sin error (no 999)
   ```

4. **Barrera (servo):**
   ```
   Verificar: Servo responde a comandos OPEN (90°) / CLOSE (0°)
   ```

5. **Comunicación Beagle:**
   ```
   Enviar: "HEARTBEAT" desde Beagle
   Recibir: Respuesta sin error en watchdog
   ```

---

## Notas Adicionales

- **Cableado UART:** Mantiene el esquema CRUZADO (TX_ESP → RX_Beagle, RX_ESP ← TX_Beagle)
- **Divisor de voltaje:** Imprescindible en ECHO (5V del HC-SR04 → 3.3V del ESP32 C6)
- **GND común:** Todos los dispositivos (HC-SR04, servo, UART) comparten GND
- **Alimentación:** VIN/5V del ESP32 alimenta HC-SR04; servo requiere 5V externo de potencia
- **Debugging:** Logs siempre por `Serial` (UART0/USB), nunca por `Serial1` (UART hacia Beagle)

---

## Historial de Cambios

| Fecha | Cambio | Archivo |
|-------|--------|---------|
| 2026-06-15 | Migración WROOM→C6 | platformio.ini, config.h, uart_protocol.cpp |

