FROM debian:bookworm-slim

# =====================================================================
# Instalar herramientas de compilación
# =====================================================================

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    gcc-arm-none-eabi \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# =====================================================================
# Instalar Python y dependencias
# =====================================================================

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# =====================================================================
# Directorio de trabajo
# =====================================================================

WORKDIR /workspace

# =====================================================================
# Copiar proyecto
# =====================================================================

COPY . .

# =====================================================================
# Instalar dependencias Python
# =====================================================================

RUN pip3 install --no-cache-dir -r requirements.txt

# =====================================================================
# Configurar permiso de ejecución para scripts
# =====================================================================

RUN chmod +x scripts/*.sh

# =====================================================================
# Volumen para compartir archivos compilados
# =====================================================================

VOLUME ["/workspace/Modulo_actuadores/build", "/workspace/build"]

# =====================================================================
# Comando por defecto: compilar
# =====================================================================

WORKDIR /workspace/Modulo_actuadores

CMD ["make", "clean", "build"]
