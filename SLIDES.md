# Prompt para IA: diapositivas + guion por diapositiva — parking-edge

> **Cómo usarlo:** sube `README.md` y `BRIEF.md` como fuentes (verdad técnica del
> proyecto) y pega este archivo como instrucción. Genera un deck de **15
> diapositivas** y las notas del presentador por diapositiva.

## Contexto de la presentación
- **Audiencia:** un profesor universitario (jurado técnico). Tono **técnico, conciso
  y seguro**, sin relleno comercial. Español neutro.
- **Formato:** 16:9, exactamente **15 diapositivas**, poco texto por slide (el detalle
  va en las notas del presentador).
- **Presentadores:** 2 integrantes, ~10 min cada uno.
  - **Integrante 1 (Percepción y borde):** diapositivas **1–7**.
  - **Integrante 2 (Decisión, integración y operación):** diapositivas **8–15**;
    conduce la **demo en vivo**.
- Se presenta con el **sistema funcionando en vivo** al final.

## Reglas de exactitud (OBLIGATORIAS)
- El hardware de tiempo real es un **ESP32 WROOM-32** comunicado por **UART** con la
  BeaglePlay. **No usar "M4" ni "RPMsg".**
- La barrera se **simula con un LED por PWM** (no un servo).
- Usar **solo métricas reales**: inferencia YOLO11m INT8 ~**12–17 s con 1 hilo** y
  ~**5 s con 4 hilos** (TFLite multi-hilo); OCR ~2–3 s por intento; confianza OCR
  **0.2–0.5 en pantalla** y **0.7–0.9 en papel**; modelo TFLite ~20 MB.
  **No inventar "<600 ms" ni "99.5 %".** El mensaje de rendimiento es la
  **optimización lograda en hardware limitado**, no cifras infladas.

## Estilo visual
- Moderno, líneas limpias, iconos planos, mucho aire. Diagramas por capas con flechas.
- Paleta: fondo claro `#F7F9FC`; primario azul `#1565C0`; secundario verde `#2E7D32`;
  acento naranja `#FF8A00` (alertas/acciones).
- Tipografía sans-serif (Inter/Roboto). Títulos 32–40pt, subtítulos 20–26pt, texto 16–18pt.
- Iconos: cámara, ESP32/MCU, sensor ultrasónico, MQTT, base de datos, candado, tarjeta de pago, LED.

## Entregable por diapositiva
Para cada slide devolver: 1) Título; 2) Layout/diseño visual; 3) Texto exacto del
slide; 4) Iconos/imágenes sugeridos; 5) Notas del presentador (3–5 frases);
6) Duración sugerida. Generar además `NOTES.md` con todas las notas seguidas.

---

## Estructura de las 15 diapositivas

### — Integrante 1: "Percepción y borde" (1–7) —

**1. Portada**
- Layout: título grande + subtítulo + diagrama esquemático pequeño (BeaglePlay + ESP32 + cámara).
- Texto: Título "parking-edge — Control de acceso inteligente en el borde". Subtítulo
  "Visión por computadora (YOLO11m INT8 + Tesseract) + tiempo real en ESP32 + microservicios MQTT". Integrantes y materia.
- Notas: Una frase con el objetivo (automatizar el acceso a un parqueadero por
  reconocimiento de placa, **en el borde**, sin nube y seguro ante fallos). Adelantar
  que al final hay demo en vivo.
- Duración: 25s

**2. Motivación: latencia y fricción**
- Layout: tabla comparativa de 2 columnas (Tradicional vs parking-edge) por filas:
  Procesamiento, Confiabilidad, Seguridad, Hardware.
- Texto: Tradicional → nube/alta latencia, vulnerable a caídas, fallos de red abren la
  barrera, hardware fragmentado. parking-edge → **IA 100 % local**, **operación autónoma
  con colas offline**, **FAIL-CLOSED por defecto**, **sistema unificado en BeaglePlay (AM625)**.
- Notas: Justificar el "edge": decidir el acceso sin depender de internet, y por qué la
  seguridad por defecto debe ser cerrar la barrera.
- Duración: 40s

**3. Ciclo de acceso (visión general)**
- Layout: ciclo de 4 nodos: Detectar → Leer → Verificar → Actuar.
- Texto: Detectar (sensor HC-SR04 en ESP32) · Leer (visión IA: YOLO + OCR) · Verificar
  (orquestador: whitelist/pago) · Actuar (comando de apertura de la barrera).
- Notas: Resumen del flujo de punta a punta en una sola imagen; cada bloque se detalla después.
- Duración: 30s

**4. Arquitectura: ecosistema BeaglePlay (AM625)**
- Layout: 3 capas apiladas.
- Texto:
  - **Capa de aplicación** — procesador A53 con Linux: microservicios Python, SQLite y broker MQTT.
  - **Capa de tiempo real** — **ESP32 WROOM-32 (FreeRTOS)**: respuestas deterministas y manejo de hardware crítico.
  - **Capa física** — sensor ultrasónico HC-SR04 y actuador de barrera (LED PWM).
- Notas: Idea central: **separar la inteligencia (Linux) del tiempo real (ESP32)**;
  se comunican por **UART a 115200**. Mencionar la migración desde un núcleo M4F a un
  ESP32 externo por simplicidad de cableado, depuración y flasheo (decisión de ingeniería honesta).
- Duración: 55s

**5. Tiempo real: el ESP32**
- Layout: chip ESP32 al centro con 3 callouts.
- Texto: **Detección de presencia** (HC-SR04, debounce de 3 lecturas <50 cm) · **Watchdog
  de hardware** (si Linux no responde en 5 s, el ESP32 cierra la barrera por su cuenta) ·
  **Control de la barrera** (LED por PWM: animación al abrir/cerrar; auto-cierre tras 5 s sin vehículo).
- Notas: Por qué un microcontrolador dedicado garantiza la respuesta dura del sensor y un
  estado seguro aunque el lado Linux falle.
- Duración: 45s

**6. hardware-controller: el puente UART ↔ MQTT**
- Layout: puente; izquierda ESP32/FreeRTOS, derecha Linux/MQTT.
- Texto: Daemon Python que **traduce UART en eventos MQTT**: sube `PRESENCE_DETECTED`
  como `presence_detected` y baja los comandos `OPEN`/`CLOSE` al ESP32.
- Notas: Aísla el protocolo serie del resto del sistema; el bus de eventos no sabe que
  detrás hay un ESP32.
- Duración: 40s

**7. vision-service: inferencia en el borde**
- Layout: pipeline de 3 pasos + nota lateral.
- Texto: **1) Captura en vivo** (sesión de cámara USB, frames a `latest.jpg` para el
  dashboard) → **2) Detección YOLO11m INT8 (TFLite)** recorta la placa → **3) OCR Tesseract**
  sobre el recorte a color → publica `plate_read`.
- Notas: Por qué INT8 (velocidad en ARM sin GPU). Detalle real: **1 detección YOLO → varios
  intentos de OCR** sobre frames frescos para no depender de un solo cuadro; el hilo de visión
  está separado del heartbeat para no bloquearlo. (Transición al Integrante 2.)
- Duración: 55s

### — Integrante 2: "Decisión, integración y operación" (8–15) —

**8. access-orchestrator: el cerebro del negocio**
- Layout: árbol de decisión de 3 ramas desde "placa leída".
- Texto: **Whitelist vigente → access_granted** · **No en whitelist + pago aprobado →
  access_granted** · **Sin registro/o error → access_denied**. Reglas en `config/policies.yaml`.
- Notas: La decisión vive en Linux y consulta SQLite. La placa debe **coincidir con la BD**
  (formato `ABC123`, sin guion). Mencionar que el OCR puede leer pero la whitelist es el filtro real.
- Duración: 50s

**9. Comunicación: el bus de eventos MQTT**
- Layout: broker Mosquitto al centro con 4 tópicos alrededor.
- Texto: `presence_detected` (hardware→visión) · `plate_read` (visión→orquestador/pagos) ·
  `access_granted/denied` (orquestador→todos) · `commands/barrier` (orquestador/dashboard→hardware).
  Broker **Mosquitto, puerto 1883**. **Desacoplamiento total** entre servicios.
- Notas: Por qué MQTT (pub/sub ligero); cada servicio hace una sola cosa y se integra por el bus.
- Duración: 40s

**10. Datos e infraestructura local (SQLite)**
- Layout: 3 tablas + ruta.
- Texto: `/var/lib/parking/parking.db` → **whitelist** (placas vigentes), **payment_events**
  (historial de cobros), **access_events** (auditoría de cada cruce). Cola offline `payment_queue.db`.
- Notas: Todo persiste local; auditoría completa sin nube. Mencionar el seed de demo.
- Duración: 35s

**11. Seguridad y tolerancia a fallos**
- Layout: 3 paneles.
- Texto: **FAIL-CLOSED** (ante cualquier error de OCR/lógica, la barrera NO abre) ·
  **Watchdog del ESP32** (estado seguro autónomo si Linux se cuelga) · **Circuit breaker +
  cola offline** para los pagos cuando el proveedor falla.
- Notas: La filosofía: ante la duda, denegar. El acceso nunca se otorga por error.
- Duración: 45s

**12. Rendimiento e ingeniería real (optimización)**
- Layout: antes/después + bullets de fixes.
- Texto: **YOLO INT8: 12–17 s (1 hilo) → ~5 s (4 hilos, TFLite multi-hilo)** · **OCR sobre
  imagen a color** (binarizar a mano lo empeoraba) · **sin `tessedit_char_whitelist`** (rompía el
  LSTM de Tesseract 5) · **validador alineado a la BD** (formato sin guion). Pruebas con `pytest services/`.
- Notas: El mensaje fuerte ante el jurado: el cuello de botella no era el modelo sino la
  **configuración**; mostrar el debugging sistemático como evidencia de ingeniería.
- Duración: 50s

**13. Entorno de desarrollo y arranque**
- Layout: terminal + toggle Hardware/Simulado.
- Texto: Arranque de todo en un terminal con **`bash scripts/run_demo.sh`** (broker + BD +
  servicios + dashboard). Modo simulado: `UART_SIMULATED=true`, `MOCK_PAYMENT_SERVER=true`,
  `DB_PATH=/tmp/parking.db`. Variables de ajuste de visión (`OCR_CONFIDENCE_MIN`, `CAMERA_INDEX`, `TFLITE_THREADS`).
- Notas: Reproducibilidad: un solo comando levanta el sistema; se puede demostrar sin el ESP32.
- Duración: 35s

**14. Demo: flujo de acceso en vivo**
- Layout: 4 pasos con tópico MQTT por paso.
- Texto: **Llegada** (`presence_detected`) → **Visión** (cámara en vivo + YOLO+OCR leen
  `ABC123`, `plate_read`) → **Decisión** (whitelist → `access_granted`) → **Apertura** (UART →
  ESP32 → la barrera/LED abre). Placas de demo: `ABC123` (whitelist), `OTR111` (pago), `UNK000` (denegada).
- Notas: Narrar la demo real; señalar el evento apareciendo en el dashboard. Tip: placa en
  **papel mate** para que el OCR lea con buena confianza.
- Duración: 90s

**15. Operación y próximos pasos**
- Layout: dashboard a la izquierda + roadmap a la derecha.
- Texto: **Dashboard (puerto 8080):** eventos en vivo (WebSocket), vista de cámara,
  whitelist, override OPEN/STOP/CLOSE, tabla de pagos. **Roadmap:** cámara industrial IP,
  modelo más liviano (YOLO11n) para más velocidad, pagos reales con tokenización.
- Notas: Cerrar con el valor entregado y abrir a preguntas.
- Duración: 35s

---

## Instrucciones finales para la IA
- Responder primero con el índice (número + título de las 15 diapositivas) y luego cada
  diapositiva en el formato pedido.
- Generar `NOTES.md` con el guion del presentador por diapositiva, rotulado por integrante
  (1: slides 1–7, 2: slides 8–15), listo para usar como notas.
- Mantener SIEMPRE los términos y métricas reales de las "Reglas de exactitud".
