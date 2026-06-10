"""
rpmsg_client.py — Cliente de comunicación bidireccional con el Cortex-M4 vía RPMsg.

Responsabilidad:
  Abstraer el acceso al dispositivo de caracteres /dev/rpmsg0, que es el canal
  de comunicación entre el dominio Linux (A53) y el firmware del M4 del compañero.

Protocolo de mensajes (acordado con Integrante A / firmware M4):
  - Cada mensaje es una línea de texto terminada en '\\n'.
  - Formato de comando enviado al M4:   "<ACTION>:<trace_id>\\n"
      Ejemplo: "OPEN:b3d9c1e2-4f87\\n"
  - Formato de respuesta del M4:        "<ACTION>:<STATUS>:<trace_id>\\n"
      Ejemplo: "OPEN:OK:b3d9c1e2-4f87\\n"
              "OPEN:FAULT:b3d9c1e2-4f87\\n"

Manejo de errores:
  - Si /dev/rpmsg0 no existe (desarrollo sin BeaglePlay), opera en modo simulado.
  - Timeouts explícitos en lectura para no bloquear el servicio indefinidamente.
  - Hilo de lectura en background para recibir eventos asíncronos del M4
    (ej. barrier_opened, barrier_closed, hardware_fault).

Uso:
    client = RPMsgClient()
    client.open()
    client.send_command("OPEN", trace_id="abc-123")
    client.close()
"""

import logging
import os
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_RPMSG_DEVICE      = os.getenv("RPMSG_DEVICE", "/dev/rpmsg0")
_READ_TIMEOUT_S    = float(os.getenv("RPMSG_READ_TIMEOUT_S", "2.0"))
_SIMULATED_MODE_ENV = os.getenv("RPMSG_SIMULATED", "false").lower() == "true"


class RPMsgClient:
    """
    Interfaz de bajo nivel sobre /dev/rpmsg0.

    Abre el dispositivo de caracteres, envía comandos al M4 y expone
    un callback para recibir respuestas/eventos asíncronos.
    """

    def __init__(
        self,
        device:         str = _RPMSG_DEVICE,
        read_timeout_s: float = _READ_TIMEOUT_S,
        simulated:      bool = _SIMULATED_MODE_ENV,
    ) -> None:
        """
        Args:
            device:         Path al dispositivo RPMsg (default: /dev/rpmsg0).
            read_timeout_s: Timeout para lecturas bloqueantes en segundos.
            simulated:      Si True, opera sin hardware real (para desarrollo/tests).
                            Se activa automáticamente si el dispositivo no existe.
        """
        self.device         = device
        self.read_timeout_s = read_timeout_s
        self._simulated     = simulated
        self._fd             = None       # file descriptor del dispositivo
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event    = threading.Event()
        self._on_message_cb: Optional[Callable[[str], None]] = None

    # -----------------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------------

    def open(self) -> None:
        """
        Abre el dispositivo RPMsg e inicia el hilo de lectura en background.

        Si el dispositivo no existe y simulated=False, activa modo simulado
        automáticamente con un WARNING (no bloquea el arranque del servicio).

        Raises:
            OSError: Solo si el dispositivo existe pero no se puede abrir
                     (problema de permisos real, no ausencia del archivo).
        """
        if self._simulated or not os.path.exists(self.device):
            if not self._simulated:
                logger.warning(
                    "RPMsg device '%s' not found — running in SIMULATED mode. "
                    "Commands will be logged but not sent to M4.",
                    self.device,
                )
            else:
                logger.info("RPMsgClient starting in SIMULATED mode (env flag set).")
            self._simulated = True
            self._start_reader_thread()
            return

        try:
            # Abrir en modo lectura/escritura, sin buffering
            self._fd = os.open(self.device, os.O_RDWR | os.O_NONBLOCK)
            logger.info("RPMsg device opened | device=%s", self.device)
            self._start_reader_thread()
        except OSError as exc:
            raise OSError(
                f"Cannot open RPMsg device '{self.device}': {exc}"
            ) from exc

    def close(self) -> None:
        """Detiene el hilo de lectura y cierra el file descriptor."""
        self._stop_event.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)

        if self._fd is not None:
            try:
                os.close(self._fd)
                logger.info("RPMsg device closed | device=%s", self.device)
            except OSError as exc:
                logger.warning("Error closing RPMsg device: %s", exc)
            finally:
                self._fd = None

    # -----------------------------------------------------------------------
    # Envío de comandos al M4
    # -----------------------------------------------------------------------

    def send_command(self, action: str, trace_id: str) -> None:
        """
        Envía un comando al firmware del M4.

        Formato en el dispositivo: "<ACTION>:<trace_id>\\n"
        Acciones válidas definidas por el firmware: OPEN, CLOSE, STOP

        Args:
            action:   Comando para el M4 ("OPEN", "CLOSE", "STOP").
            trace_id: UUID de trazabilidad del evento de origen.

        Raises:
            ValueError:  Si action está vacío.
            RuntimeError: Si el cliente no está abierto.
            OSError:     Si falla la escritura en el dispositivo real.
        """
        if not action:
            raise ValueError("RPMsg action cannot be empty.")

        message = f"{action.upper()}:{trace_id}\n"

        if self._simulated:
            logger.info(
                "[SIMULATED] RPMsg command → '%s' | action=%s trace_id=%s",
                message.strip(), action, trace_id,
            )
            return

        if self._fd is None:
            raise RuntimeError("RPMsgClient is not open. Call open() first.")

        try:
            os.write(self._fd, message.encode("utf-8"))
            logger.info(
                "RPMsg command sent | action=%s trace_id=%s", action, trace_id
            )
        except OSError as exc:
            logger.error(
                "Failed to write to RPMsg device | action=%s error=%s", action, exc
            )
            raise

    # -----------------------------------------------------------------------
    # Recepción de mensajes del M4 (asíncrona)
    # -----------------------------------------------------------------------

    def set_message_callback(self, callback: Callable[[str], None]) -> None:
        """
        Registra el callback que se invoca por cada línea recibida del M4.

        El callback recibe el mensaje crudo como string (sin '\\n').
        Ejemplo de mensaje: "OPEN:OK:b3d9c1e2" o "HARDWARE_FAULT:OBSTACLE"

        Args:
            callback: Función que recibe un str con el mensaje del M4.
        """
        self._on_message_cb = callback
        logger.debug("RPMsg message callback registered.")

    def _start_reader_thread(self) -> None:
        """Inicia el hilo de lectura en background."""
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="rpmsg-reader",
            daemon=True,
        )
        self._reader_thread.start()
        logger.debug("RPMsg reader thread started.")

    def _reader_loop(self) -> None:
        """
        Bucle de lectura que corre en el hilo de background.

        En modo real: lee líneas del file descriptor.
        En modo simulado: simplemente duerme esperando el stop_event.
        """
        if self._simulated:
            logger.debug("RPMsg reader loop running in simulated mode (idle).")
            self._stop_event.wait()
            return

        buffer = b""
        while not self._stop_event.is_set():
            try:
                chunk = os.read(self._fd, 256)
                if not chunk:
                    break
                buffer += chunk

                # Procesar líneas completas
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    message = line.decode("utf-8", errors="replace").strip()
                    if message:
                        self._dispatch_message(message)

            except BlockingIOError:
                # NONBLOCK: no hay datos disponibles en este momento
                self._stop_event.wait(timeout=0.05)
            except OSError as exc:
                logger.error("RPMsg read error: %s", exc)
                break

        logger.debug("RPMsg reader loop exited.")

    def _dispatch_message(self, message: str) -> None:
        """Invoca el callback registrado con el mensaje recibido del M4."""
        logger.debug("RPMsg message received from M4 | raw='%s'", message)
        if self._on_message_cb:
            try:
                self._on_message_cb(message)
            except Exception as exc:
                logger.exception(
                    "Unhandled exception in RPMsg callback | message='%s' error=%s",
                    message, exc,
                )
