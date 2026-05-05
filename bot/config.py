"""bot/config.py — Configuracion global del runtime.

Centraliza:
- Variables de entorno y constantes base.
- Logging comun del proyecto.
- Cliente Gemini (si hay API key).

Este modulo no depende de otros modulos de `bot/` para evitar ciclos.
"""

from dotenv import load_dotenv
from google import genai
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
CV_UPLOAD_URL = "https://drive.google.com/drive/folders/1tfEH_v1N3LqCLQQ_aWNIyaIbz9UYm_5K?usp=drive_link"

APP_VERSION = "2026-04-18-error-msg-update"

FIREBASE_CREDENTIALS_PATH = os.path.join(BASE_DIR, "firebase_service_account.json")
FIREBASE_PROJECT_ID = ""
FIRESTORE_COLLECTION = "whatsapp_users"
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
    return (value or "").replace("\ufeff", "").strip()


# ============================================================
# CREDENCIALES Y CONFIGURACIÓN DE SERVICIOS
# ============================================================
GEMINI_API_KEY = clean_env_value(os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
ENABLE_GEMINI_FALLBACK = os.getenv("ENABLE_GEMINI_FALLBACK", "false").lower() == "true"

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", FIREBASE_CREDENTIALS_PATH)
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT_ID)
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", FIRESTORE_COLLECTION)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
TEST_RECIPIENT = os.getenv("TEST_RECIPIENT")
ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "5492615031839")
ADMIN_KEY = os.getenv("ADMIN_KEY", "123456")

COURSE_URL_TEMPLATE_NAME = os.getenv("COURSE_URL_TEMPLATE_NAME", "")
COURSE_URL_TEMPLATE_LANGUAGE = os.getenv("COURSE_URL_TEMPLATE_LANGUAGE", "es")
COURSE_URL_TEMPLATE_MODE = os.getenv("COURSE_URL_TEMPLATE_MODE", "dynamic")

K_SERVICE = os.getenv("K_SERVICE", "")
K_REVISION = os.getenv("K_REVISION", "")
K_CONFIGURATION = os.getenv("K_CONFIGURATION", "")

logger.debug("VERIFY_TOKEN cargado: %s", repr(VERIFY_TOKEN))
