# Usa una imagen base de Python optimizada
FROM python:3.11-slim

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo de requerimientos primero para aprovechar el cache de Docker
COPY requirements.txt .

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de la aplicación
COPY . .

# Crea el directorio para el caché de cursos
RUN mkdir -p /app/cache

# Expone el puerto en el que correrá la aplicación
EXPOSE 8080

# Healthcheck para verificar que la aplicación está corriendo
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5)"

# Comando para iniciar la aplicación con Uvicorn
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:8080"]

# ... otras dependencias que ya tengas ...
google-genai
