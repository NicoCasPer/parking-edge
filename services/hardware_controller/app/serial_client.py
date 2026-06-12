"""
serial_client.py — Cliente UART hacia el ESP32 WROOM-32 (reemplaza al M4/RPMsg).

Sustituye a rpmsg_client.RPMsgClient manteniendo EXACTAMENTE la misma interfaz
pública (open / close / send_command / set_message_callback + modo simulado), de
modo que command_dispatcher.py y main.py no necesitan cambios de lógica: sólo
cambia el transporte físico de RPMsg (/dev/rpmsg0) a UART (pyserial, /dev/ttyS*).

Protocolo (idéntico al firmware ESP32):
  - Cada mensaje es una línea de texto terminada en '\\n'.
  - Linux → ESP32:  "<ACTION>:<trace_id>\\n"   (OPEN / CLOSE / STOP / HEARTBEAT)
  - ESP32 → Linux:  "PRESENCE_DETECTED", "<ACTION>:OK:<trace_id>",
                    "<ACTION>:FAULT:<trace_id>", "HARDWARE_FAULT:<reason>"

Variables de entorno:
    UART_DEVICE         — path del puerto serie (default: /dev/ttyS2)
    UART_BAUDRATE       — baudios (default: 115200)
    UART_READ_TIMEOUT_S — timeout de lectura en segundos (default: 1.0)
    UART_SIMULATED      — "true" para desarrollo sin ESP32 físico

Manejo de errores:
  - Si el puerto no existe (o pyserial no está instalado), opera en modo simulado.
  - Hilo de lectura en background para eventos asíncronos del ESP32.
"""

import logging
import os
import threading
from typing import Callable, Optional

try:
    import serial  # pyserial
except ImportError:  # permite arrancar en modo simulado sin la dependencia
    serial = None

logger = logging.getLogger(__name__)

_UART_DEVICE        = os.getenv("UART_DEVICE", "/dev/ttyS2")
_UART_BAUDRATE      = int(os.getenv("UART_BAUDRATE", "115200"))
_READ_TIMEOUT_S     = float(os.getenv("UART_READ_TIMEOUT_S", "1.0"))
_SIMULATED_MODE_ENV = os.getenv("UART_SIMULATED", "false").lower() == "true"


class SerialClient:
    """
    Interfaz de bajo nivel sobre un puerto serie (UART) hacia el ESP32.

    Abre el puerto, envía comandos al ESP32 y expone un callback para recibir
    respuestas/eventos asíncronos. Misma firma que RPMsgClient.
    """

    def __init__(
        self,
        device:         str = _UART_DEVICE,
        baudrate:       int = _UART_BAUDRATE,
        read_timeout_s: float = _READ_TIMEOUT_S,
        simulated:      bool = _SIMULATED_MODE_ENV,
    ) -> None:
        self.device         = device
        self.baudrate       = baudrate
        self.read_timeout_s = read_timeout_s
        self._simulated     = simulated
        self._serial         = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event    = threading.Event()
        self._on_message_cb: Optional[Callable[[str], None]] = None

    # -----------------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------------

    def open(self) -> None:
        """
        Abre el puerto UART e inicia el hilo de lectura en background.

        Si pyserial no está instalado, o el puerto no existe y simulated=False,
        activa modo simulado con un WARNING (no bloquea el arranque del servicio).

        Raises:
            OSError: Sólo si el puerto existe pero no se puede abrir (permisos,
                     puerto ocupado, etc.).
        """
        if self._simulated or serial is None or not os.path.exists(self.device):
            if serial is None:
                logger.warning(
                    "pyserial no está instalado — SerialClient en modo SIMULADO."
                )
            elif self._simulated:
                logger.info("SerialClient arranca en modo SIMULADO (flag env).")
            else:
                logger.warning(
                    "Puerto UART '%s' no encontrado — modo SIMULADO. "
                    "Los comandos se registran pero no se envían al ESP32.",
                    self.device,
                )
            self._simulated = True
            self._start_reader_thread()
            return

        try:
            self._serial = serial.Serial(
                port=self.device,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.read_timeout_s,
            )
            logger.info(
                "UART abierto | device=%s baud=%d", self.device, self.baudrate
            )
            self._start_reader_thread()
        except (OSError, serial.SerialException) as exc:
            raise OSError(
                f"No se puede abrir el puerto UART '{self.device}': {exc}"
            ) from exc

    def close(self) -> None:
        """Detiene el hilo de lectura y cierra el puerto serie."""
        self._stop_event.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)

        if self._serial is not None:
            try:
                self._serial.close()
                logger.info("UART cerrado | device=%s", self.device)
            except Exception as exc:  # noqa: BLE001 — cierre best-effort
                logger.warning("Error cerrando UART: %s", exc)
            finally:
                self._serial = None

    # -----------------------------------------------------------------------
    # Envío de comandos al ESP32
    # -----------------------------------------------------------------------

    def send_command(self, action: str, trace_id: str) -> None:
        """
        Envía un comando al firmware del ESP32.

        Formato en el puerto: "<ACTION>:<trace_id>\\n"
        Acciones: OPEN, CLOSE, STOP, HEARTBEAT.

        Raises:
            ValueError:   Si action está vacío.
            RuntimeError: Si el cliente no está abierto.
            OSError:      Si falla la escritura en el puerto real.
        """
        if not action:
            raise ValueError("La acción UART no puede ser vacía.")

        message = f"{action.upper()}:{trace_id}\n"

        if self._simulated:
            logger.info(
                "[SIMULADO] UART comando → '%s' | action=%s trace_id=%s",
                message.strip(), action, trace_id,
            )
            return

        if self._serial is None:
            raise RuntimeError("SerialClient no está abierto. Llama a open() primero.")

        try:
            self._serial.write(message.encode("utf-8"))
            logger.info(
                "UART comando enviado | action=%s trace_id=%s", action, trace_id
            )
        except (OSError, serial.SerialException) as exc:
            logger.error(
                "Fallo escribiendo en UART | action=%s error=%s", action, exc
            )
            raise

    # -----------------------------------------------------------------------
    # Recepción de mensajes del ESP32 (asíncrona)
    # -----------------------------------------------------------------------

    def set_message_callback(self, callback: Callable[[str], None]) -> None:
        """
        Registra el callback invocado por cada línea recibida del ESP32.
        El callback recibe el mensaje crudo como str (sin '\\n').
        """
        self._on_message_cb = callback
        logger.debug("UART message callback registrado.")

    def _start_reader_thread(self) -> None:
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="uart-reader",
            daemon=True,
        )
        self._reader_thread.start()
        logger.debug("UART reader thread iniciado.")

    def _reader_loop(self) -> None:
        """
        Bucle de lectura en el hilo de background.

        En modo real: lee del puerto serie y procesa líneas completas.
        En modo simulado: espera el stop_event (idle).
        """
        if self._simulated:
            logger.debug("UART reader loop en modo simulado (idle).")
            self._stop_event.wait()
            return

        buffer = b""
        while not self._stop_event.is_set():
            try:
                # read() respeta el timeout configurado y devuelve b"" al expirar
                chunk = self._serial.read(256)
                if not chunk:
                    continue
                buffer += chunk

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    message = line.decode("utf-8", errors="replace").strip()
                    if message:
                        self._dispatch_message(message)

            except (OSError, serial.SerialException) as exc:
                logger.error("Error leyendo del UART: %s", exc)
                break

        logger.debug("UART reader loop finalizado.")

    def _dispatch_message(self, message: str) -> None:
        """Invoca el callback registrado con el mensaje recibido del ESP32."""
        logger.debug("UART mensaje recibido del ESP32 | raw='%s'", message)
        if self._on_message_cb:
            try:
                self._on_message_cb(message)
            except Exception as exc:  # noqa: BLE001 — no tumbar el hilo lector
                logger.exception(
                    "Excepción no controlada en callback UART | message='%s' error=%s",
                    message, exc,
                )
