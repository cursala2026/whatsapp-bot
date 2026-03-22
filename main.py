from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json
import requests
import re
import unicodedata
from typing import Optional, Tuple

try:
    import firebase_admin  # type: ignore[import-not-found]
    from firebase_admin import credentials, firestore  # type: ignore[import-not-found]
except Exception:
    firebase_admin = None
    credentials = None
    firestore = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
CONFIG_PATH = os.path.join(BASE_DIR, "menu_config.json")
BACKUPS_DIR = os.path.join(BASE_DIR, "menu_backups")
INTERESADOS_PATH = os.path.join(BASE_DIR, "profesionales_interesados.json")
ASESOR_CONSULTAS_PATH = os.path.join(BASE_DIR, "asesor_consultas.json")
CV_UPLOAD_URL = "https://drive.google.com/drive/folders/1tfEH_v1N3LqCLQQ_aWNIyaIbz9UYm_5K?usp=drive_link"
APP_VERSION = "2026-03-22-course-buttons-v3"
FIREBASE_CREDENTIALS_PATH = os.path.join(BASE_DIR, "firebase_service_account.json")
FIREBASE_PROJECT_ID = ""
FIRESTORE_COLLECTION = "whatsapp_users"

print("Buscando .env en:", ENV_PATH)
print("Existe .env?:", os.path.exists(ENV_PATH))
print("APP_VERSION:", APP_VERSION)

load_dotenv(dotenv_path=ENV_PATH)

FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", FIREBASE_CREDENTIALS_PATH)
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT_ID)
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", FIRESTORE_COLLECTION)

app = FastAPI()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
TEST_RECIPIENT = os.getenv("TEST_RECIPIENT")
ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "5492615031839")
ADMIN_KEY = os.getenv("ADMIN_KEY", "123456")
COURSE_URL_TEMPLATE_NAME = os.getenv("COURSE_URL_TEMPLATE_NAME", "")
COURSE_URL_TEMPLATE_LANGUAGE = os.getenv("COURSE_URL_TEMPLATE_LANGUAGE", "es")
COURSE_URL_TEMPLATE_MODE = os.getenv("COURSE_URL_TEMPLATE_MODE", "dynamic")

print("VERIFY_TOKEN cargado:", repr(VERIFY_TOKEN))


@app.get("/version")
async def app_version():
    return {
        "app_version": APP_VERSION,
        "phone_number_id": PHONE_NUMBER_ID,
        "verify_token_loaded": bool(VERIFY_TOKEN),
        "course_url_template_name": COURSE_URL_TEMPLATE_NAME,
        "course_url_template_mode": COURSE_URL_TEMPLATE_MODE,
    }


def validate_admin_api_key(x_admin_key: Optional[str]) -> None:
    if not x_admin_key or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="No autorizado")


@app.get("/admin/firestore/users")
async def admin_firestore_users(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
    provincia: Optional[str] = Query(default=None, description="Nombre o slug de provincia"),
    interes: Optional[str] = Query(default=None, description="Interes para filtrar (tag o texto)"),
    limit: int = Query(default=50, ge=1, le=200),
):
    validate_admin_api_key(x_admin_key)

    if firestore_db is None:
        raise HTTPException(status_code=503, detail="Firestore no configurado")

    provincia_slug = normalize_interest_tag(provincia) if provincia else None
    interes_tag = normalize_interest_tag(interes) if interes else None

    query_ref = firestore_db.collection(FIRESTORE_COLLECTION)
    if provincia_slug:
        query_ref = query_ref.where("indicadores.provincia_slug", "==", provincia_slug)
    if interes_tag:
        query_ref = query_ref.where("intereses_tags", "array_contains", interes_tag)

    try:
        docs = query_ref.limit(limit).stream()
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            items.append(
                {
                    "id": doc.id,
                    "nombre": data.get("nombre", ""),
                    "telefono": data.get("telefono", {}).get("normalizado", ""),
                    "provincia": data.get("provincia_por_numero", {}),
                    "intereses_tags": data.get("intereses_tags", []),
                    "intereses_labels": data.get("intereses_labels", []),
                    "indicadores": data.get("indicadores", {}),
                    "actualizado_en": str(data.get("actualizado_en", "")),
                }
            )

        return {
            "collection": FIRESTORE_COLLECTION,
            "filters": {
                "provincia": provincia or "",
                "provincia_slug": provincia_slug or "",
                "interes": interes or "",
                "interes_tag": interes_tag or "",
                "limit": limit,
            },
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando Firestore: {e}")


@app.get("/admin/firestore/users/{telefono}")
async def admin_firestore_user_by_phone(
    telefono: str,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    validate_admin_api_key(x_admin_key)

    if firestore_db is None:
        raise HTTPException(status_code=503, detail="Firestore no configurado")

    normalized_phone = normalize_number(telefono)
    if not normalized_phone:
        raise HTTPException(status_code=400, detail="Telefono invalido")

    try:
        doc = firestore_db.collection(FIRESTORE_COLLECTION).document(normalized_phone).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return {
            "id": doc.id,
            "data": doc.to_dict() or {},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando Firestore: {e}")


def normalize_number(number: str) -> str:
    if not number:
        return ""
    return "".join(ch for ch in str(number) if ch.isdigit())


def is_admin(number: str) -> bool:
    return normalize_number(number) == normalize_number(ADMIN_NUMBER)


def saludo_por_horario() -> str:
    hora = datetime.now(ZoneInfo("America/Argentina/Mendoza")).hour

    if 5 <= hora < 12:
        return "Buen día"
    elif 12 <= hora < 20:
        return "Buenas tardes"
    else:
        return "Buenas noches"


def load_menu_config() -> dict:
    default_config = {
        "greeting": "Bienvenido/a a Cursala.\nGracias por comunicarte con nosotros.\n\n¿Cómo podemos ayudarte hoy?",
        "options": {
            "1": "Cursos disponibles",
            "2": "Capacitaciones para empresas",
            "3": "Quiero capacitar",
            "4": "Quiero hablar con un asesor",
        },
        "responses": {
            "1": "¡Claro! En Cursala contamos con distintas propuestas de formación técnica y profesional.",
            "2": "Excelente. Vamos a recopilar algunos datos para poder asesorarte mejor.",
            "3": "¡Gracias por tu interés en capacitar con Cursala!\n\nEnvia un correo a recursos.humanos@cursala.com.ar adjuntando tu cv y tu propuesta de capacitación.",
            "4": "Perfecto, te pondremos en contacto con un asesor de Cursala a la brevedad.\n\nPor favor, indicános tu nombre y en qué temática o curso estás interesado/a."
        },
        "cursos": {
            "1": {
                "nombre": "Minería",
                "descripcion": "Formación en técnicas de extracción, seguridad minera.",
                "link_web": "https://www.cursala.com/cursos/mineria",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "2": {
                "nombre": "Soldadura",
                "descripcion": "Cursos de soldadura MIG, TIG y SMAW.",
                "link_web": "https://www.cursala.com/cursos/soldadura",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "3": {
                "nombre": "Piping",
                "descripcion": "Diseño e instalación de sistemas de tuberías.",
                "link_web": "https://www.cursala.com/cursos/piping",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "4": {
                "nombre": "Redes y telecomunicaciones",
                "descripcion": "Formación en redes y tecnología IT.",
                "link_web": "https://www.cursala.com/cursos/redes",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "5": {
                "nombre": "Instrumentación y control",
                "descripcion": "Cursos de automatización e instrumentación.",
                "link_web": "https://www.cursala.com/cursos/instrumentacion",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "6": {
                "nombre": "Herramientas para pymes",
                "descripcion": "Capacitación para pequeñas y medianas empresas.",
                "link_web": "https://www.cursala.com/cursos/pymes",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "7": {
                "nombre": "Ensayos No destructivos",
                "descripcion": "Técnicas avanzadas de inspección.",
                "link_web": "https://www.cursala.com/cursos/ensayos",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "8": {
                "nombre": "Diseño mecánico",
                "descripcion": "Formación en CAD y diseño mecanico.",
                "link_web": "https://www.cursala.com/cursos/diseno",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "9": {
                "nombre": "Logística para Pymes",
                "descripcion": "Gestión de cadena de suministro.",
                "link_web": "https://www.cursala.com/cursos/logistica",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
        },
        "vendedores": {
            "1": {
                "nombre": "Carlos",
                "apellido": "García",
                "telefono": "+5492615031839",
                "correo": "carlos@cursala.com.ar"
            }
        }
    }

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        changed = False

        for key in ["greeting", "options", "responses", "cursos", "vendedores"]:
            if key not in config:
                config[key] = default_config[key]
                changed = True

        for key, value in default_config["options"].items():
            if key not in config["options"]:
                config["options"][key] = value
                changed = True

        for key, value in default_config["responses"].items():
            if key not in config["responses"]:
                config["responses"][key] = value
                changed = True

        if changed:
            print("⚠️ menu_config.json fue completado con claves faltantes.")
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

        return config

    except FileNotFoundError:
        print("📝 Creando menu_config.json con valores por defecto...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config

    except json.JSONDecodeError as e:
        print(f"⚠️ Error: menu_config.json corrupto. {e}")
        print("Regenerando con valores por defecto...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config


def save_menu_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def list_backups() -> list:
    """Returns sorted list of backup filenames, newest first."""
    if not os.path.exists(BACKUPS_DIR):
        return []
    files = [f for f in os.listdir(BACKUPS_DIR) if f.endswith(".json")]
    return sorted(files, reverse=True)


def create_menu_backup() -> str:
    """Creates a timestamped backup of the current menu_config. Returns the filename."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    timestamp = datetime.now(ZoneInfo("America/Argentina/Mendoza")).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.json"
    filepath = os.path.join(BACKUPS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(menu_config, f, ensure_ascii=False, indent=2)
    return filename


def restore_menu_backup(filename: str) -> bool:
    """Restores menu_config from the specified backup file. Returns True if successful."""
    global menu_config
    filepath = os.path.join(BACKUPS_DIR, filename)
    if not os.path.exists(filepath):
        return False
    with open(filepath, "r", encoding="utf-8") as f:
        restored = json.load(f)
    menu_config = restored
    save_menu_config(menu_config)
    return True


def save_profesional_interesado(registro: dict):
    try:
        if os.path.exists(INTERESADOS_PATH):
            with open(INTERESADOS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []

        data.append(registro)
        with open(INTERESADOS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error guardando profesional interesado: {e}")


def save_asesor_consulta(registro: dict):
    try:
        if os.path.exists(ASESOR_CONSULTAS_PATH):
            with open(ASESOR_CONSULTAS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []

        data.append(registro)
        with open(ASESOR_CONSULTAS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error guardando consulta para asesor: {e}")


def reorganize_course_ids():
    if not menu_config.get("cursos"):
        return

    cursos_ordenados = []
    for key in sorted(menu_config["cursos"].keys(), key=int):
        cursos_ordenados.append(menu_config["cursos"][key])

    menu_config["cursos"] = {}
    for index, curso in enumerate(cursos_ordenados, 1):
        menu_config["cursos"][str(index)] = curso

    save_menu_config(menu_config)


try:
    menu_config = load_menu_config()
    print("✅ Configuración cargada correctamente")
    print(f"Claves en menu_config: {menu_config.keys()}")
    admin_sessions = {}
except Exception as e:
    print(f"⚠️ Error cargando configuración: {e}")
    menu_config = {"greeting": "", "options": {}, "responses": {}, "cursos": {}, "vendedores": {}}
    admin_sessions = {}


def get_admin_session(number: str) -> dict:
    key = normalize_number(number)
    if key not in admin_sessions:
        admin_sessions[key] = {
            "active": False,
            "awaiting_admin_password": False,
            "in_course_menu": False,
            "in_course_detail": False,
            "in_courses_edit_menu": False,
            "in_response_menu": False,
            "current_course": None,
            "awaiting_confirmation": False,
            "pending_action": None,
            "pending_change": None,
            "change_history": [],
            "temp_option": None,
            "temp_option_text": None,
            "temp_field": None,
            "temp_course_data": {},
            "temp_prof_data": {},
            "temp_asesor_data": {},
            "temp_course_field_index": 0,
            "last_response_option": None
        }
    return admin_sessions[key]


def reset_user_flow(session: dict):
    session["in_course_menu"] = False
    session["in_course_detail"] = False
    session["in_courses_edit_menu"] = False
    session["in_response_menu"] = False
    session["current_course"] = None
    session["pending_action"] = None
    session["temp_option"] = None
    session["temp_option_text"] = None
    session["temp_field"] = None
    session["temp_course_data"] = {}
    session["temp_prof_data"] = {}
    session["temp_asesor_data"] = {}
    session["last_response_option"] = None


AREA_CODE_TO_PROVINCE = {
    "220": "Buenos Aires",
    "221": "Buenos Aires",
    "223": "Buenos Aires",
    "230": "Buenos Aires",
    "236": "Buenos Aires",
    "237": "Buenos Aires",
    "249": "Buenos Aires",
    "261": "Mendoza",
    "264": "San Juan",
    "266": "San Luis",
    "280": "Chubut",
    "291": "Buenos Aires",
    "294": "Rio Negro",
    "297": "Chubut",
    "299": "Neuquen",
    "341": "Santa Fe",
    "342": "Santa Fe",
    "343": "Entre Rios",
    "351": "Cordoba",
    "362": "Chaco",
    "370": "Formosa",
    "376": "Misiones",
    "379": "Corrientes",
    "381": "Tucuman",
    "385": "Santiago del Estero",
    "387": "Salta",
    "388": "Jujuy",
}


def normalize_text_for_filter(text: str) -> str:
    lowered = (text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", lowered)
    without_accents = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    compact = " ".join(without_accents.split())
    return compact


def normalize_interest_tag(label: str) -> str:
    base = normalize_text_for_filter(label)
    safe = "".join(ch if ch.isalnum() else "_" for ch in base)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")


def infer_argentina_province_from_phone(number: str) -> Tuple[str, str]:
    digits = normalize_number(number)
    if digits.startswith("54"):
        digits = digits[2:]
    if digits.startswith("9"):
        digits = digits[1:]
    if digits.startswith("0"):
        digits = digits[1:]

    for size in [4, 3, 2]:
        area_code = digits[:size]
        if area_code in AREA_CODE_TO_PROVINCE:
            return AREA_CODE_TO_PROVINCE[area_code], area_code

    return "Desconocida", ""


def init_firestore_client():
    if firebase_admin is None or credentials is None or firestore is None:
        print("⚠️ firebase_admin no está instalado. Firestore deshabilitado.")
        return None

    if firebase_admin._apps:
        return firestore.client()

    if not os.path.exists(FIREBASE_CREDENTIALS_PATH):
        print(f"⚠️ No se encontró credencial de Firebase en: {FIREBASE_CREDENTIALS_PATH}")
        print("Firestore deshabilitado hasta configurar FIREBASE_CREDENTIALS_PATH.")
        return None

    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        if FIREBASE_PROJECT_ID:
            firebase_admin.initialize_app(cred, {"projectId": FIREBASE_PROJECT_ID})
        else:
            firebase_admin.initialize_app(cred)
        print("✅ Firestore inicializado correctamente")
        return firestore.client()
    except Exception as e:
        print(f"⚠️ Error inicializando Firestore: {e}")
        return None


firestore_db = init_firestore_client()


def upsert_user_profile_firestore(
    whatsapp_number: str,
    nombre: Optional[str] = None,
    telefono: Optional[str] = None,
    intereses: Optional[list] = None,
    evento: str = "",
    extra_fields: Optional[dict] = None,
):
    if firestore_db is None:
        return

    phone = telefono or whatsapp_number
    normalized_phone = normalize_number(phone)
    if not normalized_phone:
        return

    provincia, area_code = infer_argentina_province_from_phone(normalized_phone)
    provincia_slug = normalize_interest_tag(provincia)

    payload = {
        "origen": "whatsapp_bot",
        "whatsapp_number": normalize_number(whatsapp_number),
        "telefono": {
            "normalizado": normalized_phone,
            "e164": f"+{normalized_phone}",
            "codigo_area": area_code,
        },
        "provincia_por_numero": {
            "nombre": provincia,
            "slug": provincia_slug,
            "codigo_area": area_code,
        },
        "indicadores": {
            "tiene_telefono": True,
            "provincia_slug": provincia_slug,
            "ultimo_evento": evento or "actualizacion",
        },
        "actualizado_en": firestore.SERVER_TIMESTAMP,
    }

    if nombre:
        clean_name = " ".join(nombre.strip().split())
        payload["nombre"] = clean_name
        payload["nombre_normalizado"] = normalize_text_for_filter(clean_name)
        payload["indicadores"]["tiene_nombre"] = True

    if intereses:
        labels = [" ".join(str(item).strip().split()) for item in intereses if str(item).strip()]
        tags = [normalize_interest_tag(label) for label in labels]
        tags = [tag for tag in tags if tag]
        if labels:
            payload["intereses_labels"] = firestore.ArrayUnion(labels)
        if tags:
            payload["intereses_tags"] = firestore.ArrayUnion(tags)
            payload["indicadores_interes"] = {tag: True for tag in tags}

    if extra_fields:
        payload.update(extra_fields)

    try:
        firestore_db.collection(FIRESTORE_COLLECTION).document(normalized_phone).set(payload, merge=True)
    except Exception as e:
        print(f"⚠️ Error guardando perfil en Firestore: {e}")


def track_user_interest(whatsapp_number: str, interest_label: str, evento: str = "interes_detectado"):
    upsert_user_profile_firestore(
        whatsapp_number=whatsapp_number,
        telefono=whatsapp_number,
        intereses=[interest_label],
        evento=evento,
    )


def build_main_menu() -> str:
    saludo = saludo_por_horario()
    lines = [f"{saludo} 👋", menu_config["greeting"], ""]
    for key in sorted(menu_config["options"].keys(), key=int):
        lines.append(f"{key}. {menu_config['options'][key]}")
    lines.append("\nPor favor, respondé con el número de la opción que te interesa.")
    return "\n".join(lines)


def build_courses_menu() -> str:
    if "cursos" not in menu_config:
        return "⚠️ Error: No hay cursos disponibles. Por favor, contacta al administrador."
    menu = "📚 MENÚ DE CURSOS DISPONIBLES\n\n"
    for key in sorted(menu_config["cursos"].keys(), key=int):
        menu += f"C{key}. {menu_config['cursos'][key]['nombre']}\n"
    menu += "\nRespondé con el código del curso. Ejemplo: C1\n\n0. Volver al menú principal"
    return menu


def build_course_detail_menu(curso_id: str) -> str:
    if curso_id not in menu_config["cursos"]:
        return "Curso no encontrado."
    curso = menu_config["cursos"][curso_id]
    return (
        f"📖 {curso['nombre'].upper()}\n\n"
        f"{curso['descripcion']}\n\n"
        "1. 🌐 VER CURSO\n"
        "2. 📘 TEMARIO\n"
        "3. 💳 Comprar\n"
        "0. Volver al menú principal"
    )


def parse_course_selection(text: str) -> Optional[str]:
    normalized_text = text.strip().lower()
    match = re.fullmatch(r"c\s*(\d+)", normalized_text)
    if not match:
        return None

    curso_id = match.group(1)
    if curso_id not in menu_config.get("cursos", {}):
        return None
    return curso_id


def parse_course_action_identifier(text: str) -> Optional[Tuple[str, str]]:
    normalized_text = text.strip().lower()
    match = re.fullmatch(r"course:(\d+):(view|syllabus|buy)", normalized_text)
    if not match:
        return None

    curso_id, action_name = match.groups()
    if curso_id not in menu_config.get("cursos", {}):
        return None

    action_mapping = {
        "view": "1",
        "syllabus": "2",
        "buy": "3",
    }
    return curso_id, action_mapping[action_name]


def handle_course_detail_action(from_number: str, curso_id: str, action: str):
    if action == "0":
        reset_user_flow(get_admin_session(from_number))
        enviar_respuesta(from_number, build_main_menu())
        return

    curso = menu_config["cursos"].get(curso_id, {})

    if action == "1":
        enviar_respuesta(from_number, f"🌐 Link: {curso.get('link_web', 'N/A')}\n\n0. Volver")
        return

    if action == "2":
        enviar_respuesta(from_number, f"📥 Descarga: {curso.get('link_descarga', 'N/A')}\n\n0. Volver")
        return

    if action == "3":
        vendedor_id = curso.get("vendedor_id", "1")
        vendedor = menu_config["vendedores"].get(vendedor_id, {})
        msg = (
            f"📞 Contacta a:\n"
            f"{vendedor.get('nombre', 'N/A')} {vendedor.get('apellido', 'N/A')}\n"
            f"📱 {vendedor.get('telefono', 'N/A')}\n"
            f"📧 {vendedor.get('correo', 'N/A')}"
        )
        enviar_respuesta(from_number, msg)
        return

    enviar_respuesta(from_number, "Opción inválida. Elegí VER CURSO, TEMARIO, COMPRAR o 0.")
    enviar_detalle_curso(from_number, curso_id)


def build_courses_edit_menu() -> str:
    menu = "📚 EDITAR CURSOS DISPONIBLES\n\n"
    menu += "1. ➕ Agregar curso\n"
    menu += "2. ❌ Eliminar curso\n"
    menu += "3. ✏️ Editar curso\n"
    menu += "4. 📋 Ver cursos disponibles\n"
    menu += "\n0. Volver al menú admin"
    return menu


def build_admin_menu() -> str:
    return (
        "⚙️ MODO ADMINISTRADOR\n\n"
        "1. Ver menú actual\n"
        "2. Modificar saludo\n"
        "3. Editar opción\n"
        "4. Agregar opción\n"
        "5. Modificar respuesta\n"
        "6. Editar cursos disponibles\n"
        "7. Gestionar vendedores\n"
        "8. Deshacer cambio\n"
        "9. Desactivar admin\n"
        "10. 💾 Gestionar backups\n\n"
        "0. Volver al menú principal"
    )


def build_vendor_menu() -> str:
    return (
        "👥 GESTIONAR VENDEDORES\n\n"
        "1. ➕ Agregar vendedor\n"
        "2. ✏️ Editar vendedor\n"
        "3. ❌ Eliminar vendedor\n\n"
        "0. Volver al menú admin"
    )


def build_backup_menu() -> str:
    backups = list_backups()
    count = len(backups)
    count_str = f"({count} backup{'s' if count != 1 else ''} guardado{'s' if count != 1 else ''})"
    return (
        f"💾 GESTIONAR BACKUPS {count_str}\n\n"
        "1. ➕ Crear backup de configuración actual\n"
        "2. 🔄 Ver / Restaurar backup\n\n"
        "0. Volver al menú admin"
    )


PROVINCIAS_ARGENTINA = {
    "buenos aires", "catamarca", "chaco", "chubut", "córdoba", "cordoba",
    "corrientes", "entre ríos", "entre rios", "formosa", "jujuy",
    "la pampa", "la rioja", "mendoza", "misiones", "neuquén", "neuquen",
    "río negro", "rio negro", "salta", "san juan", "san luis",
    "santa cruz", "santa fe", "santiago del estero",
    "tierra del fuego", "antártida e islas del atlántico sur",
    "antartida e islas del atlantico sur",
    "tucumán", "tucuman",
    "ciudad autónoma de buenos aires", "ciudad autonoma de buenos aires",
    "caba", "ciudad de buenos aires",
}


def validar_correo(texto: str) -> bool:
    partes = texto.strip().split("@")
    return len(partes) == 2 and len(partes[0]) > 0 and "." in partes[1] and len(partes[1]) > 2


def validar_telefono(texto: str) -> bool:
    limpio = texto.strip().replace(" ", "").replace("+", "").replace("-", "")
    return limpio.isdigit() and len(limpio) >= 6


def validar_provincia(texto: str) -> bool:
    return texto.strip().lower() in PROVINCIAS_ARGENTINA


def validar_nombre_empresa(texto: str) -> bool:
    limpio = texto.strip()
    if len(limpio) < 2:
        return False
    return not any(ch.isdigit() for ch in limpio)


def validar_dni(texto: str) -> bool:
    limpio = "".join(ch for ch in texto if ch.isdigit())
    return len(limpio) in [7, 8]


def validar_texto_sin_numeros(texto: str, min_len: int = 2) -> bool:
    limpio = " ".join(texto.strip().split())
    if len(limpio) < min_len:
        return False
    return not any(ch.isdigit() for ch in limpio)


def validar_cuit(texto: str) -> bool:
    limpio = "".join(ch for ch in texto if ch.isdigit())
    if len(limpio) != 11:
        return False
    if not limpio.isdigit():
        return False

    multiplicadores = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(limpio[i]) * multiplicadores[i] for i in range(10))
    resto = suma % 11
    verificador = 0 if resto == 0 else 9 if resto == 1 else 11 - resto
    return verificador == int(limpio[10])


def build_empresa_confirmacion(data: dict) -> str:
    return (
        "📋 *Revisá los datos ingresados:*\n\n"
        f"1️⃣  Empresa: {data.get('empresa', '')}\n"
        f"2️⃣  CUIT: {data.get('cuit', '')}\n"
        f"3️⃣  Provincia: {data.get('provincia', '')}\n"
        f"4️⃣  Correo: {data.get('correo', '')}\n"
        f"5️⃣  Teléfono: {data.get('telefono', '')}\n"
        f"6️⃣  Necesidades: {data.get('necesidades', '')}\n\n"
        "¿Qué querés hacer?\n"
        "C. ✅ Confirmar y enviar\n"
        "1. Editar nombre de empresa\n"
        "2. Editar CUIT\n"
        "3. Editar provincia\n"
        "4. Editar correo\n"
        "5. Editar teléfono\n"
        "6. Editar necesidades de formación\n"
        "0. Volver al menú principal"
    )


def build_profesional_confirmacion(data: dict) -> str:
    return (
        "📋 *Revisá los datos ingresados:*\n\n"
        f"1️⃣  Nombre y apellido: {data.get('nombre_apellido', '')}\n"
        f"2️⃣  Profesión: {data.get('profesion', '')}\n"
        f"3️⃣  Nacionalidad: {data.get('nacionalidad', '')}\n"
        f"4️⃣  DNI: {data.get('dni', '')}\n"
        f"5️⃣  Curso a dictar: {data.get('descripcion_curso', '')}\n\n"
        "¿Qué querés hacer?\n"
        "C. Continuar con carga de CV\n"
        "1. Editar nombre y apellido\n"
        "2. Editar profesión\n"
        "3. Editar nacionalidad\n"
        "4. Editar DNI\n"
        "5. Editar descripción del curso\n"
        "0. Volver al menú principal"
    )


def build_asesor_empresa_confirmacion(data: dict) -> str:
    return (
        "📋 *Revisá los datos de EMPRESA:*\n\n"
        f"1️⃣  🏢 Empresa: {data.get('empresa_nombre', '')}\n"
        f"2️⃣  📧 Correo: {data.get('empresa_correo', '')}\n"
        f"3️⃣  📩 Email: {data.get('empresa_email', '')}\n"
        f"4️⃣  📝 Motivo: {data.get('motivo', '')}\n\n"
        "¿Qué querés hacer?\n"
        "C. ✅ Confirmar y enviar\n"
        "1. Editar nombre de empresa\n"
        "2. Editar correo\n"
        "3. Editar email\n"
        "4. Editar motivo\n"
        "0. Volver al menú principal"
    )


def build_asesor_persona_confirmacion(data: dict) -> str:
    return (
        "📋 *Revisá los datos de PERSONA FÍSICA:*\n\n"
        f"1️⃣  Nombre completo: {data.get('nombre_completo', '')}\n"
        f"2️⃣  CUIT: {data.get('cuit', '')}\n"
        f"3️⃣  Teléfono: {data.get('telefono', '')}\n"
        f"4️⃣  DNI: {data.get('dni', '')}\n"
        f"5️⃣  Correo: {data.get('correo', '')}\n"
        f"6️⃣  Motivo: {data.get('motivo', '')}\n\n"
        "¿Qué querés hacer?\n"
        "C. ✅ Confirmar y enviar\n"
        "1. Editar nombre completo\n"
        "2. Editar CUIT\n"
        "3. Editar teléfono\n"
        "4. Editar DNI\n"
        "5. Editar correo\n"
        "6. Editar motivo\n"
        "0. Volver al menú principal"
    )


def enviar_payload_whatsapp(destino: str, payload: dict, log_preview: str) -> bool:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        print("⚠️ Credenciales no configuradas")
        return False

    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    full_payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        **payload,
    }

    print(f"Enviando a {destino}: {log_preview[:80]}...")

    try:
        response = requests.post(
            url,
            headers=headers,
            json=full_payload,
            timeout=15
        )
        print(f"Respuesta Meta: {response.status_code} - {response.text}")
        return response.ok

    except requests.exceptions.Timeout:
        print("⚠️ Timeout enviando mensaje a Meta")
        return False

    except requests.exceptions.RequestException as e:
        print(f"⚠️ Error HTTP enviando mensaje: {e}")
        return False

    except Exception as e:
        print(f"⚠️ Error inesperado enviando mensaje: {e}")
        return False


def enviar_respuesta(to_number: str, message: str):
    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number
    enviar_payload_whatsapp(
        destino,
        {
            "type": "text",
            "text": {"body": message}
        },
        message,
    )


def extract_url_suffix(url: str, prefixes: list[str]) -> Optional[str]:
    clean_url = (url or "").strip()
    for prefix in prefixes:
        if clean_url.startswith(prefix):
            return clean_url[len(prefix):]
    return None

def course_url_template_enabled() -> bool:
    return bool(COURSE_URL_TEMPLATE_NAME)


def enviar_detalle_curso_template_url(to_number: str, curso_id: str) -> bool:
    if not COURSE_URL_TEMPLATE_NAME:
        return False

    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number
    curso = menu_config["cursos"].get(curso_id)
    if not curso:
        return False

    template_payload = {
        "type": "template",
        "template": {
            "name": COURSE_URL_TEMPLATE_NAME,
            "language": {"code": COURSE_URL_TEMPLATE_LANGUAGE},
        },
    }

    if COURSE_URL_TEMPLATE_MODE == "dynamic":
        web_suffix = extract_url_suffix(
            curso.get("link_web", ""),
            [
                "https://cursala.com.ar/",
                "http://cursala.com.ar/",
                "https://www.cursala.com.ar/",
                "http://www.cursala.com.ar/",
            ],
        )
        temario_suffix = extract_url_suffix(
            curso.get("link_descarga", ""),
            [
                "https://drive.google.com/",
                "http://drive.google.com/",
                "https://www.drive.google.com/",
                "http://www.drive.google.com/",
            ],
        )

        if not web_suffix or not temario_suffix:
            return False

        template_payload["template"]["components"] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": curso.get("nombre", "Curso")},
                ],
            },
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [
                    {"type": "text", "text": web_suffix},
                ],
            },
            {
                "type": "button",
                "sub_type": "url",
                "index": "1",
                "parameters": [
                    {"type": "text", "text": temario_suffix},
                ],
            },
        ]

    template_preview = f"template:{COURSE_URL_TEMPLATE_NAME} course:{curso_id}"
    return enviar_payload_whatsapp(destino, template_payload, template_preview)


def enviar_detalle_curso(to_number: str, curso_id: str):
    sent_template = enviar_detalle_curso_template_url(to_number, curso_id)
    if sent_template:
        return

    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number
    curso = menu_config["cursos"].get(curso_id)
    if not curso:
        enviar_respuesta(to_number, "Curso no encontrado.")
        return

    descripcion = curso.get("descripcion", "") or "Encontrá toda la información del curso en los accesos rápidos."
    body_text = (
        f"📖 *{curso['nombre']}*\n\n"
        f"{descripcion}\n\n"
        "Usá los botones para abrir el curso, el temario o hablar con un asesor.\n"
        "Si querés volver al inicio, escribí MENU."
    )
    interactive_payload = {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"course:{curso_id}:view",
                            "title": "VER CURSO",
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"course:{curso_id}:syllabus",
                            "title": "TEMARIO",
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"course:{curso_id}:buy",
                            "title": "COMPRAR",
                        },
                    },
                ]
            },
        },
    }

    sent = enviar_payload_whatsapp(destino, interactive_payload, body_text)
    if not sent:
        enviar_respuesta(to_number, build_course_detail_menu(curso_id))


def extract_message_text(msg: dict) -> Optional[str]:
    msg_type = msg.get("type")
    if msg_type == "text":
        return msg.get("text", {}).get("body", "").strip()

    if msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type")

        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            return (reply.get("id") or reply.get("title") or "").strip()

        if interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            return (reply.get("id") or reply.get("title") or "").strip()

    return None


def resolve_course_detail_action(text: str, curso_id: str) -> str:
    normalized_text = text.strip()
    lowered_text = normalized_text.lower()
    button_mapping = {
        f"course:{curso_id}:view": "1",
        f"course:{curso_id}:syllabus": "2",
        f"course:{curso_id}:buy": "3",
        "ver curso": "1",
        "temario": "2",
        "comprar": "3",
    }
    return button_mapping.get(normalized_text, button_mapping.get(lowered_text, normalized_text))


def manejar_usuario(from_number: str, text_body: str):
    session = get_admin_session(from_number)
    text = text_body.strip()
    text_lower = text.lower()
    upsert_user_profile_firestore(
        whatsapp_number=from_number,
        telefono=from_number,
        evento="mensaje_entrante",
    )
    empresa_actions = {
        "empresa_nombre",
        "empresa_cuit",
        "empresa_provincia",
        "empresa_correo",
        "empresa_telefono",
        "empresa_necesidades",
        "empresa_confirmacion",
        "empresa_edit_empresa",
        "empresa_edit_cuit",
        "empresa_edit_provincia",
        "empresa_edit_correo",
        "empresa_edit_telefono",
        "empresa_edit_necesidades",
    }
    profesional_actions = {
        "pro_nombre_apellido",
        "pro_profesion",
        "pro_nacionalidad",
        "pro_dni",
        "pro_descripcion",
        "pro_confirmacion",
        "pro_edit_nombre_apellido",
        "pro_edit_profesion",
        "pro_edit_nacionalidad",
        "pro_edit_dni",
        "pro_edit_descripcion",
        "pro_cv_confirmacion",
    }
    asesor_actions = {
        "asesor_tipo",
        "asesor_empresa_nombre",
        "asesor_empresa_correo",
        "asesor_empresa_email",
        "asesor_empresa_motivo",
        "asesor_empresa_confirmacion",
        "asesor_empresa_edit_nombre",
        "asesor_empresa_edit_correo",
        "asesor_empresa_edit_email",
        "asesor_empresa_edit_motivo",
        "asesor_persona_nombre",
        "asesor_persona_cuit",
        "asesor_persona_telefono",
        "asesor_persona_dni",
        "asesor_persona_correo",
        "asesor_persona_motivo",
        "asesor_persona_confirmacion",
        "asesor_persona_edit_nombre",
        "asesor_persona_edit_cuit",
        "asesor_persona_edit_telefono",
        "asesor_persona_edit_dni",
        "asesor_persona_edit_correo",
        "asesor_persona_edit_motivo",
    }

    if text_lower in ["hola", "menu", "inicio"]:
        reset_user_flow(session)
        track_user_interest(from_number, "menu_principal", "navegacion_menu")
        enviar_respuesta(from_number, build_main_menu())
        return

    if text_lower == "admin":
        if not is_admin(from_number):
            enviar_respuesta(from_number, "❌ No autorizado.")
            return
        session["awaiting_admin_password"] = True
        enviar_respuesta(from_number, "Por favor, ingresá la contraseña:")
        return

    if session.get("pending_action") in (empresa_actions | profesional_actions | asesor_actions) and text == "0":
        reset_user_flow(session)
        enviar_respuesta(from_number, "↩️ Volviste al menú principal.\n\n" + build_main_menu())
        return

    if session["pending_action"] == "empresa_nombre":
        if not validar_nombre_empresa(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El nombre de la empresa no es válido. No debe contener números.\n"
                "Ejemplo: *Cursala SA*, *Servicios Andinos SRL*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["empresa"] = text_body.strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            intereses=["capacitaciones_empresas"],
            evento="captura_empresa_nombre",
        )
        enviar_respuesta(from_number, "Perfecto. Ahora indicános el CUIT de la empresa:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_cuit"
        return

    if session["pending_action"] == "empresa_cuit":
        if not validar_cuit(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El CUIT ingresado no es válido. Debe tener 11 dígitos y un dígito verificador correcto.\n"
                "Ejemplo: *30-12345678-9*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["cuit"] = "".join(ch for ch in text_body if ch.isdigit())
        enviar_respuesta(from_number, "Gracias. ¿En qué provincia se encuentra la empresa?\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_provincia"
        return

    if session["pending_action"] == "empresa_provincia":
        if not validar_provincia(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ La provincia ingresada no es válida. Por favor, escribí el nombre completo de una provincia argentina.\n"
                "Ejemplo: *Mendoza*, *Buenos Aires*, *CABA*, *Santa Fe*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["provincia"] = text_body.strip().title()
        enviar_respuesta(from_number, "Indicános un correo de contacto:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_correo"
        return

    if session["pending_action"] == "empresa_correo":
        if not validar_correo(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El correo ingresado no parece válido. Debe contener *@* y un dominio.\n"
                "Ejemplo: *contacto@empresa.com*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["correo"] = text_body.strip()
        enviar_respuesta(from_number, "Ahora compartinos un teléfono de contacto:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_telefono"
        return

    if session["pending_action"] == "empresa_telefono":
        if not validar_telefono(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El teléfono ingresado no es válido. Debe contener solo números (podés incluir +, - o espacios).\n"
                "Ejemplo: *+54 261 5031839*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["telefono"] = text_body.strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            telefono=from_number,
            intereses=["capacitaciones_empresas"],
            evento="captura_empresa_telefono",
            extra_fields={"telefono_contacto_empresa": text_body.strip()},
        )
        enviar_respuesta(from_number, "Por favor, describí las necesidades de formación de tu empresa:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_necesidades"
        return

    if session["pending_action"] == "empresa_necesidades":
        session["temp_course_data"]["necesidades"] = text_body
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_confirmacion":
        if text.lower() == "c":
            data = session["temp_course_data"]
            upsert_user_profile_firestore(
                whatsapp_number=from_number,
                nombre=data.get("empresa", ""),
                telefono=from_number,
                intereses=["capacitaciones_empresas", data.get("necesidades", "")],
                evento="empresa_confirmada",
                extra_fields={
                    "empresa": {
                        "nombre": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia_declarada": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                        "telefono": data.get("telefono", ""),
                    }
                },
            )
            resumen = (
                "✅ Gracias por la información.\n\n"
                "Hemos registrado los siguientes datos:\n"
                f"🏢 Empresa: {data.get('empresa', '')}\n"
                f"🧾 CUIT: {data.get('cuit', '')}\n"
                f"📍 Provincia: {data.get('provincia', '')}\n"
                f"📧 Correo: {data.get('correo', '')}\n"
                f"📞 Teléfono: {data.get('telefono', '')}\n"
                f"📝 Necesidades de formación: {data.get('necesidades', '')}\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad para brindarte la información solicitada."
            )
            enviar_respuesta(from_number, resumen)
            reset_user_flow(session)
        elif text == "1":
            session["pending_action"] = "empresa_edit_empresa"
            enviar_respuesta(from_number, "Ingresá el nuevo *nombre de la empresa*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "empresa_edit_cuit"
            enviar_respuesta(from_number, "Ingresá el nuevo *CUIT*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "empresa_edit_provincia"
            enviar_respuesta(from_number, "Ingresá la nueva *provincia*:\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "empresa_edit_correo"
            enviar_respuesta(from_number, "Ingresá el nuevo *correo de contacto*:\n\n0. Volver al menú principal")
        elif text == "5":
            session["pending_action"] = "empresa_edit_telefono"
            enviar_respuesta(from_number, "Ingresá el nuevo *teléfono de contacto*:\n\n0. Volver al menú principal")
        elif text == "6":
            session["pending_action"] = "empresa_edit_necesidades"
            enviar_respuesta(from_number, "Ingresá las nuevas *necesidades de formación*:\n\n0. Volver al menú principal")
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_edit_empresa":
        if not validar_nombre_empresa(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El nombre de la empresa no es válido. No debe contener números.\n"
                "Ejemplo: *Cursala SA*, *Servicios Andinos SRL*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["empresa"] = text_body.strip()
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_edit_cuit":
        if not validar_cuit(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El CUIT ingresado no es válido. Debe tener 11 dígitos y un dígito verificador correcto.\n"
                "Ejemplo: *30-12345678-9*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["cuit"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_edit_provincia":
        if not validar_provincia(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ La provincia ingresada no es válida. Por favor, escribí el nombre completo de una provincia argentina.\n"
                "Ejemplo: *Mendoza*, *Buenos Aires*, *CABA*, *Santa Fe*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["provincia"] = text_body.strip().title()
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_edit_correo":
        if not validar_correo(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El correo ingresado no parece válido. Debe contener *@* y un dominio.\n"
                "Ejemplo: *contacto@empresa.com*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["correo"] = text_body.strip()
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_edit_telefono":
        if not validar_telefono(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El teléfono ingresado no es válido. Debe contener solo números (podés incluir +, - o espacios).\n"
                "Ejemplo: *+54 261 5031839*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["telefono"] = text_body.strip()
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_edit_necesidades":
        session["temp_course_data"]["necesidades"] = text_body
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "pro_nombre_apellido":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(
                from_number,
                "⚠️ Ingresá un nombre y apellido válidos (sin números).\n"
                "Ejemplo: *Juan Pérez*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["nombre_apellido"] = text_body.strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            intereses=["quiero_capacitar"],
            evento="captura_profesional_nombre",
        )
        session["pending_action"] = "pro_profesion"
        enviar_respuesta(from_number, "Perfecto. Ahora indicános tu *profesión*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "pro_profesion":
        if not validar_texto_sin_numeros(text_body, min_len=3):
            enviar_respuesta(
                from_number,
                "⚠️ La profesión ingresada no es válida (sin números).\n"
                "Ejemplo: *Ingeniero Mecánico*, *Docente*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["profesion"] = text_body.strip()
        session["pending_action"] = "pro_nacionalidad"
        enviar_respuesta(from_number, "Gracias. ¿Cuál es tu *nacionalidad*?\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "pro_nacionalidad":
        if not validar_texto_sin_numeros(text_body, min_len=3):
            enviar_respuesta(
                from_number,
                "⚠️ La nacionalidad ingresada no es válida (sin números).\n"
                "Ejemplo: *Argentina*, *Chilena*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["nacionalidad"] = text_body.strip()
        session["pending_action"] = "pro_dni"
        enviar_respuesta(from_number, "Ahora indicános tu *DNI* (solo números):\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "pro_dni":
        if not validar_dni(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El DNI no es válido. Debe tener 7 u 8 dígitos.\n"
                "Ejemplo: *30123456*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "pro_descripcion"
        enviar_respuesta(from_number, "Describí brevemente el *curso que querés dictar*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "pro_descripcion":
        if len(text_body.strip()) < 10:
            enviar_respuesta(
                from_number,
                "⚠️ La descripción es muy breve. Contanos un poco más sobre el curso que querés dictar.\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["descripcion_curso"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, build_profesional_confirmacion(session["temp_prof_data"]))
        return

    if session["pending_action"] == "pro_confirmacion":
        if text_lower == "c":
            session["pending_action"] = "pro_cv_confirmacion"
            enviar_respuesta(
                from_number,
                "Excelente. Para finalizar, cargá tu CV en este enlace:\n"
                f"🔗 {CV_UPLOAD_URL}\n\n"
                "Cuando termines, respondé *LISTO* para guardar tu postulación.\n\n"
                "0. Volver al menú principal"
            )
        elif text == "1":
            session["pending_action"] = "pro_edit_nombre_apellido"
            enviar_respuesta(from_number, "Ingresá el nuevo *Nombre y apellido*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "pro_edit_profesion"
            enviar_respuesta(from_number, "Ingresá la nueva *profesión*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "pro_edit_nacionalidad"
            enviar_respuesta(from_number, "Ingresá la nueva *nacionalidad*:\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "pro_edit_dni"
            enviar_respuesta(from_number, "Ingresá el nuevo *DNI* (solo números):\n\n0. Volver al menú principal")
        elif text == "5":
            session["pending_action"] = "pro_edit_descripcion"
            enviar_respuesta(from_number, "Ingresá la nueva *descripción del curso*:\n\n0. Volver al menú principal")
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_profesional_confirmacion(session["temp_prof_data"]))
        return

    if session["pending_action"] == "pro_edit_nombre_apellido":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(
                from_number,
                "⚠️ Ingresá un nombre y apellido válidos (sin números).\n"
                "Ejemplo: *Juan Pérez*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["nombre_apellido"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_profesional_confirmacion(session["temp_prof_data"]))
        return

    if session["pending_action"] == "pro_edit_profesion":
        if not validar_texto_sin_numeros(text_body, min_len=3):
            enviar_respuesta(
                from_number,
                "⚠️ La profesión ingresada no es válida (sin números).\n"
                "Ejemplo: *Ingeniero Mecánico*, *Docente*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["profesion"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_profesional_confirmacion(session["temp_prof_data"]))
        return

    if session["pending_action"] == "pro_edit_nacionalidad":
        if not validar_texto_sin_numeros(text_body, min_len=3):
            enviar_respuesta(
                from_number,
                "⚠️ La nacionalidad ingresada no es válida (sin números).\n"
                "Ejemplo: *Argentina*, *Chilena*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["nacionalidad"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_profesional_confirmacion(session["temp_prof_data"]))
        return

    if session["pending_action"] == "pro_edit_dni":
        if not validar_dni(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El DNI no es válido. Debe tener 7 u 8 dígitos.\n"
                "Ejemplo: *30123456*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_profesional_confirmacion(session["temp_prof_data"]))
        return

    if session["pending_action"] == "pro_edit_descripcion":
        if len(text_body.strip()) < 10:
            enviar_respuesta(
                from_number,
                "⚠️ La descripción es muy breve. Contanos un poco más sobre el curso que querés dictar.\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["descripcion_curso"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(
            from_number,
            "✏️ Dato actualizado.\n\n" + build_profesional_confirmacion(session["temp_prof_data"])
        )
        return

    if session["pending_action"] == "pro_cv_confirmacion":
        if text_lower != "listo":
            enviar_respuesta(
                from_number,
                "Para continuar, cargá tu CV en el enlace y respondé *LISTO*.\n"
                f"🔗 {CV_UPLOAD_URL}\n\n"
                "0. Volver al menú principal"
            )
            return

        data = session.get("temp_prof_data", {})
        registro = {
            "fecha": datetime.now(ZoneInfo("America/Argentina/Mendoza")).isoformat(),
            "whatsapp": normalize_number(from_number),
            "nombre_apellido": data.get("nombre_apellido", ""),
            "profesion": data.get("profesion", ""),
            "nacionalidad": data.get("nacionalidad", ""),
            "dni": data.get("dni", ""),
            "descripcion_curso": data.get("descripcion_curso", ""),
            "cv_link": CV_UPLOAD_URL,
            "cv_confirmado": True,
        }
        save_profesional_interesado(registro)
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=registro.get("nombre_apellido", ""),
            telefono=from_number,
            intereses=["quiero_capacitar", registro.get("descripcion_curso", "")],
            evento="postulacion_profesional_confirmada",
            extra_fields={
                "postulacion_profesional": {
                    "profesion": registro.get("profesion", ""),
                    "nacionalidad": registro.get("nacionalidad", ""),
                    "dni": registro.get("dni", ""),
                    "descripcion_curso": registro.get("descripcion_curso", ""),
                    "cv_confirmado": True,
                }
            },
        )

        resumen = (
            "✅ ¡Postulación recibida!\n\n"
            "Datos registrados:\n"
            f"👤 Nombre y apellido: {registro['nombre_apellido']}\n"
            f"🧰 Profesión: {registro['profesion']}\n"
            f"🌎 Nacionalidad: {registro['nacionalidad']}\n"
            f"🪪 DNI: {registro['dni']}\n"
            f"📝 Curso a dictar: {registro['descripcion_curso']}\n"
            "📎 CV: carga confirmada\n\n"
            "Nuestro equipo revisará tu propuesta y te contactará a la brevedad."
        )
        enviar_respuesta(from_number, resumen)
        reset_user_flow(session)
        return

    if session["pending_action"] == "asesor_tipo":
        if text_lower in ["1", "empresa"]:
            session["temp_asesor_data"] = {"tipo": "empresa"}
            session["pending_action"] = "asesor_empresa_nombre"
            enviar_respuesta(from_number, "Indicános el *nombre de la empresa*:\n\n0. Volver al menú principal")
        elif text_lower in ["2", "persona", "persona fisica", "persona física"]:
            session["temp_asesor_data"] = {"tipo": "persona_fisica"}
            session["pending_action"] = "asesor_persona_nombre"
            enviar_respuesta(from_number, "Indicános tu *nombre completo*:\n\n0. Volver al menú principal")
        else:
            enviar_respuesta(
                from_number,
                "Seleccioná una opción válida:\n"
                "1. EMPRESA\n"
                "2. PERSONA FÍSICA\n\n"
                "0. Volver al menú principal"
            )
        return

    if session["pending_action"] == "asesor_empresa_nombre":
        if not validar_nombre_empresa(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El nombre de empresa no es válido (sin números).\n"
                "Ejemplo: *Servicios Andinos SRL*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_asesor_data"]["empresa_nombre"] = text_body.strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            intereses=["hablar_con_asesor", "asesoria_empresa"],
            evento="asesor_empresa_nombre",
        )
        session["pending_action"] = "asesor_empresa_correo"
        enviar_respuesta(from_number, "Indicános un *correo* de contacto:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_empresa_correo":
        if not validar_correo(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El correo no es válido.\n"
                "Ejemplo: *contacto@empresa.com*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_asesor_data"]["empresa_correo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_email"
        enviar_respuesta(from_number, "Indicános un *email* alternativo:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_empresa_email":
        if not validar_correo(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El email no es válido.\n"
                "Ejemplo: *rrhh@empresa.com*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_asesor_data"]["empresa_email"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_motivo"
        enviar_respuesta(from_number, "Describí el *motivo de la consulta*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_empresa_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(
                from_number,
                "⚠️ El motivo es muy breve. Contanos un poco más.\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, build_asesor_empresa_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_empresa_confirmacion":
        if text_lower == "c":
            data = session["temp_asesor_data"]
            registro = {
                "fecha": datetime.now(ZoneInfo("America/Argentina/Mendoza")).isoformat(),
                "whatsapp": normalize_number(from_number),
                "tipo": "empresa",
                "empresa_nombre": data.get("empresa_nombre", ""),
                "correo": data.get("empresa_correo", ""),
                "email": data.get("empresa_email", ""),
                "motivo": data.get("motivo", ""),
            }
            save_asesor_consulta(registro)
            upsert_user_profile_firestore(
                whatsapp_number=from_number,
                nombre=data.get("empresa_nombre", ""),
                telefono=from_number,
                intereses=["hablar_con_asesor", "asesoria_empresa", data.get("motivo", "")],
                evento="asesoria_empresa_confirmada",
                extra_fields={"consulta_asesor_empresa": registro},
            )
            enviar_respuesta(
                from_number,
                "✅ Consulta enviada correctamente.\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad.\n\n"
                "↩️ Volviste al menú principal.\n\n" + build_main_menu()
            )
            reset_user_flow(session)
        elif text == "1":
            session["pending_action"] = "asesor_empresa_edit_nombre"
            enviar_respuesta(from_number, "Ingresá el nuevo *nombre de la empresa*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "asesor_empresa_edit_correo"
            enviar_respuesta(from_number, "Ingresá el nuevo *correo*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "asesor_empresa_edit_email"
            enviar_respuesta(from_number, "Ingresá el nuevo *email*:\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "asesor_empresa_edit_motivo"
            enviar_respuesta(from_number, "Ingresá el nuevo *motivo*:\n\n0. Volver al menú principal")
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_asesor_empresa_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_empresa_edit_nombre":
        if not validar_nombre_empresa(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El nombre de empresa no es válido (sin números).\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_asesor_data"]["empresa_nombre"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_empresa_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_empresa_edit_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_correo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_empresa_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_empresa_edit_email":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El email no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_email"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_empresa_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_empresa_edit_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ El motivo es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_empresa_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_nombre":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(from_number, "⚠️ Ingresá un nombre completo válido (sin números).\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["nombre_completo"] = text_body.strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            intereses=["hablar_con_asesor", "asesoria_persona_fisica"],
            evento="asesor_persona_nombre",
        )
        session["pending_action"] = "asesor_persona_cuit"
        enviar_respuesta(from_number, "Indicános tu *CUIT*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_cuit":
        if not validar_cuit(text_body):
            enviar_respuesta(from_number, "⚠️ El CUIT no es válido.\nEjemplo: *20-12345678-3*\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["cuit"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "asesor_persona_telefono"
        enviar_respuesta(from_number, "Indicános tu *teléfono*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_telefono":
        if not validar_telefono(text_body):
            enviar_respuesta(from_number, "⚠️ El teléfono no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["telefono"] = text_body.strip()
        session["pending_action"] = "asesor_persona_dni"
        enviar_respuesta(from_number, "Indicános tu *DNI*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_dni":
        if not validar_dni(text_body):
            enviar_respuesta(from_number, "⚠️ El DNI no es válido. Debe tener 7 u 8 dígitos.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "asesor_persona_correo"
        enviar_respuesta(from_number, "Indicános tu *correo*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["correo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_motivo"
        enviar_respuesta(from_number, "Describí el *motivo de la consulta*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ El motivo es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_confirmacion":
        if text_lower == "c":
            data = session["temp_asesor_data"]
            registro = {
                "fecha": datetime.now(ZoneInfo("America/Argentina/Mendoza")).isoformat(),
                "whatsapp": normalize_number(from_number),
                "tipo": "persona_fisica",
                "nombre_completo": data.get("nombre_completo", ""),
                "cuit": data.get("cuit", ""),
                "telefono": data.get("telefono", ""),
                "dni": data.get("dni", ""),
                "correo": data.get("correo", ""),
                "motivo": data.get("motivo", ""),
            }
            save_asesor_consulta(registro)
            upsert_user_profile_firestore(
                whatsapp_number=from_number,
                nombre=data.get("nombre_completo", ""),
                telefono=from_number,
                intereses=["hablar_con_asesor", "asesoria_persona_fisica", data.get("motivo", "")],
                evento="asesoria_persona_confirmada",
                extra_fields={"consulta_asesor_persona": registro},
            )
            enviar_respuesta(
                from_number,
                "✅ Consulta enviada correctamente.\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad.\n\n"
                "↩️ Volviste al menú principal.\n\n" + build_main_menu()
            )
            reset_user_flow(session)
        elif text == "1":
            session["pending_action"] = "asesor_persona_edit_nombre"
            enviar_respuesta(from_number, "Ingresá el nuevo *nombre completo*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "asesor_persona_edit_cuit"
            enviar_respuesta(from_number, "Ingresá el nuevo *CUIT*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "asesor_persona_edit_telefono"
            enviar_respuesta(from_number, "Ingresá el nuevo *teléfono*:\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "asesor_persona_edit_dni"
            enviar_respuesta(from_number, "Ingresá el nuevo *DNI*:\n\n0. Volver al menú principal")
        elif text == "5":
            session["pending_action"] = "asesor_persona_edit_correo"
            enviar_respuesta(from_number, "Ingresá el nuevo *correo*:\n\n0. Volver al menú principal")
        elif text == "6":
            session["pending_action"] = "asesor_persona_edit_motivo"
            enviar_respuesta(from_number, "Ingresá el nuevo *motivo*:\n\n0. Volver al menú principal")
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_nombre":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(from_number, "⚠️ Nombre completo inválido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["nombre_completo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_cuit":
        if not validar_cuit(text_body):
            enviar_respuesta(from_number, "⚠️ El CUIT no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["cuit"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_telefono":
        if not validar_telefono(text_body):
            enviar_respuesta(from_number, "⚠️ El teléfono no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["telefono"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_dni":
        if not validar_dni(text_body):
            enviar_respuesta(from_number, "⚠️ El DNI no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["correo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ El motivo es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    direct_course_action = parse_course_action_identifier(text)
    if direct_course_action is not None:
        curso_id, action = direct_course_action
        handle_course_detail_action(from_number, curso_id, action)
        return

    direct_course_selection = parse_course_selection(text)
    if direct_course_selection is not None:
        session["in_course_menu"] = True
        session["in_course_detail"] = True
        session["current_course"] = direct_course_selection
        track_user_interest(from_number, menu_config["cursos"][direct_course_selection]["nombre"], "curso_seleccionado")
        enviar_detalle_curso(from_number, direct_course_selection)
        return

    if session["in_course_detail"]:
        curso_id = session["current_course"]
        selected_action = resolve_course_detail_action(text, curso_id)
        if selected_action in {"0", "1", "2", "3"}:
            handle_course_detail_action(from_number, curso_id, selected_action)
        else:
            enviar_respuesta(from_number, "Opción inválida. Elegí VER CURSO, TEMARIO, 3 o 0.")
            enviar_detalle_curso(from_number, curso_id)
        return

    if session["in_course_menu"]:
        if text == "0":
            session["in_course_menu"] = False
            enviar_respuesta(from_number, build_main_menu())
        elif text in menu_config["cursos"] or direct_course_selection is not None:
            selected_course_id = text if text in menu_config["cursos"] else direct_course_selection
            session["in_course_detail"] = True
            session["current_course"] = selected_course_id
            track_user_interest(from_number, menu_config["cursos"][selected_course_id]["nombre"], "curso_seleccionado")
            enviar_detalle_curso(from_number, selected_course_id)
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_courses_menu())
        return

    if session.get("in_response_menu"):
        if text == "0":
            session["in_response_menu"] = False
            session["last_response_option"] = None
            enviar_respuesta(from_number, build_main_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa: 0 para volver")
        return

    if text == "1":
        session["in_course_menu"] = True
        track_user_interest(from_number, "cursos_disponibles", "menu_opcion_1")
        enviar_respuesta(from_number, build_courses_menu())
        return

    if text == "2":
        session["temp_course_data"] = {}
        session["pending_action"] = "empresa_nombre"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "capacitaciones_empresas", "menu_opcion_2")
        enviar_respuesta(
            from_number,
            "Excelente. Para poder asesorarte mejor, indicános el nombre de la empresa:\n\n0. Volver al menú principal"
        )
        return

    if text == "3":
        session["temp_prof_data"] = {}
        session["pending_action"] = "pro_nombre_apellido"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "quiero_capacitar", "menu_opcion_3")
        enviar_respuesta(
            from_number,
            "¡Excelente! Vamos a registrar tu perfil para dictar capacitaciones.\n\n"
            "Indicános tu *Nombre y apellido*:\n\n"
            "0. Volver al menú principal"
        )
        return

    if text == "4":
        session["temp_asesor_data"] = {}
        session["pending_action"] = "asesor_tipo"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "hablar_con_asesor", "menu_opcion_4")
        enviar_respuesta(
            from_number,
            "Para hablar con un asesor, elegí el tipo de consulta:\n\n"
            "1. EMPRESA\n"
            "2. PERSONA FÍSICA\n\n"
            "0. Volver al menú principal"
        )
        return

    if text in menu_config["responses"]:
        msg = menu_config["responses"][text] + "\n\n0. ← Volver al menú principal"
        session["in_response_menu"] = True
        session["last_response_option"] = text
        enviar_respuesta(from_number, msg)
        return

    enviar_respuesta(from_number, "Opción inválida.\n\n" + build_main_menu())


def manejar_admin(from_number: str, text_body: str):
    global menu_config
    session = get_admin_session(from_number)
    text = text_body.strip()
    text_lower = text.lower()

    if session["awaiting_admin_password"]:
        if text == ADMIN_KEY:
            session["active"] = True
            session["awaiting_admin_password"] = False
            enviar_respuesta(from_number, build_admin_menu())
        else:
            session["awaiting_admin_password"] = False
            enviar_respuesta(from_number, "❌ Contraseña incorrecta.\n\n" + build_main_menu())
        return

    if not session["active"]:
        manejar_usuario(from_number, text_body)
        return

    if text_lower in ["hola", "menu", "inicio"]:
        session["active"] = False
        session["awaiting_admin_password"] = False
        reset_user_flow(session)
        enviar_respuesta(from_number, build_main_menu())
        return

    if session["pending_action"] == "awaiting_course_name":
        if text == "0":
            session["pending_action"] = None
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, build_courses_edit_menu())
            return
        session["temp_course_data"]["nombre"] = text_body
        enviar_respuesta(
            from_number,
            "✅ Nombre ingresado.\n\n📝 Ahora ingresa el link del curso (sitio web):\n\n0. Volver al menú admin"
        )
        session["pending_action"] = "awaiting_course_link"
        return

    if session["pending_action"] == "awaiting_course_link":
        if text == "0":
            session["pending_action"] = "awaiting_course_name"
            enviar_respuesta(from_number, "📝 ¿Cuál es el nombre del curso?\n\n0. Volver al menú admin")
            return
        session["temp_course_data"]["link_web"] = text_body
        enviar_respuesta(
            from_number,
            "✅ Link del curso ingresado.\n\n📄 Ahora ingresa el link del PDF del programa:\n\n0. Volver al menú admin"
        )
        session["pending_action"] = "awaiting_course_pdf"
        return

    if session["pending_action"] == "awaiting_course_pdf":
        if text == "0":
            session["pending_action"] = "awaiting_course_link"
            enviar_respuesta(from_number, "📝 Ingresa el link del curso (sitio web):\n\n0. Volver al menú admin")
            return
        session["temp_course_data"]["link_descarga"] = text_body

        resumen = " RESUMEN DE DATOS INGRESADOS\n\n"
        resumen += f" Nombre: {session['temp_course_data']['nombre']}\n"
        resumen += f" Link Curso: {session['temp_course_data']['link_web']}\n"
        resumen += f" Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
        resumen += "¿Deseas continuar?\n"
        resumen += "1. ACEPTAR\n"
        resumen += "2. EDITAR\n\n"
        resumen += "0. Volver al menú admin\n\n"
        resumen += "Escribe tu opción:"

        enviar_respuesta(from_number, resumen)
        session["pending_action"] = "confirm_course_data"
        return

    if session["pending_action"] == "confirm_course_data":
        if text == "1":
            max_id = max([int(k) for k in menu_config["cursos"].keys()]) if menu_config["cursos"] else 0
            nuevo_id = str(max_id + 1)

            menu_config["cursos"][nuevo_id] = {
                "nombre": session["temp_course_data"]["nombre"],
                "descripcion": session["temp_course_data"].get("descripcion", ""),
                "link_web": session["temp_course_data"]["link_web"],
                "link_descarga": session["temp_course_data"]["link_descarga"],
                "vendedor_id": "1"
            }
            save_menu_config(menu_config)

            enviar_respuesta(
                from_number,
                f"✅ Curso '{session['temp_course_data']['nombre']}' agregado exitosamente con ID {nuevo_id}.\n\n"
                + build_courses_edit_menu()
            )
            session["pending_action"] = None
            session["temp_course_data"] = {}
        elif text == "2":
            menu_edit = "✏️ ¿QUÉ DESEAS EDITAR?\n\n"
            menu_edit += "1. ✏️ Nombre\n"
            menu_edit += "2. ✏️ Link Curso\n"
            menu_edit += "3. ✏️ Link PDF\n"
            menu_edit += "\n0. Volver\n\nEscribe tu opción:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field_add"
        elif text == "0":
            session["pending_action"] = None
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, build_courses_edit_menu())
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Usa 1 o 2.")
        return

    if session["pending_action"] == "edit_course_field_add":
        fields = {
            "1": ("nombre", "Nombre del curso"),
            "2": ("link_web", "Link del curso"),
            "3": ("link_descarga", "Link del PDF")
        }
        if text == "0":
            resumen = "📋 RESUMEN DE DATOS INGRESADOS\n\n"
            resumen += f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
            resumen += f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
            resumen += f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
            resumen += "¿Deseas continuar?\n"
            resumen += "1. ✅ ACEPTAR\n"
            resumen += "2. ✏️ EDITAR\n\n"
            resumen += "Escribe tu opción:"
            enviar_respuesta(from_number, resumen)
            session["pending_action"] = "confirm_course_data"
        elif text in fields:
            field_key, field_name = fields[text]
            session["temp_field"] = field_key
            enviar_respuesta(from_number, f"📝 Ingresa el nuevo valor para {field_name}:\n\n0. Volver al menú admin")
            session["pending_action"] = "awaiting_field_value_add"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Intenta de nuevo.")
        return

    if session["pending_action"] == "awaiting_field_value_add":
        if text == "0":
            session["pending_action"] = "edit_course_field_add"
            session["temp_field"] = None
            menu_edit = "✏️ ¿QUÉ DESEAS EDITAR?\n\n"
            menu_edit += "1. ✏️ Nombre\n"
            menu_edit += "2. ✏️ Link Curso\n"
            menu_edit += "3. ✏️ Link PDF\n"
            menu_edit += "\n0. Volver\n\nEscribe tu opción:"
            enviar_respuesta(from_number, menu_edit)
            return
        field = session["temp_field"]
        session["temp_course_data"][field] = text_body

        resumen = "📋 RESUMEN DE DATOS INGRESADOS\n\n"
        resumen += f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
        resumen += f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
        resumen += f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
        resumen += "¿Deseas continuar?\n"
        resumen += "1. ✅ ACEPTAR\n"
        resumen += "2. ✏️ EDITAR\n\n"
        resumen += "Escribe tu opción:"

        enviar_respuesta(from_number, resumen)
        session["pending_action"] = "confirm_course_data"
        session["temp_field"] = None
        return

    if session["pending_action"] == "delete_course":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_courses_edit_menu())
            return
        if text in menu_config["cursos"]:
            curso = menu_config["cursos"][text]
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"⚠️ ¿Estás seguro de eliminar '{curso['nombre']}'?\n\n1. ✅ Sí\n0. ❌ No\n\nEscribe tu opción:"
            )
            session["pending_action"] = "confirm_delete_course"
        else:
            enviar_respuesta(from_number, "❌ Curso no encontrado. Intenta de nuevo.\n\n" + build_courses_menu())
        return

    if session["pending_action"] == "confirm_delete_course":
        if text == "1":
            curso_id = session["temp_option"]
            curso = menu_config["cursos"][curso_id]
            del menu_config["cursos"][curso_id]
            reorganize_course_ids()
            enviar_respuesta(
                from_number,
                f"✅ Curso '{curso['nombre']}' eliminado exitosamente.\n\nℹ️ Los IDs se han reorganizado automáticamente.\n\n"
                + build_courses_edit_menu()
            )
        elif text == "0":
            enviar_respuesta(from_number, "❌ Eliminación cancelada.\n\n" + build_courses_edit_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa 1 o 0.")
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "edit_course_select":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_courses_edit_menu())
            return
        if text in menu_config["cursos"]:
            session["current_course"] = text
            curso = menu_config["cursos"][text]
            menu_edit = f"📝 EDITAR CURSO: {curso['nombre']}\n\n"
            menu_edit += "1. ✏️ Nombre\n"
            menu_edit += "2. ✏️ Descripción\n"
            menu_edit += "3. ✏️ Link web\n"
            menu_edit += "4. ✏️ Link descarga\n"
            menu_edit += "\n0. Volver\n\nEscribe el número del campo a editar:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
        else:
            enviar_respuesta(from_number, "❌ Curso no encontrado. Intenta de nuevo.\n\n" + build_courses_menu())
        return

    if session["pending_action"] == "edit_course_field":
        fields = {"1": "nombre", "2": "descripcion", "3": "link_web", "4": "link_descarga"}
        if text == "0":
            session["pending_action"] = None
            session["current_course"] = None
            enviar_respuesta(from_number, build_courses_edit_menu())
        elif text in fields:
            session["temp_field"] = fields[text]
            field_name = {
                "nombre": "nombre",
                "descripcion": "descripción",
                "link_web": "link web",
                "link_descarga": "link de descarga"
            }
            enviar_respuesta(
                from_number,
                f"📝 Ingresa el nuevo valor para {field_name.get(fields[text], fields[text])}:\n\n0. Volver al menú admin"
            )
            session["pending_action"] = "awaiting_field_value"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Intenta de nuevo.")
        return

    if session["pending_action"] == "awaiting_field_value":
        if text == "0":
            session["pending_action"] = "edit_course_field"
            curso_id = session["current_course"]
            curso = menu_config["cursos"].get(curso_id, {})
            menu_edit = f"📝 EDITAR CURSO: {curso.get('nombre', 'N/A')}\n\n"
            menu_edit += "1. ✏️ Nombre\n"
            menu_edit += "2. ✏️ Descripción\n"
            menu_edit += "3. ✏️ Link web\n"
            menu_edit += "4. ✏️ Link descarga\n"
            menu_edit += "\n0. Volver\n\nEscribe el número del campo a editar:"
            enviar_respuesta(from_number, menu_edit)
            return
        curso_id = session["current_course"]
        field = session["temp_field"]
        menu_config["cursos"][curso_id][field] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, f"✅ Campo actualizado exitosamente.\n\n" + build_courses_edit_menu())
        session["pending_action"] = None
        session["temp_field"] = None
        session["current_course"] = None
        return

    if session["in_courses_edit_menu"]:
        if text == "0":
            session["in_courses_edit_menu"] = False
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text == "1":
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, "📝 AGREGAR NUEVO CURSO\n\n¿Cuál es el nombre del curso?")
            session["pending_action"] = "awaiting_course_name"
        elif text == "2":
            enviar_respuesta(from_number, "❌ Ingresa el número del curso a eliminar:\n\n" + build_courses_menu())
            session["pending_action"] = "delete_course"
        elif text == "3":
            enviar_respuesta(from_number, "✏️ Ingresa el número del curso a editar:\n\n" + build_courses_menu())
            session["pending_action"] = "edit_course_select"
        elif text == "4":
            enviar_respuesta(from_number, build_courses_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_courses_edit_menu())
        return

    if session["pending_action"] is None:
        if text == "0":
            session["active"] = False
            reset_user_flow(session)
            enviar_respuesta(from_number, build_main_menu())
            return

        if text == "1":
            enviar_respuesta(from_number, "📋 " + build_main_menu())
            return

        if text == "2":
            enviar_respuesta(
                from_number,
                f"📝 MENSAJE ACTUAL:\n\n{menu_config['greeting']}\n\n✏️ Escribe el nuevo saludo:\n\n0. Volver al menú admin"
            )
            session["pending_action"] = "edit_greeting"
            return

        if text == "3":
            menu_str = "✏️ EDITAR OPCIÓN DEL MENÚ\n\n"
            for key in sorted(menu_config["options"].keys(), key=int):
                menu_str += f"{key}. {menu_config['options'][key]}\n"
            menu_str += "\n¿Qué opción deseas editar? (1-" + str(len(menu_config["options"])) + ")\n0. Volver al menú admin"
            enviar_respuesta(from_number, menu_str)
            session["pending_action"] = "edit_option_select"
            return

        if text == "4":
            enviar_respuesta(from_number, "➕ AGREGAR NUEVA OPCIÓN\n\n¿Cuál es el título de la nueva opción?\n\n0. Volver al menú admin")
            session["pending_action"] = "add_option_title"
            return

        if text == "5":
            resp_str = "📝 EDITAR RESPUESTA\n\n"
            for key in sorted(menu_config["responses"].keys(), key=int):
                resp_str += f"{key}. {menu_config['responses'][key][:40]}...\n"
            resp_str += "\n¿Qué respuesta deseas editar? (1-" + str(len(menu_config["responses"])) + ")\n0. Volver al menú admin"
            enviar_respuesta(from_number, resp_str)
            session["pending_action"] = "edit_response_select"
            return

        if text == "6":
            session["in_courses_edit_menu"] = True
            enviar_respuesta(from_number, build_courses_edit_menu())
            return

        if text == "7":
            enviar_respuesta(from_number, build_vendor_menu())
            session["pending_action"] = "vendor_menu"
            return

        if text == "8":
            if session["change_history"]:
                ultimo_cambio = session["change_history"].pop()
                enviar_respuesta(from_number, f"⏮️ Cambio deshecho:\n{ultimo_cambio}\n\n" + build_admin_menu())
            else:
                enviar_respuesta(from_number, "❌ No hay cambios para deshacer.\n\n" + build_admin_menu())
            return

        if text == "9":
            session["active"] = False
            reset_user_flow(session)
            enviar_respuesta(from_number, "✅ Admin desactivado.\n\n" + build_main_menu())
            return

        if text == "10":
            enviar_respuesta(from_number, build_backup_menu())
            session["pending_action"] = "backup_menu"
            return

        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_admin_menu())
        return

    if session["pending_action"] == "edit_greeting":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
            return
        session["change_history"].append(f"Saludo anterior: {menu_config['greeting'][:50]}...")
        menu_config["greeting"] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Saludo actualizado.\n\n" + build_admin_menu())
        session["pending_action"] = None
        return

    if session["pending_action"] == "edit_option_select":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text in menu_config["options"]:
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"✏️ OPCIÓN ACTUAL: {menu_config['options'][text]}\n\nEscribe el nuevo texto:\n\n0. Volver al menú admin"
            )
            session["pending_action"] = "edit_option_text"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.")
        return

    if session["pending_action"] == "edit_option_text":
        if text == "0":
            session["pending_action"] = None
            session["temp_option"] = None
            enviar_respuesta(from_number, build_admin_menu())
            return
        option_id = session["temp_option"]
        session["change_history"].append(f"Opción {option_id}: '{menu_config['options'][option_id]}' → '{text_body}'")
        menu_config["options"][option_id] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Opción actualizada.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "add_option_title":
        if text == "0":
            session["pending_action"] = None
            session["temp_option_text"] = None
            enviar_respuesta(from_number, build_admin_menu())
            return
        session["temp_option_text"] = text_body
        enviar_respuesta(
            from_number,
            f"💬 Título: '{text_body}'\n\n¿Cuál será la respuesta a esta opción?\n\n0. Volver al menú admin"
        )
        session["pending_action"] = "add_option_response"
        return

    if session["pending_action"] == "add_option_response":
        if text == "0":
            session["pending_action"] = None
            session["temp_option_text"] = None
            enviar_respuesta(from_number, build_admin_menu())
            return
        max_id = max([int(k) for k in menu_config["options"].keys()]) if menu_config["options"] else 0
        nuevo_id = str(max_id + 1)
        menu_config["options"][nuevo_id] = session["temp_option_text"]
        menu_config["responses"][nuevo_id] = text_body
        save_menu_config(menu_config)
        session["change_history"].append(f"Opción agregada: {nuevo_id}. {session['temp_option_text']}")
        enviar_respuesta(from_number, f"✅ Opción [{nuevo_id}] agregada con éxito.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option_text"] = None
        return

    if session["pending_action"] == "edit_response_select":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text in menu_config["responses"]:
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"📝 RESPUESTA ACTUAL ({text}):\n\n{menu_config['responses'][text]}\n\n✏️ Escribe la nueva respuesta:\n\n0. Volver al menú admin"
            )
            session["pending_action"] = "edit_response_text"
        else:
            enviar_respuesta(from_number, "❌ Respuesta no encontrada.")
        return

    if session["pending_action"] == "edit_response_text":
        if text == "0":
            session["pending_action"] = None
            session["temp_option"] = None
            enviar_respuesta(from_number, build_admin_menu())
            return
        response_id = session["temp_option"]
        session["change_history"].append(
            f"Respuesta {response_id}: '{menu_config['responses'][response_id][:40]}...' → '{text_body[:40]}...'"
        )
        menu_config["responses"][response_id] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Respuesta actualizada.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "vendor_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text == "1":
            enviar_respuesta(from_number, "➕ AGREGAR VENDEDOR\n\n¿Cuál es el nombre del vendedor?\n\n0. Volver al menú de vendedores")
            session["pending_action"] = "add_vendor_name"
        elif text == "2":
            if not menu_config["vendedores"]:
                enviar_respuesta(from_number, "⚠️ No hay vendedores cargados.\n\n" + build_vendor_menu())
                return
            vendor_str = "📋 LISTADO ACTUAL DE VENDEDORES\n\n"
            for key in sorted(menu_config["vendedores"].keys(), key=int):
                vendor = menu_config["vendedores"][key]
                vendor_str += f"{key}. {vendor['nombre']} {vendor['apellido']}\n"
            vendor_str += "\n¿Cuál deseas editar?\n0. Volver al menú de vendedores"
            enviar_respuesta(from_number, vendor_str)
            session["pending_action"] = "edit_vendor_select"
        elif text == "3":
            if not menu_config["vendedores"]:
                enviar_respuesta(from_number, "⚠️ No hay vendedores cargados.\n\n" + build_vendor_menu())
                return
            vendor_str = "❌ ELIMINAR VENDEDOR\n\n"
            for key in sorted(menu_config["vendedores"].keys(), key=int):
                vendor = menu_config["vendedores"][key]
                vendor_str += f"{key}. {vendor['nombre']} {vendor['apellido']}\n"
            vendor_str += "\n¿Cuál deseas eliminar?\n0. Volver al menú de vendedores"
            enviar_respuesta(from_number, vendor_str)
            session["pending_action"] = "delete_vendor"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_menu())
        return

    if session["pending_action"] == "add_vendor_name":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session["temp_option_text"] = None
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, build_vendor_menu())
            return
        session["temp_option_text"] = text_body
        session["temp_course_data"] = {}
        enviar_respuesta(from_number, "Correo:\n\n0. Volver al menú de vendedores")
        session["pending_action"] = "add_vendor_email"
        return

    if session["pending_action"] == "add_vendor_phone":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session["temp_option_text"] = None
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, build_vendor_menu())
            return
        session["temp_course_data"]["telefono"] = text_body
        max_id = max([int(k) for k in menu_config["vendedores"].keys()]) if menu_config["vendedores"] else 0
        nuevo_id = str(max_id + 1)
        menu_config["vendedores"][nuevo_id] = {
            "nombre": session["temp_option_text"],
            "apellido": "",
            "telefono": session["temp_course_data"].get("telefono", ""),
            "correo": session["temp_course_data"].get("correo", "")
        }
        save_menu_config(menu_config)
        session["change_history"].append(f"Vendedor agregado: {session['temp_option_text']}")
        enviar_respuesta(from_number, "✅ Vendedor agregado.\n\n" + build_vendor_menu())
        session["pending_action"] = "vendor_menu"
        session["temp_option_text"] = None
        session["temp_course_data"] = {}
        return

    if session["pending_action"] == "add_vendor_email":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session["temp_option_text"] = None
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, build_vendor_menu())
            return
        session["temp_course_data"]["correo"] = text_body
        enviar_respuesta(from_number, "Teléfono:\n\n0. Volver al menú de vendedores")
        session["pending_action"] = "add_vendor_phone"
        return

    if session["pending_action"] == "edit_vendor_select":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session["temp_option"] = None
            enviar_respuesta(from_number, build_vendor_menu())
        elif text in menu_config["vendedores"]:
            session["temp_option"] = text
            vendor = menu_config["vendedores"][text]
            menu_edit = f"✏️ EDITAR VENDEDOR: {vendor['nombre']} {vendor['apellido']}\n\n"
            menu_edit += "1. 📝 Nombre\n"
            menu_edit += "2. 📝 Apellido\n"
            menu_edit += "3. 📱 Teléfono\n"
            menu_edit += "4. 📧 Correo\n"
            menu_edit += "\n0. Volver\n\nEscribe tu opción:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_vendor_field"
        else:
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.")
        return

    if session["pending_action"] == "edit_vendor_field":
        fields = {"1": "nombre", "2": "apellido", "3": "telefono", "4": "correo"}
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session["temp_option"] = None
            enviar_respuesta(from_number, build_vendor_menu())
        elif text in fields:
            session["temp_field"] = fields[text]
            field_names = {
                "nombre": "Nombre",
                "apellido": "Apellido",
                "telefono": "Teléfono",
                "correo": "Correo"
            }
            enviar_respuesta(from_number, f"📝 Nuevo {field_names.get(fields[text], fields[text])}:\n\n0. Volver al menú de vendedores")
            session["pending_action"] = "edit_vendor_value"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.")
        return

    if session["pending_action"] == "edit_vendor_value":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session["temp_field"] = None
            session["temp_option"] = None
            enviar_respuesta(from_number, build_vendor_menu())
            return
        vendor_id = session["temp_option"]
        field = session["temp_field"]
        menu_config["vendedores"][vendor_id][field] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Vendedor actualizado.\n\n" + build_vendor_menu())
        session["pending_action"] = "vendor_menu"
        session["temp_field"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "delete_vendor":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session["temp_option"] = None
            enviar_respuesta(from_number, build_vendor_menu())
        elif text in menu_config["vendedores"]:
            vendor = menu_config["vendedores"][text]
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"⚠️ ¿Estás seguro de eliminar '{vendor['nombre']} {vendor['apellido']}'?\n\n1. ✅ Sí\n0. ❌ No"
            )
            session["pending_action"] = "confirm_delete_vendor"
        else:
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.")
        return

    if session["pending_action"] == "confirm_delete_vendor":
        if text == "1":
            vendor_id = session["temp_option"]
            vendor = menu_config["vendedores"][vendor_id]
            del menu_config["vendedores"][vendor_id]
            save_menu_config(menu_config)
            session["change_history"].append(f"Vendedor eliminado: {vendor['nombre']} {vendor['apellido']}")
            enviar_respuesta(from_number, "✅ Vendedor eliminado.\n\n" + build_vendor_menu())
        elif text == "0":
            enviar_respuesta(from_number, "❌ Eliminación cancelada.\n\n" + build_vendor_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa 1 o 0.")
            return
        session["pending_action"] = "vendor_menu"
        session["temp_option"] = None
        return

    if session["pending_action"] == "backup_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text == "1":
            filename = create_menu_backup()
            enviar_respuesta(
                from_number,
                f"✅ Backup creado exitosamente.\n\n📁 Archivo: {filename}\n\n" + build_backup_menu()
            )
        elif text == "2":
            backups = list_backups()
            if not backups:
                enviar_respuesta(from_number, "⚠️ No hay backups disponibles.\n\n" + build_backup_menu())
            else:
                lista = "🔄 RESTAURAR BACKUP\n\nSeleccioná el número del backup a restaurar:\n\n"
                for i, fname in enumerate(backups, start=1):
                    lista += f"{i}. {fname}\n"
                lista += "\n0. Volver"
                session["temp_course_data"]["backup_list"] = backups
                enviar_respuesta(from_number, lista)
                session["pending_action"] = "backup_restore_select"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_backup_menu())
        return

    if session["pending_action"] == "backup_restore_select":
        backups = session["temp_course_data"].get("backup_list", [])
        if text == "0":
            session["pending_action"] = "backup_menu"
            session["temp_course_data"].pop("backup_list", None)
            enviar_respuesta(from_number, build_backup_menu())
        elif text.isdigit() and 1 <= int(text) <= len(backups):
            selected = backups[int(text) - 1]
            session["temp_option"] = selected
            enviar_respuesta(
                from_number,
                f"⚠️ ¿Restaurar el backup?\n\n📁 {selected}\n\n"
                "⚠️ Esta acción reemplazará la configuración actual.\n\n"
                "1. ✅ Confirmar\n"
                "0. ❌ Cancelar"
            )
            session["pending_action"] = "backup_restore_confirm"
        else:
            enviar_respuesta(from_number, "❌ Número inválido. Intenta de nuevo.")
        return

    if session["pending_action"] == "backup_restore_confirm":
        if text == "1":
            filename = session["temp_option"]
            if restore_menu_backup(filename):
                enviar_respuesta(
                    from_number,
                    f"✅ Configuración restaurada exitosamente desde:\n📁 {filename}\n\n" + build_backup_menu()
                )
            else:
                enviar_respuesta(from_number, "❌ Error al restaurar. El archivo no fue encontrado.\n\n" + build_backup_menu())
            session["pending_action"] = "backup_menu"
            session["temp_option"] = None
            session["temp_course_data"].pop("backup_list", None)
        elif text == "0":
            enviar_respuesta(from_number, "❌ Restauración cancelada.\n\n" + build_backup_menu())
            session["pending_action"] = "backup_menu"
            session["temp_option"] = None
            session["temp_course_data"].pop("backup_list", None)
        else:
            enviar_respuesta(from_number, "Opción inválida. Usá 1 para confirmar o 0 para cancelar.")
        return

    enviar_respuesta(from_number, "❌ Opción inválida. " + build_admin_menu())


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Invalid token", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print("Webhook:", data)
    print("APP_VERSION webhook:", APP_VERSION)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        messages = value.get("messages")
        statuses = value.get("statuses")

        if messages:
            print("MENSAJE ENTRANTE:", messages)

        if statuses:
            print("STATUS:", statuses)

        if messages:
            msg = messages[0]
            from_number = msg.get("from", "")

            text_body = extract_message_text(msg)
            if text_body is not None:
                print(f"De {from_number}: {text_body}")
                manejar_admin(from_number, text_body)
            else:
                print(f"Mensaje no soportado. Tipo recibido: {msg.get('type')}")

    except Exception as e:
        print(f"Error en webhook: {e}")
        import traceback
        traceback.print_exc()

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)