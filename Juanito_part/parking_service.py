#!/usr/bin/env python3

"""
parking_service.py

Servicio principal del sistema de parqueadero.
Orquesta la comunicación M4 <-> Linux y el procesamiento de visión.

Este es un ejemplo de integración. Adaptarlo según necesidades específicas.
"""

import os
import sys
import time
import signal
import logging
from pathlib import Path

# Agregar directorio local a path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# =====================================================================
# Imports del proyecto
# =====================================================================

try:
    from Modulo_vision.capture import capturar_rafaga_vehiculo
    from Modulo_vision.vision_pipeline import procesar_imagenes_parqueadero
except ImportError as e:
    print(f"Error al importar módulos de visión: {e}", file=sys.stderr)
    sys.exit(1)

# =====================================================================
# Configuración de logging
# =====================================================================

LOG_PATH = Path("/opt/parking/logs")
LOG_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH / "parking_service.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# =====================================================================
# Variables globales
# =====================================================================

RPMSG_DEVICE = "/dev/rpmsg0"
HEARTBEAT_INTERVAL = 1.0  # segundos
running = True

# =====================================================================
# Funciones de RPMsg
# =====================================================================

def enviar_comando_m4(comando):
    """
    Envía un comando al M4 via RPMsg.
    
    Args:
        comando: String del comando ("OPEN", "CLOSE", "HEARTBEAT")
    
    Returns:
        True si se envió correctamente, False si error
    """
    try:
        if not os.path.exists(RPMSG_DEVICE):
            logger.warning(f"Dispositivo RPMsg no existe: {RPMSG_DEVICE}")
            return False
        
        with open(RPMSG_DEVICE, 'w') as f:
            f.write(comando)
        
        logger.debug(f"Comando enviado al M4: {comando}")
        return True
    
    except Exception as e:
        logger.error(f"Error enviando comando a M4: {e}")
        return False

def enviar_heartbeat():
    """Envía heartbeat al M4 para alimentar el watchdog."""
    enviar_comando_m4("HEARTBEAT")

# =====================================================================
# Funciones de visión
# =====================================================================

def procesar_evento_presencia():
    """
    Procesa un evento de presencia detectado por el sensor M4.
    
    1. Captura ráfaga de frames
    2. Procesa con YOLO + OCR
    3. Abre barrera si placa es válida
    """
    try:
        logger.info("📸 Capturando frames...")
        rutas = capturar_rafaga_vehiculo(num_frames=5)
        
        if not rutas:
            logger.warning("No se pudieron capturar frames")
            return None
        
        logger.info(f"📖 Procesando {len(rutas)} frames...")
        placa, roi = procesar_imagenes_parqueadero(rutas)
        
        logger.info(f"Placa detectada: {placa}")
        
        # Validar placa
        if placa and placa not in ["NO_LEIDO", "DESCONOCIDO", "ERROR_OCR"]:
            logger.info(f"✅ Placa válida: {placa}. Abriendo barrera...")
            enviar_comando_m4("OPEN")
            
            # Mantener barrera abierta 10 segundos
            time.sleep(10)
            
            logger.info("Cerrando barrera...")
            enviar_comando_m4("CLOSE")
        else:
            logger.warning(f"⚠️  Placa no válida: {placa}")
        
        return placa
    
    except Exception as e:
        logger.error(f"Error procesando evento de presencia: {e}")
        return None

# =====================================================================
# Escuchador de eventos del M4
# =====================================================================

def escuchar_eventos_m4():
    """
    Escucha eventos del M4 via RPMsg.
    
    En una implementación real, se usaría un cliente RPMsg
    para recibir mensajes de forma asíncrona.
    """
    try:
        if not os.path.exists(RPMSG_DEVICE):
            logger.warning(f"RPMsg no disponible: {RPMSG_DEVICE}")
            logger.info("Simulando evento de presencia en 5 segundos...")
            time.sleep(5)
            return "PRESENCE_DETECTED"
        
        # Aquí se implementaría lectura real de RPMsg
        # Por ahora, retornamos None (sin eventos)
        return None
    
    except Exception as e:
        logger.error(f"Error escuchando RPMsg: {e}")
        return None

# =====================================================================
# Handler de señales
# =====================================================================

def handle_signal(signum, frame):
    """Maneja señales de terminación (SIGTERM, SIGINT)."""
    global running
    logger.info(f"Recibida señal {signum}. Cerrando barrera y terminando...")
    
    # Cerrar barrera como medida de seguridad
    enviar_comando_m4("CLOSE")
    
    running = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

# =====================================================================
# Loop principal
# =====================================================================

def main():
    """Loop principal del servicio."""
    
    logger.info("=" * 60)
    logger.info("🅿️  SISTEMA DE PARQUEADERO INTELIGENTE")
    logger.info(f"Versión: 1.0.0")
    logger.info(f"RPMsg Device: {RPMSG_DEVICE}")
    logger.info("=" * 60)
    
    # Contador para heartbeat
    heartbeat_counter = 0
    heartbeat_freq = int(HEARTBEAT_INTERVAL)
    
    global running
    
    try:
        while running:
            # ===== Enviar heartbeat cada N segundos =====
            if heartbeat_counter % heartbeat_freq == 0:
                logger.debug("💓 Enviando heartbeat...")
                enviar_heartbeat()
            
            # ===== Escuchar eventos del M4 =====
            evento = escuchar_eventos_m4()
            
            if evento == "PRESENCE_DETECTED":
                logger.info("🚗 VEHÍCULO DETECTADO")
                placa = procesar_evento_presencia()
                
                if placa:
                    logger.info(f"📊 Registro: placa={placa}, timestamp={time.time()}")
                    # Aquí se guardaría en BD, etc.
            
            # ===== Sleep y actualizar contador =====
            time.sleep(1)
            heartbeat_counter += 1
            
            # Reset contador después de 24h para evitar overflow
            if heartbeat_counter > 86400:
                heartbeat_counter = 0
    
    except KeyboardInterrupt:
        logger.info("Interrupción de usuario")
    
    except Exception as e:
        logger.error(f"Error fatal en el loop principal: {e}", exc_info=True)
    
    finally:
        # Cleanup
        logger.info("Limpiando recursos...")
        enviar_comando_m4("CLOSE")
        logger.info("✅ Servicio terminado")

# =====================================================================

if __name__ == "__main__":
    main()
