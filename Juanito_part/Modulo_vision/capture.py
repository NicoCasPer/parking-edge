import cv2
import os
import time

CAMERA_INDEX = 0  # Puerto cs1 mapeado en /dev/video0 por Debian
TMP_DIR = "tmp_captures/"

def inicializar_camara():
    """
    Abre la cámara CSI y permite que el sensor regule la luz.
    Retorna el objeto VideoCapture o None si hay error.
    """
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"❌ Error: No se puede acceder a la cámara CSI en /dev/video{CAMERA_INDEX}")
        return None
    
    # Pequeña pausa técnica opcional para estabilizar exposición de blancos
    time.sleep(0.5)
    return cap

def liberar_camara(cap):
    """Libera los recursos de la cámara de forma segura."""
    if cap is not None:
        try:
            cap.release()
        except Exception as e:
            print(f"⚠️ Advertencia al liberar cámara: {e}")

def capturar_rafaga_vehiculo(num_frames=5):
    """
    Se ejecuta inmediatamente al activarse el detector de vehículos.
    Captura una ráfaga rápida de fotos para asegurar que alguna salga nítida.
    
    Args:
        num_frames: Número de frames a capturar (por defecto 5)
    
    Returns:
        Lista de rutas a las imágenes capturadas, o lista vacía si hay error
    """
    cap = inicializar_camara()
    if cap is None:
        return []

    os.makedirs(TMP_DIR, exist_ok=True)
    rutas_imagenes = []
    
    print(f"📸 ¡Vehículo detectado! Capturando ráfaga de {num_frames} frames...")
    
    try:
        for i in range(num_frames):
            ret, frame = cap.read()
            if not ret:
                print(f"⚠️ Error al capturar frame {i}. Discontinuando captura.")
                break
            
            # Validar que el frame sea válido antes de guardar
            if frame is None or frame.size == 0:
                print(f"⚠️ Frame {i} vacío. Saltando.")
                continue
            
            # Guardamos cada frame con un identificador temporal
            ruta = os.path.join(TMP_DIR, f"frame_{i}.jpg")
            
            # Usar cv2.imwrite con validación de resultado
            if cv2.imwrite(ruta, frame):
                rutas_imagenes.append(ruta)
                print(f"   ✓ Frame {i} guardado: {ruta}")
            else:
                print(f"   ✗ Error al guardar frame {i}")
            
            # Una micro-pausa entre fotos para capturar movimiento leve
            time.sleep(0.05)
            
    except Exception as e:
        print(f"❌ Error durante la captura: {e}")
    finally:
        # Liberar la cámara de inmediato para ahorrar energía y recursos
        liberar_camara(cap)
    
    print(f"✅ Ráfaga completada. {len(rutas_imagenes)} imágenes guardadas en '{TMP_DIR}'.")
    return rutas_imagenes

if __name__ == "__main__":
    # Prueba aislada: Simula que el detector de vehículos se activó
    rutas = capturar_rafaga_vehiculo()
    print("Archivos listos para el pipeline:", rutas)
