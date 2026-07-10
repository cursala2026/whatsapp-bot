import os
import google.generativeai as genai
from dotenv import load_dotenv

# Carga las variables del archivo .env si existe
# Esto es útil para pruebas locales fuera de Docker
load_dotenv()

print("--- Iniciando prueba de API de Gemini ---")

# Obtiene la API Key desde las variables de entorno
# Docker-compose se encarga de pasar esta variable al contenedor
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ ERROR: La variable de entorno GEMINI_API_KEY no está configurada.")
    print("   Asegurate de que esté en tu archivo .env o en la configuración de docker-compose.yml")
    exit(1)

print("✅ API Key encontrada.")

try:
    # Configura el cliente de Gemini
    genai.configure(api_key=api_key)
    print("✅ Cliente de Gemini configurado.")

    # Crea el modelo
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")
    model = genai.GenerativeModel(model_name)
    print(f"✅ Modelo '{model_name}' cargado.")

    # Envía una pregunta de prueba
    print("⏳ Enviando pregunta de prueba a Gemini...")
    response = model.generate_content("Hola, solo estoy probando la conexión. Responde con 'OK'.")

    # Imprime la respuesta
    print(f"\n--- Respuesta de Gemini ---\n{response.text.strip()}\n---------------------------\n")

    print("✅ ¡ÉXITO! La conexión con la API de Gemini funciona correctamente.")
except Exception as e:
    print(f"\n❌ ERROR: Falló la prueba de conexión con Gemini.\n   Detalle: {e}")
    exit(1)