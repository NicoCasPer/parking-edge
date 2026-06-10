import cv2
import numpy as np
from ultralytics import YOLO
import pytesseract
import os

MODEL_PATH = "best_plate_yolo11m_int8.tflite"

# Variable global para almacenar el modelo (se inicializa en la primera llamada)
_model = None
_model_initialized = False

def inicializar_modelo():
    """
    Inicializa el modelo YOLO de forma lazy (solo cuando se necesita).
    Valida que el archivo del modelo exista antes de cargar.
    
    Returns:
        Objeto YOLO si se carga correctamente, None si hay error
    """
    global _model, _model_initialized
    
    if _model_initialized:
        return _model
    
    # Validar que el archivo del modelo existe
    if not os.path.exists(MODEL_PATH):
        print(f"❌ ERROR: Archivo del modelo no encontrado en '{MODEL_PATH}'")
        print(f"   Directorio actual: {os.getcwd()}")
        print(f"   Archivos disponibles: {os.listdir('.')}")
        _model_initialized = True
        _model = None
        return None
    
    try:
        print(f"📦 Cargando modelo YOLO desde '{MODEL_PATH}'...")
        _model = YOLO(MODEL_PATH)
        _model_initialized = True
        print(f"✅ Modelo YOLO cargado correctamente.")
        return _model
    except Exception as e:
        print(f"❌ ERROR al cargar el modelo YOLO: {e}")
        _model_initialized = True
        _model = None
        return None

def calcular_nitidez(ruta_imagen):
    """
    Calcula la varianza del Laplaciano (Requerimiento estricto de calidad).
    
    Args:
        ruta_imagen: Ruta al archivo de imagen
    
    Returns:
        Valor de nitidez (varianza del Laplaciano), o 0 si hay error
    """
    try:
        img = cv2.imread(ruta_imagen, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"⚠️ No se pudo leer la imagen: {ruta_imagen}")
            return 0
        
        nitidez = cv2.Laplacian(img, cv2.CV_64F).var()
        return nitidez
    except Exception as e:
        print(f"⚠️ Error al calcular nitidez: {e}")
        return 0

def seleccionar_mejor_frame(lista_rutas):
    """
    Analiza la ráfaga y devuelve la imagen más nítida para el OCR.
    
    Args:
        lista_rutas: Lista de rutas a imágenes
    
    Returns:
        Ruta al mejor frame, o None si la lista está vacía
    """
    if not lista_rutas:
        print("⚠️ Lista de rutas vacía. No hay frames para analizar.")
        return None
    
    mejor_ruta = None
    max_nitidez = -1
    
    for ruta in lista_rutas:
        nitidez = calcular_nitidez(ruta)
        if nitidez > max_nitidez:
            max_nitidez = nitidez
            mejor_ruta = ruta
    
    if mejor_ruta is None:
        print("⚠️ No se pudo seleccionar un frame válido (todos dieron error)")
        return None
            
    print(f"🔬 Mejor frame seleccionado: {mejor_ruta} (Nitidez Laplaciana: {max_nitidez:.2f})")
    return mejor_ruta

def extract_roi(image, x1, y1, x2, y2):
    """
    Función obligatoria de recorte de la Región de Interés.
    Incluye validación de límites.
    
    Args:
        image: Imagen de entrada (numpy array)
        x1, y1, x2, y2: Coordenadas del bounding box
    
    Returns:
        Región de interés recortada
    """
    if image is None or image.size == 0:
        print("⚠️ Imagen inválida para extract_roi")
        return np.array([])
    
    h, w = image.shape[:2]
    
    # Garantizar que las coordenadas están dentro de límites y son válidas
    x1_safe = max(0, min(x1, w - 1))
    x2_safe = max(x1_safe + 1, min(x2, w))
    y1_safe = max(0, min(y1, h - 1))
    y2_safe = max(y1_safe + 1, min(y2, h))
    
    return image[y1_safe:y2_safe, x1_safe:x2_safe]

def read_plate_tesseract(roi_image):
    """
    Procesa el recorte con Tesseract OCR optimizado.
    
    Args:
        roi_image: Región de interés a procesar
    
    Returns:
        Texto extraído o un código de error
    """
    if roi_image is None or roi_image.size == 0:
        print("⚠️ ROI vacía, no hay nada que procesar")
        return "NO_LEIDO"
    
    try:
        gray = cv2.cvtColor(roi_image, cv2.COLOR_RGB2GRAY)
        binarizada = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        custom_config = r'--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        texto = pytesseract.image_to_string(binarizada, config=custom_config)
        
        texto_limpio = texto.strip().upper().replace(" ", "").replace("-", "")
        
        if not texto_limpio:
            return "NO_LEIDO"
        
        return texto_limpio
    
    except pytesseract.TesseractNotFoundError:
        print("❌ ERROR: Tesseract no está instalado en el sistema")
        return "ERROR_OCR_TESSERACT_NOT_FOUND"
    except Exception as e:
        print(f"❌ ERROR en OCR: {e}")
        return "ERROR_OCR"

def procesar_imagenes_parqueadero(lista_rutas):
    """
    Orquesta el análisis de la ráfaga que capturó el módulo de la cámara.
    Incluye validación en cada paso.
    
    Args:
        lista_rutas: Lista de rutas a imágenes capturadas
    
    Returns:
        Tupla (texto_placa, roi_imagen)
        - texto_placa: String con la placa detectada o código de error
        - roi_imagen: Array numpy con la región de la placa (o None)
    """
    
    # 1. Inicializar el modelo si no está listo
    model = inicializar_modelo()
    if model is None:
        print("❌ No se puede procesar: modelo YOLO no disponible")
        return "ERROR_MODEL_LOAD", None
    
    # 2. Filtrado de calidad: seleccionar mejor frame
    mejor_foto = seleccionar_mejor_frame(lista_rutas)
    if not mejor_foto:
        print("⚠️ No se pudo seleccionar un frame válido")
        return "NO_LEIDO", None
    
    # 3. Leer la imagen
    try:
        img = cv2.imread(mejor_foto)
        if img is None:
            print(f"❌ No se pudo leer la imagen: {mejor_foto}")
            return "ERROR_IMAGE_READ", None
        
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    except Exception as e:
        print(f"❌ Error al procesar imagen: {e}")
        return "ERROR_IMAGE_PROCESS", None
    
    # 4. Inferencia con YOLO INT8
    try:
        results = model(img_rgb, verbose=False)
        if not results or len(results) == 0:
            print("⚠️ YOLO no retornó resultados")
            return "ERROR_YOLO_INFERENCE", None
        
        boxes = results[0].boxes.xyxy.cpu().numpy()
        
        if len(boxes) == 0:
            print("⚠️ No se localizó la placa en la mejor foto.")
            return "DESCONOCIDO", None
        
        # Usar solo la primera detección (más confianza)
        x1, y1, x2, y2 = map(int, boxes[0])
        
    except Exception as e:
        print(f"❌ Error en inferencia YOLO: {e}")
        return "ERROR_YOLO", None
    
    # 5. Recorte de la ROI
    try:
        plate_roi = extract_roi(img_rgb, x1, y1, x2, y2)
        if plate_roi.size == 0:
            print("⚠️ ROI vacía después del recorte")
            return "ERROR_ROI_EXTRACTION", None
    except Exception as e:
        print(f"❌ Error al extraer ROI: {e}")
        return "ERROR_ROI_EXTRACTION", None
    
    # 6. Reconocimiento de caracteres
    try:
        texto_placa = read_plate_tesseract(plate_roi)
    except Exception as e:
        print(f"❌ Error en OCR: {e}")
        return "ERROR_OCR", None
    
    return texto_placa, plate_roi
