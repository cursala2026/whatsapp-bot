"""bot/config.py — Configuracion global del runtime.

Centraliza:
- Variables de entorno y constantes base.
- Logging comun del proyecto.
- Cliente Gemini (si hay API key).

Este modulo no depende de otros modulos de `bot/` para evitar ciclos.
"""

from dotenv import load_dotenv
from google import generativeai as genai
import os
import logging

# ============================================================
# PATHS Y CONSTANTES
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
CONFIG_PATH = os.path.join(BASE_DIR, "menu_config.json")
BACKUPS_DIR = os.path.join(BASE_DIR, "menu_backups")
INTERESADOS_PATH = os.path.join(BASE_DIR, "profesionales_interesados.json")
ASESOR_CONSULTAS_PATH = os.path.join(BASE_DIR, "asesor_consultas.json")

# URL pública para que los usuarios suban su CV.
CV_UPLOAD_URL = "https://drive.google.com/drive/folders/1tfEH_v1N3LqCLQQ_aWNIyaIbz9UYm_5K?usp=drive_link"

# Versión de la aplicación, útil para trazabilidad en logs y deploys.
APP_VERSION = "2026-04-18-error-msg-update"

# Configuración de Firebase/Firestore para persistencia de datos.
FIREBASE_CREDENTIALS_PATH = os.path.join(BASE_DIR, "firebase_service_account.json")
FIREBASE_PROJECT_ID = ""
FIRESTORE_COLLECTION = "whatsapp_users"
# Tiempo en segundos para resetear la sesión de un usuario por inactividad.
USER_INACTIVITY_TIMEOUT_SECONDS = 300

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cursala_bot")

# ============================================================
# CARGAR .env
# ============================================================
load_dotenv(dotenv_path=ENV_PATH)

logger.info("Buscando .env en: %s", ENV_PATH)
logger.info("Existe .env: %s", os.path.exists(ENV_PATH))
logger.info("APP_VERSION: %s", APP_VERSION)


def clean_env_value(value: str) -> str:
    """Limpia variables de entorno de caracteres invisibles como BOM."""
    return (value or "").replace("\ufeff", "").strip()


# ============================================================
# CREDENCIALES Y CONFIGURACIÓN DE SERVICIOS
# ============================================================
GEMINI_API_KEY = clean_env_value(os.getenv("GEMINI_API_KEY", ""))
# Modelo de Gemini a utilizar para respuestas y transcripciones. Se recomienda "gemini-1.5-flash".
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
# Habilita/deshabilita el uso de Gemini para responder a texto libre.
ENABLE_GEMINI_FALLBACK = os.getenv("ENABLE_GEMINI_FALLBACK", "true").lower() == "true"

# Cliente de Gemini, se inicializa solo si la API Key está presente.
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY) # type: ignore
    gemini_client = genai.GenerativeModel(GEMINI_MODEL)
else:
    gemini_client = None

# Ruta al archivo de credenciales de Firebase.
FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", FIREBASE_CREDENTIALS_PATH)
# ID del proyecto de Firebase.
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT_ID)
# Nombre de la colección principal en Firestore.
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", FIRESTORE_COLLECTION)

# Credenciales de la API de WhatsApp Cloud.
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
# Número para redirigir todos los mensajes de prueba (si está configurado).
TEST_RECIPIENT = os.getenv("TEST_RECIPIENT")
# Número del administrador para acceder al panel de control.
ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "5492615031839")
# Clave de acceso al panel de administrador.
ADMIN_KEY = os.getenv("ADMIN_KEY", "123456")

# Configuración de plantillas de WhatsApp (opcional).
COURSE_URL_TEMPLATE_NAME = os.getenv("COURSE_URL_TEMPLATE_NAME", "")
COURSE_URL_TEMPLATE_LANGUAGE = os.getenv("COURSE_URL_TEMPLATE_LANGUAGE", "es")
COURSE_URL_TEMPLATE_MODE = os.getenv("COURSE_URL_TEMPLATE_MODE", "dynamic")

# Variables de entorno para trazabilidad en entornos de Cloud Run.
K_SERVICE = os.getenv("K_SERVICE", "")
K_REVISION = os.getenv("K_REVISION", "")
K_CONFIGURATION = os.getenv("K_CONFIGURATION", "")

logger.debug("VERIFY_TOKEN cargado: %s", repr(VERIFY_TOKEN))
