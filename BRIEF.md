# Brief para los guiones del video de presentación

> Documento de contexto para generar **2 guiones** de video del proyecto **parking-edge**.
> Pensado para que otra IA (o el propio equipo) escriba los guiones con toda la información necesaria.
> El detalle técnico vive en [README.md](README.md) y [firmware/esp32/README.md](firmware/esp32/README.md).

---

## 1. Objetivo y audiencia

- **Contexto:** proyecto de una materia universitaria.
- **Audiencia:** el profesor de la materia. Conoce de ingeniería → **tono técnico y conciso**, sin relleno comercial.
- **Tono:** explicar decisiones de ingeniería y *por qué*, no solo *qué*. Mostrar dominio del sistema.

## 2. Formato

- **2 guiones**, uno por cada integrante del equipo (somos 2).
- **Duración objetivo:** ~8 minutos cada uno.
- Cada integrante presenta su parte; juntos cubren el sistema completo sin solaparse.

## 3. Recursos disponibles para mostrar en pantalla

- ✅ **Hardware armado**: BeaglePlay + ESP32 WROOM-32 + sensor HC-SR04 + **LED PWM que simula la barrera** + cámara USB.
- ✅ **Dashboard corriendo**: panel web con eventos en tiempo real, **vista en vivo de la cámara**, whitelist, override de barrera y tabla de pagos.
- ✅ **Diagramas / slides**: diagrama de arquitectura del README, tabla de tópicos MQTT, tabla de bugs corregidos.
- (Opcional) Modo simulado (`UART_SIMULATED=true`, `MOCK_PAYMENT_SERVER=true`) para una demo controlada sin depender del hardware en vivo.

> **Para grabar la demo en vivo:**
> - Arrancar todo con `bash scripts/run_demo.sh` (un solo terminal).
> - Mostrar la placa **impresa en papel mate**, de frente y bien iluminada — sube la
>   confianza del OCR y la lectura es fiable (en pantalla hay brillo/moiré que falla).
> - Tener listas las placas de demo de la sección 9b (whitelist, pago y denegada).

## 4. Problema / motivación (gancho inicial)

Control de acceso a un parqueadero **automatizado por reconocimiento de placas**, capaz de operar en el borde (*edge*), de forma **segura ante fallos** y **sin depender de la nube** para la decisión de acceso. Reemplaza tickets/tarjetas y operación manual de la barrera.

## 5. Qué hace el sistema (resumen de una frase)

Una cámara lee la placa del vehículo; el sistema decide el acceso según whitelist o pago; y abre la barrera — todo coordinado en el borde entre un gateway Linux (BeaglePlay) y un microcontrolador de tiempo real (ESP32).

## 6. Arquitectura en una línea

`ESP32 (HC-SR04 + barrera simulada con LED PWM, FreeRTOS) ⇄ UART ⇄ hardware-controller ⇄ MQTT ⇄ vision-service (TFLite + OCR, cámara en vivo) / access-orchestrator (whitelist+pago) / payment-integration / web-dashboard`

## 7. Puntos técnicos fuertes a destacar

1. **Arquitectura de microservicios desacoplados por MQTT** — cada servicio hace una cosa; el bus de eventos los integra.
2. **Visión en el borde**: YOLO11m cuantizado **INT8 con TensorFlow Lite** + OCR Tesseract sobre cámara USB. Hablar de por qué INT8 (rendimiento en ARM sin GPU) y de la optimización **multi-hilo de TFLite** (de ~12–17 s a ~5 s por inferencia usando los 4 núcleos A53).
   - El pipeline real: sesión de cámara en vivo → 1 detección YOLO (caja) → **varios intentos de OCR** sobre frames frescos → validación de formato `AAA999` → decisión. Buen ejemplo de optimización en hardware limitado.
3. **Separación tiempo real / lógica**: el ESP32 (FreeRTOS) garantiza la respuesta dura del sensor y la barrera; Linux hace la inteligencia. Comunicación por UART.
   - La barrera se **simula con un LED por PWM**: respiración ~5 s al abrir, encendido fijo mientras abre, respiración ~5 s al cerrar hasta apagarse. El auto-cierre tras 5 s sin vehículo vive en el ESP32 con su propio HC-SR04.
   - **Cámara en vivo**: al detectar un vehículo, el vision-service abre una sesión, transmite los frames al dashboard y, apenas YOLO+OCR leen una placa clara, dispara la decisión de acceso.
4. **Seguridad ante fallos (FAIL-CLOSED)**: cualquier error en OCR/lógica → se **deniega** el acceso (`fault_policy: deny`).
5. **Watchdog de hardware**: si Linux no responde en 5 s, el ESP32 cierra la barrera por su cuenta.
6. **Resiliencia de pagos**: circuit breaker + store-and-forward (cola offline) cuando el proveedor de pagos falla.
7. **Migración M4F → ESP32**: decisión de ingeniería real (simplicidad de cableado, depuración y flasheo). Bonus de honestidad técnica frente al jurado.
8. **Calidad / depuración real**: tabla de bugs corregidos (C1–A6 y V1–V9) — integración, FAIL-CLOSED, mutex en GPIO, escala de cajas YOLO, OCR (whitelist que rompía el LSTM, color vs binarizado), TFLite multi-hilo, validador alineado a la BD. Excelente material para mostrar **proceso de ingeniería y debugging sistemático**.

## 8. Propuesta de división entre los 2 integrantes

> Sugerencia editable. La idea es que cada uno tenga ~8 min coherentes y sin solape.

**Guion A — "Percepción y borde" (Integrante 1):**
- Problema y visión general del sistema (gancho).
- Hardware: ESP32 + HC-SR04 + barrera simulada con LED PWM + cámara USB; por qué ESP32 vía UART (migración desde M4F).
- Visión por computadora: pipeline YOLO11m INT8 (TFLite) + Tesseract OCR; por qué INT8 en el borde.
- Demo: detección de placa en vivo / simulada.

**Guion B — "Decisión, integración y operación" (Integrante 2):**
- Arquitectura de microservicios y bus MQTT (recorrer los tópicos).
- Lógica de acceso: whitelist + pago, política FAIL-CLOSED, watchdog.
- Resiliencia de pagos (circuit breaker + cola offline).
- Dashboard en vivo (eventos, override, whitelist) + cierre con calidad/bugs corregidos.

## 9. Datos / métricas (medidos en la BeaglePlay)

Valores reales obtenidos durante la integración (úsalos en el guion):

- **Inferencia YOLO11m INT8 (TFLite):** ~12–17 s con 1 hilo → **~5 s con 4 hilos** (multi-hilo).
- **OCR (Tesseract):** ~2–3 s por intento; **varios intentos por sesión**.
- **Confianza OCR:** placa en **pantalla** ~0.2–0.5; en **papel mate** ~0.7–0.9.
- **Modelo:** `best_plate_yolo11m_int8.tflite`, ~20 MB (INT8).
- **Cámara USB:** UVC, cae en `/dev/video1` (autodetectado).
- **Hardware tiempo real:** ESP32 (HC-SR04, debounce 3 lecturas <50 cm) por UART a 115200.

Pendiente de completar por el equipo:
- Precisión / tasa de acierto del OCR sobre vuestro set de placas: `???`
- Nombres de los integrantes y de la materia: `???`

> **Lección clave para el guion (muy buena ante un jurado técnico):** el cuello de
> botella no era el modelo sino la **configuración** — TFLite a 1 hilo, el
> `tessedit_char_whitelist` que rompe el LSTM de Tesseract 5, y binarizar a mano
> cuando Leptonica lo hace mejor. Mostrar este *debugging* da más puntos que el
> "happy path".

## 9b. Placas de demo (verificadas contra el seed)

Estas placas existen en `db/seeds/simulation_data.sql` y dan un resultado conocido
en vivo. Sirven para guionizar la demo de los 3 caminos de decisión:

| Placa    | Resultado esperado            | Por qué |
|----------|-------------------------------|---------|
| `ABC123` | ✅ GRANTED — whitelist        | en whitelist vigente |
| `XYZ789` | ✅ GRANTED — whitelist        | en whitelist vigente |
| `DEF012` | ✅ GRANTED — whitelist        | en whitelist vigente |
| `JKL345` | ✅ GRANTED — whitelist        | en whitelist vigente |
| `OTR111` | ✅ GRANTED — pago aprobado     | no está en whitelist, pero tiene pago APPROVED |
| `UNK000` | ⛔ DENIED — placa desconocida  | no existe en ninguna tabla |
| `EXP999` | ⛔ DENIED — whitelist vencida  | vigencia expirada (camino de denegación por fecha) |

> Las placas se guardan **sin guion ni punto** (`ABC123`). El OCR normaliza a solo
> letras/números; cuidado con el logo central de las imágenes generadas.

## 10. Estructura sugerida de cada guion (~8 min)

1. **Apertura (30–45 s):** quién eres, qué parte presentas, gancho del problema.
2. **Desarrollo (5–6 min):** explicación técnica con apoyo en slides/diagrama y demo en pantalla.
3. **Demo (1–2 min):** mostrar el sistema real funcionando (hardware o dashboard).
4. **Cierre (30 s):** decisión de ingeniería clave de tu parte + transición al otro integrante.
