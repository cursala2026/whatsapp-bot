"""
Script de prueba aislado para verificar la integración con Gemini.

Uso:
    python bot/test_gemini.py

Requiere .env con:
    GEMINI_API_KEY=...
"""
import os
import google.generativeai as genai
from dotenv import load_dotenv

# Carga las variables del archivo .env si existe
load_dotenv()

print("--- Iniciando prueba de API de Gemini ---")

# Obtiene la API Key desde las variables de entorno
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ ERROR: La variable de entorno GEMINI_API_KEY no está configurada.")
    print("   Asegurate de que esté en tu archivo .env o en la configuración de docker-compose.yml")
    exit(1)

print(f"✅ API Key encontrada (termina en '...{api_key[-4:]}').")

try:
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    model = genai.GenerativeModel(model_name)
    print(f"✅ Modelo '{model_name}' cargado.")

    print("⏳ Enviando pregunta de prueba a Gemini...")
    response = model.generate_content("Respondé en una sola línea: hola desde Gemini")

    print(f"\nRespuesta de Gemini:\n-> \"{response.text.strip()}\"\n")

    print("✅ ¡Prueba exitosa! La conexión con la API de Gemini funciona correctamente.")
except Exception as e:
    print(f"\n❌ ERROR: Falló la prueba de conexión con Gemini.\n   Detalle: {e}")
    exit(1)