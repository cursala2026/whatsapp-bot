"""Bot de WhatsApp para Cursala.

Estructura general del archivo:
- Configuracion global y variables de entorno.
- Endpoints de administracion y consulta.
- Utilidades de normalizacion y persistencia.
- Constructores de menu y validaciones.
- Envio de mensajes a WhatsApp API.
- Flujos conversacionales (usuario y admin).
- Webhook de entrada y arranque local.
"""

# ============================================================
# SECCION 1 - IMPORTS Y DEPENDENCIAS
# ============================================================
from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo
from google import genai
import os
import json
import csv
import io
import time
import random
import requests
import re
import unicodedata
from urllib.parse import quote
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import firebase_admin  # type: ignore[import-not-found]
    from firebase_admin import credentials, firestore  # type: ignore[import-not-found]
except Exception:
    firebase_admin = None
    credentials = None
    firestore = None

from email_service import enviar_correo_brevo, procesar_notificacion_registro, enviar_notificacion_evento  # noqa: E402

# ============================================================
# SECCION 2 - CONFIGURACION GLOBAL Y VARIABLES DE ENTORNO
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
CONFIG_PATH = os.path.join(BASE_DIR, "menu_config.json")
BACKUPS_DIR = os.path.join(BASE_DIR, "menu_backups")
INTERESADOS_PATH = os.path.join(BASE_DIR, "profesionales_interesados.json")
ASESOR_CONSULTAS_PATH = os.path.join(BASE_DIR, "asesor_consultas.json")
CV_UPLOAD_URL = "https://drive.google.com/drive/folders/1tfEH_v1N3LqCLQQ_aWNIyaIbz9UYm_5K?usp=drive_link"
APP_VERSION = "2026-03-26-bsuid-meta-compliance-v1"
FIREBASE_CREDENTIALS_PATH = os.path.join(BASE_DIR, "firebase_service_account.json")
FIREBASE_PROJECT_ID = ""
FIRESTORE_COLLECTION = "whatsapp_users"
USER_INACTIVITY_TIMEOUT_SECONDS = 300

load_dotenv(dotenv_path=ENV_PATH)


def clean_env_value(value: str) -> str:
    return (value or "").replace("\ufeff", "").strip()


GEMINI_API_KEY = clean_env_value(os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
ENABLE_GEMINI_FALLBACK = os.getenv("ENABLE_GEMINI_FALLBACK", "false").lower() == "true"

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

print("Buscando .env en:", ENV_PATH)
print("Existe .env?:", os.path.exists(ENV_PATH))
print("APP_VERSION:", APP_VERSION)

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
K_SERVICE = os.getenv("K_SERVICE", "")
K_REVISION = os.getenv("K_REVISION", "")
K_CONFIGURATION = os.getenv("K_CONFIGURATION", "")

print("VERIFY_TOKEN cargado:", repr(VERIFY_TOKEN))


# ============================================================
# SECCION 3 - ENDPOINTS DE SALUD Y ADMINISTRACION
# ============================================================
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


def build_runtime_revision_message() -> str:
    runtime_service = K_SERVICE or "local"
    runtime_revision = K_REVISION or "local-dev"
    runtime_configuration = K_CONFIGURATION or "local"

    menu_revision = menu_config.get("revision", {}) if isinstance(menu_config, dict) else {}
    menu_version = menu_revision.get("version", "1.0.0")
    menu_fecha = menu_revision.get("fecha", "—")
    menu_hora = menu_revision.get("hora", "—")

    return (
        "*REVISIÓN DEL SISTEMA*\n\n"
        + build_labeled_data_block([
            ("App version", APP_VERSION),
            ("Servicio runtime", runtime_service),
            ("Revisión deploy", runtime_revision),
            ("Configuración deploy", runtime_configuration),
        ])
        + "\n\n*REVISIÓN DE MENÚ / CONFIG*\n\n"
        + build_labeled_data_block([
            ("Versión menú", menu_version),
            ("Fecha último cambio menú", menu_fecha),
            ("Hora último cambio menú", menu_hora),
        ])
        + "\n\n"
        "0. Volver al menú admin"
    )


def format_display_value(value: Any) -> str:
    text = str(value or "").strip()
    return text.lower() if text else "—"


def build_labeled_data_block(items: List[Tuple[str, Any]]) -> str:
    blocks = []
    for label, value in items:
        blocks.append(f"*{label.strip().upper()}*\n{format_display_value(value)}")
    return "\n\n".join(blocks)


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


def _normalize_intereses_backup(intereses_raw: Any) -> List[str]:
    if not intereses_raw:
        return []
    if isinstance(intereses_raw, str):
        cleaned = " ".join(intereses_raw.strip().split())
        return [cleaned] if cleaned else []
    if isinstance(intereses_raw, list):
        cleaned_items = []
        for item in intereses_raw:
            item_clean = " ".join(str(item).strip().split())
            if item_clean:
                cleaned_items.append(item_clean)
        return cleaned_items
    return []


def import_contacts_backup_to_firestore(
    payload: dict,
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    """Importa contactos de backup a Firestore priorizando la persistencia del telefono.

    Reglas:
    - Si no hay telefono valido, el contacto se omite.
    - Si hay telefono, se guarda aunque el resto de campos esten incompletos.
    - Deduplica por telefono normalizado dentro del mismo payload.
    - Si el numero ya existe en Firestore, se omite para evitar sobrescribir.
    """
    contactos = payload.get("contactos")
    if not isinstance(contactos, list):
        raise HTTPException(status_code=400, detail="Formato invalido: 'contactos' debe ser una lista")

    origen_default = " ".join(str(payload.get("origen", "backup_json")).strip().split()) or "backup_json"
    evento_default = " ".join(str(payload.get("evento_default", "importacion_backup")).strip().split()) or "importacion_backup"

    seen_phones = set()
    imported = 0
    skipped_no_phone = 0
    skipped_duplicates = 0
    skipped_existing = 0
    skipped_invalid = 0
    failed = 0
    failures = []

    total_contacts = len(contactos)

    def _tick_progress(processed: int) -> None:
        if not progress_callback:
            return
        percent = 100 if total_contacts == 0 else int((processed / total_contacts) * 100)
        progress_callback(processed, total_contacts, percent)

    for idx, item in enumerate(contactos, start=1):
        if not isinstance(item, dict):
            skipped_invalid += 1
            failures.append({"index": idx, "error": "item_no_es_objeto"})
            _tick_progress(idx)
            continue

        raw_phone = (
            item.get("whatsapp_number")
            or item.get("phone")
            or item.get("telefono")
            or item.get("numero")
        )
        normalized_phone = normalize_number(raw_phone)

        if not normalized_phone:
            skipped_no_phone += 1
            failures.append({"index": idx, "error": "telefono_invalido_o_ausente"})
            _tick_progress(idx)
            continue

        if normalized_phone in seen_phones:
            skipped_duplicates += 1
            _tick_progress(idx)
            continue
        seen_phones.add(normalized_phone)

        try:
            existing_doc = firestore_db.collection(FIRESTORE_COLLECTION).document(normalized_phone).get()
            if existing_doc.exists:
                skipped_existing += 1
                _tick_progress(idx)
                continue
        except Exception as e:
            failed += 1
            failures.append({"index": idx, "telefono": normalized_phone, "error": f"error_verificando_existencia: {e}"})
            _tick_progress(idx)
            continue

        nombre = " ".join(str(item.get("nombre", "")).strip().split())
        etiqueta_cliente = " ".join(str(item.get("etiqueta_cliente", "")).strip().split())
        intereses = _normalize_intereses_backup(item.get("intereses"))
        ultimo_evento = " ".join(str(item.get("ultimo_evento", evento_default)).strip().split()) or "importacion_backup"

        extra_fields: Dict[str, Any] = {}
        if isinstance(item.get("extra_fields"), dict):
            extra_fields.update(item.get("extra_fields", {}))

        origen_item = " ".join(str(item.get("origen", "")).strip().split())
        extra_fields["origen"] = origen_item or origen_default
        extra_fields.setdefault("contacto_agendado", True)
        extra_fields.setdefault("agendado_por", "importacion_backup")

        try:
            upsert_user_profile_firestore(
                whatsapp_number=normalized_phone,
                nombre=nombre or None,
                telefono=normalized_phone,
                intereses=intereses or None,
                evento=ultimo_evento,
                extra_fields=extra_fields,
                etiqueta_cliente=etiqueta_cliente or None,
            )
            imported += 1
        except Exception as e:
            failed += 1
            failures.append({"index": idx, "telefono": normalized_phone, "error": str(e)})
        finally:
            _tick_progress(idx)

    return {
        "ok": True,
        "collection": FIRESTORE_COLLECTION,
        "summary": {
            "total_recibidos": len(contactos),
            "importados": imported,
            "omitidos_sin_telefono": skipped_no_phone,
            "omitidos_duplicados": skipped_duplicates,
            "omitidos_ya_registrados": skipped_existing,
            "omitidos_invalidos": skipped_invalid,
            "fallidos": failed,
        },
        "failures_preview": failures[:25],
    }


@app.post("/admin/firestore/contacts/import")
async def admin_import_contacts_backup(
    payload: dict,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    validate_admin_api_key(x_admin_key)

    if firestore_db is None:
        raise HTTPException(status_code=503, detail="Firestore no configurado")

    return import_contacts_backup_to_firestore(payload)


def _normalize_csv_header(header: str) -> str:
    raw = (header or "").strip().lower()
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.replace("-", "_").replace(" ", "_")
    return raw


def _extract_phone_from_row(row: Dict[str, Any]) -> str:
    candidates = [
        "whatsapp_number",
        "phone",
        "telefono",
        "numero",
        "celular",
        "movil",
        "wa_id",
    ]
    for key in candidates:
        value = row.get(key)
        normalized = normalize_number(value)
        if normalized:
            return normalized
    return ""


def _parse_intereses_csv(value: str) -> List[str]:
    if not value:
        return []
    raw = value.replace(";", ",").replace("|", ",")
    items = [" ".join(part.strip().split()) for part in raw.split(",")]
    return [item for item in items if item]


def parse_csv_contacts_file(file_bytes: bytes) -> List[dict]:
    content = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            content = file_bytes.decode(encoding)
            break
        except Exception:
            continue

    if not content:
        return []

    reader = csv.DictReader(io.StringIO(content))
    contacts = []

    for raw_row in reader:
        normalized_row = {}
        for key, value in (raw_row or {}).items():
            normalized_row[_normalize_csv_header(str(key))] = " ".join(str(value or "").strip().split())

        phone = _extract_phone_from_row(normalized_row)
        nombre = normalized_row.get("nombre") or normalized_row.get("name") or normalized_row.get("full_name")
        etiqueta = (
            normalized_row.get("etiqueta_cliente")
            or normalized_row.get("etiqueta")
            or normalized_row.get("tag")
            or normalized_row.get("label")
        )
        intereses_raw = normalized_row.get("intereses") or normalized_row.get("interes") or normalized_row.get("tags")
        ultimo_evento = normalized_row.get("ultimo_evento") or "importacion_backup_csv"

        contacto = {
            "whatsapp_number": phone,
            "nombre": nombre or "",
            "etiqueta_cliente": etiqueta or "",
            "intereses": _parse_intereses_csv(intereses_raw or ""),
            "ultimo_evento": ultimo_evento,
        }
        contacts.append(contacto)

    return contacts


def build_upload_progress_message(percent: int, stage: str) -> str:
    safe_percent = max(0, min(100, int(percent)))
    filled = safe_percent // 10
    bar = ("#" * filled) + ("-" * (10 - filled))
    return f"CARGA CSV: {safe_percent}%\n[{bar}]\n{stage}"


def download_whatsapp_media_content(media_id: str) -> Tuple[bool, bytes, str]:
    if not ACCESS_TOKEN:
        return False, b"", "ACCESS_TOKEN no configurado"

    try:
        meta_resp = requests.get(
            f"https://graph.facebook.com/v23.0/{media_id}",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            timeout=30,
        )
        if meta_resp.status_code != 200:
            return False, b"", f"Error consultando media metadata: {meta_resp.status_code}"

        media_url = (meta_resp.json() or {}).get("url", "")
        if not media_url:
            return False, b"", "No se obtuvo URL de descarga"

        file_resp = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            timeout=60,
        )
        if file_resp.status_code != 200:
            return False, b"", f"Error descargando archivo: {file_resp.status_code}"

        return True, file_resp.content, "ok"
    except Exception as e:
        return False, b"", str(e)


def process_admin_csv_document_message(from_number: str, msg: dict) -> bool:
    session = get_admin_session(from_number)
    if not (session.get("active") and session.get("pending_action") == "contacts_admin_waiting_csv"):
        return False

    document = msg.get("document", {})
    media_id = document.get("id", "")
    filename = (document.get("filename") or "").lower()

    enviar_respuesta(from_number, build_upload_progress_message(0, "Archivo recibido. Iniciando validacion..."))

    if not media_id:
        enviar_respuesta(from_number, "⚠️ No pude leer el archivo. Reenviá el CSV como documento.")
        return True

    if filename and not filename.endswith(".csv"):
        enviar_respuesta(from_number, "⚠️ El archivo debe ser CSV (.csv). Volvé a enviarlo como documento.")
        return True

    enviar_respuesta(from_number, build_upload_progress_message(15, "Validacion OK. Descargando archivo desde Meta..."))

    ok, content, detail = download_whatsapp_media_content(media_id)
    if not ok:
        enviar_respuesta(from_number, f"⚠️ Error descargando CSV desde Meta: {detail}")
        return True

    enviar_respuesta(from_number, build_upload_progress_message(35, "Archivo descargado. Parseando CSV..."))

    contacts = parse_csv_contacts_file(content)
    enviar_respuesta(
        from_number,
        build_upload_progress_message(50, f"CSV parseado. Contactos detectados: {len(contacts)}. Iniciando importacion...")
    )

    progress_state = {"last_bucket": 50}

    def _progress_callback(processed: int, total: int, percent: int) -> None:
        if total <= 0:
            return
        bucket = max(50, min(95, (percent // 10) * 10))
        if bucket > progress_state["last_bucket"]:
            progress_state["last_bucket"] = bucket
            enviar_respuesta(
                from_number,
                build_upload_progress_message(bucket, f"Importando contactos ({processed}/{total})...")
            )

    result = import_contacts_backup_to_firestore(
        {
            "origen": "backup_csv_whatsapp",
            "evento_default": "importacion_backup_csv",
            "contactos": contacts,
        },
        progress_callback=_progress_callback,
    )

    summary = result.get("summary", {})
    enviar_respuesta(
        from_number,
        build_upload_progress_message(100, "Importacion finalizada.")
        + "\n\n"
        + "✅ Importación CSV finalizada.\n\n"
        f"Recibidos: {summary.get('total_recibidos', 0)}\n"
        f"Importados: {summary.get('importados', 0)}\n"
        f"Omitidos sin teléfono: {summary.get('omitidos_sin_telefono', 0)}\n"
        f"Omitidos duplicados: {summary.get('omitidos_duplicados', 0)}\n"
        f"Omitidos ya registrados: {summary.get('omitidos_ya_registrados', 0)}\n"
        f"Omitidos inválidos: {summary.get('omitidos_invalidos', 0)}\n"
        f"Fallidos: {summary.get('fallidos', 0)}\n\n"
        + build_contacts_admin_menu()
    )
    session["pending_action"] = "contacts_admin_menu"
    return True


def build_contacts_saved_list_message(limit: int = 20) -> str:
    if firestore_db is None:
        return "⚠️ Firestore no configurado."

    safe_limit = max(1, min(limit, 50))
    docs = []

    try:
        if firestore is not None and hasattr(firestore, "Query"):
            docs = list(
                firestore_db
                .collection(FIRESTORE_COLLECTION)
                .order_by("actualizado_en", direction=firestore.Query.DESCENDING)
                .limit(safe_limit)
                .stream()
            )
        else:
            docs = list(
                firestore_db
                .collection(FIRESTORE_COLLECTION)
                .limit(safe_limit)
                .stream()
            )
    except Exception:
        docs = list(
            firestore_db
            .collection(FIRESTORE_COLLECTION)
            .limit(safe_limit)
            .stream()
        )

    if not docs:
        return "📭 No hay contactos guardados todavía."

    lines = [f"*CONTACTOS GUARDADOS* (últimos {len(docs)})", ""]
    for idx, doc in enumerate(docs, start=1):
        data = doc.to_dict() or {}
        nombre = " ".join(str(data.get("nombre", "")).strip().split()) or "(sin nombre)"
        telefono = (data.get("telefono", {}) or {}).get("normalizado") or doc.id
        etiqueta = " ".join(str(data.get("etiqueta_cliente", "")).strip().split()) or "sin_etiqueta"
        if len(nombre) > 28:
            nombre = nombre[:28].rstrip() + "..."
        lines.append(f"{idx}. {nombre} | {telefono} | {etiqueta}")

    lines.append("")
    lines.append("0. Volver al menú admin")
    return "\n".join(lines)


def normalize_number(number: str) -> str:
    if not number:
        return ""
    return "".join(ch for ch in str(number) if ch.isdigit())


def is_admin(number: str) -> bool:
    return normalize_number(number) == normalize_number(ADMIN_NUMBER)


def saludo_por_horario() -> str:
    hora = datetime.now(ZoneInfo("America/Argentina/Mendoza")).hour

    if 5 <= hora < 12:
        return "¡Buen día!"
    elif 12 <= hora < 20:
        return "¡Buenas tardes!"
    else:
        return "¡Buenas noches!"


def normalize_legacy_greeting(greeting_text: str) -> str:
    """Limpia encabezados legados para evitar saludos duplicados o desactualizados."""
    cleaned = (greeting_text or "").replace("\r\n", "\n").strip()
    legacy_prefixes = [
        "CURSALA | Plataforma de formacion tecnica y profesional",
        "Hola Bienvenido/a a Cursala.",
    ]

    for prefix in legacy_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    return cleaned


# ============================================================
# SECCION 4 - CARGA / GUARDA DE CONFIGURACION DEL MENU
# ============================================================
def load_menu_config() -> dict:
    default_config = {
        "greeting": "Gracias por comunicarte. Soy NINA 👩‍💼, la asistente virtual de Cursala, elegi una opcion o consultame lo que quieras.\n\n¿Cómo puedo ayudarte hoy?",
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
        },
        "email_notificacion_admin": {
            "activo": True,
            "destinatario": "info@cursala.com.ar",
            "asunto": "Nuevo contacto en WhatsApp Bot - Cursala",
            "cuerpo_intro": "Se ha registrado un nuevo usuario en el bot de Cursala.",
        },
        "gemini_prompt_rules": [],
    }

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        changed = False

        for key in ["greeting", "options", "responses", "cursos", "vendedores", "email_notificacion_admin", "gemini_prompt_rules"]:
            if key not in config:
                config[key] = default_config[key]
                changed = True

        normalized_greeting = normalize_legacy_greeting(config.get("greeting", ""))
        if normalized_greeting != config.get("greeting", ""):
            config["greeting"] = normalized_greeting
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
    now = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
    config.setdefault("revision", {"version": "1.0.0"})
    current_version = str(config["revision"].get("version", "1.0.0")).strip()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current_version)
    if match:
        major, minor, patch = map(int, match.groups())
        config["revision"]["version"] = f"{major}.{minor}.{patch + 1}"
    else:
        config["revision"]["version"] = "1.0.1"
    config["revision"]["fecha"] = now.strftime("%d/%m/%Y")
    config["revision"]["hora"] = now.strftime("%H:%M:%S")
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


# ============================================================
# SECCION 5 - INICIALIZACION DE ESTADO EN MEMORIA
# ============================================================
try:
    menu_config = load_menu_config()
    print("✅ Configuración cargada correctamente")
    print(f"Claves en menu_config: {menu_config.keys()}")
    admin_sessions = {}
except Exception as e:
    print(f"⚠️ Error cargando configuración: {e}")
    menu_config = {
        "greeting": "",
        "options": {},
        "responses": {},
        "cursos": {},
        "vendedores": {},
        "gemini_prompt_rules": [],
    }
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
            "last_response_option": None,
            "gemini_history": [],
            "notificacion_admin_enviada": False,
            "user_name": "",
            "post_onboarding_command": None,
            "last_interaction_at": time.time(),
            "bsuid": None,
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
    session["post_onboarding_command"] = None


def sanitize_contact_name(raw_name: str) -> str:
    cleaned = " ".join((raw_name or "").strip().split())
    return cleaned


def get_saved_contact_name(_from_number: str, session: dict) -> str:
    session_name = sanitize_contact_name(session.get("user_name", ""))
    return session_name


def apply_contact_name_to_message(to_number: str, message: str) -> str:
    session = get_admin_session(to_number)
    user_name = sanitize_contact_name(session.get("user_name", ""))
    if not user_name:
        return message

    first_line = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    if user_name.lower() in first_line.lower():
        return message

    return f"{user_name},\n{message}"


def resume_post_onboarding_flow(from_number: str, command_text: str, session: dict) -> bool:
    deferred_command = (command_text or "").strip()
    if not deferred_command:
        return False

    saved_name = get_saved_contact_name(from_number, session)

    direct_course_action = parse_course_action_identifier(deferred_command)
    if direct_course_action is not None:
        curso_id, action = direct_course_action
        menu_trace("route_post_onboarding_course_action", from_number, command=deferred_command, curso_id=curso_id, action=action)
        handle_course_detail_action(from_number, curso_id, action)
        return True

    direct_course_selection = parse_course_selection(deferred_command)
    if direct_course_selection is not None:
        menu_trace("route_post_onboarding_course_selection", from_number, command=deferred_command, curso_id=direct_course_selection)
        session["in_course_menu"] = True
        session["in_course_detail"] = True
        session["current_course"] = direct_course_selection
        track_user_interest(from_number, menu_config["cursos"][direct_course_selection]["nombre"], "curso_seleccionado")
        enviar_detalle_curso(from_number, direct_course_selection)
        return True

    if deferred_command == "1":
        menu_trace("route_post_onboarding_main_option_courses", from_number, command=deferred_command)
        session["in_course_menu"] = True
        track_user_interest(from_number, "cursos_disponibles", "menu_opcion_1", etiqueta_cliente="interesado_cursos")
        enviar_respuesta(from_number, build_courses_menu())
        return True

    if deferred_command == "2":
        session["temp_course_data"] = {}
        session["pending_action"] = "empresa_nombre"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "capacitaciones_empresas", "menu_opcion_2", etiqueta_cliente="interesado_empresa")
        enviar_respuesta(
            from_number,
            "Excelente. Para poder asesorarte mejor, indicános el nombre de la empresa:\n\n0. Volver al menú principal"
        )
        return True

    if deferred_command == "3":
        session["temp_prof_data"] = {}
        if saved_name:
            session["temp_prof_data"]["nombre_apellido"] = saved_name
            session["pending_action"] = "pro_nacionalidad"
            prompt_profesional = (
                f"¡Excelente, {saved_name}! Ahora indicános tu *nacionalidad*:\n\n"
                "0. Volver al menú principal"
            )
        else:
            session["pending_action"] = "pro_nombre_apellido"
            prompt_profesional = (
                "¡Excelente! Vamos a registrar tu perfil para dictar capacitaciones.\n\n"
                "Indicános tu *Nombre y apellido*:\n\n"
                "0. Volver al menú principal"
            )
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "quiero_capacitar", "menu_opcion_3", etiqueta_cliente="interesado_profesional")
        enviar_respuesta(from_number, prompt_profesional)
        return True

    if deferred_command == "4":
        session["temp_asesor_data"] = {}
        session["pending_action"] = "asesor_tipo"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "hablar_con_asesor", "menu_opcion_4", etiqueta_cliente="interesado_asesoria")
        enviar_respuesta(
            from_number,
            "Para hablar con un asesor, elegí el tipo de consulta:\n\n"
            "1. EMPRESA\n"
            "2. PERSONA FÍSICA\n\n"
            "0. Volver al menú principal"
        )
        return True

    return False


# ============================================================
# SECCION 6 - NORMALIZACION DE DATOS Y FIRESTORE
# ============================================================
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


def validate_bsuid(bsuid: str) -> Optional[str]:
    """Valida y normaliza un BSUID (Business-Scoped User ID).
    
    Formato esperado: COUNTRYCODE.alphanumeric
    Ejemplo: AR.123456789abcdef o US.13491208655302741918
    
    Retorna el BSUID normalizado o None si es inválido.
    """
    if not bsuid:
        return None
    
    bsuid_clean = str(bsuid).strip()
    
    # Verificar formato básico: XX.xxxxx (donde XX es código país)
    if "." not in bsuid_clean:
        return None
    
    parts = bsuid_clean.split(".")
    if len(parts) != 2:
        return None
    
    country_code, identifier = parts
    
    # País: 2 caracteres alfabéticos (AR, US, MX, etc.)
    if not (len(country_code) == 2 and country_code.isalpha()):
        return None
    
    # Identificador: solo caracteres alfanuméricos, hasta 256 chars según Meta
    if not identifier or not all(c.isalnum() for c in identifier) or len(identifier) > 256:
        return None
    
    return f"{country_code.upper()}.{identifier}"


def normalize_interest_tag(label: str) -> str:
    base = normalize_text_for_filter(label)
    safe = "".join(ch if ch.isalnum() else "_" for ch in base)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")


def build_contact_code(number: str, interest_tag: Optional[str] = None) -> str:
    """Genera un identificador estable y facil de buscar para el contacto."""
    tag = normalize_interest_tag(interest_tag or "contacto").upper() or "CONTACTO"
    digits = normalize_number(number).zfill(16)
    return f"{tag}_{digits}"


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
    etiqueta_cliente: Optional[str] = None,
    bsuid: Optional[str] = None,
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
    
    if bsuid:
        bsuid_validated = validate_bsuid(bsuid)
        if bsuid_validated:
            payload["bsuid"] = bsuid_validated
            payload["indicadores"]["tiene_bsuid"] = True

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

            primary_tag = tags[0]
            payload["etiqueta_interes"] = primary_tag.upper()
            payload["contacto_codigo"] = build_contact_code(normalized_phone, primary_tag)

            if not etiqueta_cliente:
                etiqueta_cliente = primary_tag.upper()

    if "contacto_codigo" not in payload:
        payload["contacto_codigo"] = build_contact_code(normalized_phone)

    if extra_fields:
        payload.update(extra_fields)

    if etiqueta_cliente:
        payload["etiqueta_cliente"] = etiqueta_cliente

    try:
        firestore_db.collection(FIRESTORE_COLLECTION).document(normalized_phone).set(payload, merge=True)
    except Exception as e:
        print(f"⚠️ Error guardando perfil en Firestore: {e}")


def track_user_interest(whatsapp_number: str, interest_label: str, evento: str = "interes_detectado", etiqueta_cliente: Optional[str] = None):
    upsert_user_profile_firestore(
        whatsapp_number=whatsapp_number,
        telefono=whatsapp_number,
        intereses=[interest_label],
        evento=evento,
        etiqueta_cliente=etiqueta_cliente,
    )


# ============================================================
# SECCION 7 - CONSTRUCCION DE MENUS Y NAVEGACION
# ============================================================
def build_main_menu(include_greeting: bool = True, user_name: Optional[str] = None) -> str:
    lines = []
    # En sesiones activas ocultamos el saludo inicial para evitar re-onboarding visual.
    if include_greeting:
        greeting_text = menu_config["greeting"]
        # Preprender nombre del usuario si está disponible
        if user_name:
            greeting_text = f"{user_name},\n{greeting_text}"
        lines.extend([
            greeting_text,
            "",
        ])

    lines.append("*MENU PRINCIPAL*")
    for key in sorted(menu_config["options"].keys(), key=int):
        lines.append(f"{key}. {menu_config['options'][key]}")
    lines.append("")
    lines.append("Espero tu respuesta...")
    return "\n".join(lines)


def build_courses_menu() -> str:
    if "cursos" not in menu_config:
        return "No hay cursos disponibles en este momento. Por favor, contacta al administrador."
    menu = "📚 CATALOGO DE CURSOS\n\n"
    menu += "Elegi el programa que queres explorar:\n\n"
    for key in sorted(menu_config["cursos"].keys(), key=int):
        menu += f"{key}. {menu_config['cursos'][key]['nombre']}\n"
    menu += "\n"
    menu += "0. Volver al menu principal"
    return menu


def build_course_detail_menu(curso_id: str) -> str:
    if curso_id not in menu_config["cursos"]:
        return "Curso no encontrado."
    curso = menu_config["cursos"][curso_id]
    descripcion = curso.get("descripcion", "") or "Accede al contenido, al temario y a la orientacion comercial del programa."
    return (
        f"📘 *{curso['nombre'].upper()}*\n\n"
        f"{descripcion}\n\n"
        "*Accesos disponibles*\n"
        "1. Ver curso\n"
        "2. Ver temario\n"
        "3. Hablar con asesor de inscripcion\n"
        "0. Volver al menu principal"
    )


def normalize_menu_command(text: str) -> str:
    normalized_text = (text or "").strip()
    normalized_text = re.sub(r"[\s\.:;,\)\]]+$", "", normalized_text)
    return normalized_text


def menu_trace(event: str, from_number: str, **details) -> None:
    safe_details = {key: value for key, value in details.items() if value is not None}
    print(f"MENU_TRACE event={event} from={normalize_number(from_number)} details={safe_details}")


def course_session_snapshot(session: dict) -> dict:
    return {
        "active": session.get("active"),
        "pending_action": session.get("pending_action"),
        "in_course_menu": session.get("in_course_menu"),
        "in_course_detail": session.get("in_course_detail"),
        "current_course": session.get("current_course"),
    }


def parse_course_selection(text: str) -> Optional[str]:
    normalized_text = normalize_menu_command(text).lower()
    match = re.fullmatch(r"c\s*(\d+)", normalized_text)
    if not match:
        return None

    curso_id = match.group(1)
    if curso_id not in menu_config.get("cursos", {}):
        return None
    return curso_id


def parse_course_action_identifier(text: str) -> Optional[Tuple[str, str]]:
    normalized_text = normalize_menu_command(text).lower()
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


def build_vendor_whatsapp_url(vendedor: dict, curso_nombre: str) -> str:
    phone_digits = normalize_number(vendedor.get("telefono", ""))
    if not phone_digits:
        return ""
    prefilled = quote(f"Hola, quiero informacion para inscribirme al curso {curso_nombre}.")
    return f"https://wa.me/{phone_digits}?text={prefilled}"


def build_asesores_contacto_message(prefilled_text: str = "Hola, quiero hablar con un asesor de Cursala.") -> str:
    vendedores = menu_config.get("vendedores", {})
    if not vendedores:
        return (
            "*COMUNICATE CON NUESTROS ASESORES*\n\n"
            "No hay asesores cargados en este momento."
        )

    lines = ["*COMUNICATE CON NUESTROS ASESORES*"]
    valid_count = 0
    prefilled = quote(prefilled_text)

    for vid in sorted(vendedores.keys(), key=int):
        vendedor = vendedores.get(vid, {})
        nombre = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip() or f"Asesor {vid}"
        phone_digits = normalize_number(vendedor.get("telefono", ""))

        # Usar formato consistent con build_labeled_data_block
        asesor_data = [("Nombre", nombre)]
        if phone_digits:
            valid_count += 1
            whatsapp_link = f"https://wa.me/{phone_digits}?text={prefilled}"
            asesor_data.append(("Telefonico", whatsapp_link))
        else:
            asesor_data.append(("Telefonico", "no disponible"))
        
        lines.append("\n" + build_labeled_data_block(asesor_data))

    if valid_count == 0:
        lines.append("\nNo hay telefonos disponibles para contacto inmediato. Por favor, escribinos mas tarde.")
    else:
        lines.append("\nComunicate directamente con nuestros asesores o escribinos para mas informacion.")

    return "".join(lines).strip()


def send_course_option_single_card(
    from_number: str,
    curso_id: str,
    button_label: str,
    button_url: str,
    trace_label: str,
) -> None:
    curso = menu_config["cursos"].get(curso_id, {})
    sent_cta = enviar_curso_cta_url_boton(
        from_number,
        curso_id,
        button_label,
        button_url,
        f"📘 *{curso.get('nombre', 'Curso')}*",
    )
    if sent_cta:
        menu_trace("course_action_cta_sent", from_number, curso_id=curso_id, label=trace_label)
        return

    print(f"⚠️ CTA URL falló para {trace_label}. curso_id={curso_id}")
    sent_template = course_url_template_enabled() and enviar_detalle_curso_template_url(from_number, curso_id)
    if sent_template:
        menu_trace("course_action_template_sent", from_number, curso_id=curso_id, label=trace_label)
        return

    print(f"⚠️ Template fallback falló para {trace_label}. curso_id={curso_id}")
    enviar_respuesta(from_number, "No pude generar el botón del curso en este momento. Te vuelvo a mostrar las opciones.")
    enviar_detalle_curso(from_number, curso_id)


def handle_course_detail_action(from_number: str, curso_id: str, action: str):
    menu_trace(
        "course_action_enter",
        from_number,
        curso_id=curso_id,
        action=action,
        session=course_session_snapshot(get_admin_session(from_number)),
    )

    if action == "0":
        reset_user_flow(get_admin_session(from_number))
        menu_trace("course_action_home", from_number, curso_id=curso_id, action=action)
        enviar_respuesta(from_number, build_main_menu(include_greeting=False))
        return

    curso = menu_config["cursos"].get(curso_id, {})

    if action == "1":
        send_course_option_single_card(
            from_number,
            curso_id,
            "VER CURSO",
            curso.get("link_web", ""),
            "VER CURSO",
        )
        enviar_respuesta(
            from_number,
            "Si querés volver al menú principal, escribí 0.\n"
            "Si querés seguir en este curso, elegí 1, 2 o 3."
        )
        return

    if action == "2":
        send_course_option_single_card(
            from_number,
            curso_id,
            "VER PROGRAMA",
            curso.get("link_descarga", ""),
            "VER PROGRAMA",
        )
        enviar_respuesta(
            from_number,
            "Si querés volver al menú principal, escribí 0.\n"
            "Si querés seguir en este curso, elegí 1, 2 o 3."
        )
        return

    if action == "3":
        vendedor = choose_vendor_for_course(curso)
        asesor_url = build_vendor_whatsapp_url(vendedor, curso.get("nombre", "Curso"))
        if asesor_url:
            send_course_option_single_card(
                from_number,
                curso_id,
                "HABLAR CON ASESOR",
                asesor_url,
                "HABLAR CON ASESOR",
            )
        else:
            enviar_respuesta(
                from_number,
                "No pude generar el boton del asesor para este curso.\n\n"
                + build_asesores_contacto_message(
                    f"Hola, quiero informacion para inscribirme al curso {curso.get('nombre', 'Curso')}."
                )
            )
            enviar_respuesta(
                from_number,
                "Si queres volver al menu principal, escribi 0.\n"
                "Si queres seguir en este curso, elegi 1, 2 o 3."
            )
        return

    enviar_respuesta(from_number, "Opción inválida. Elegí VER CURSO, TEMARIO, COMPRAR o 0.")
    enviar_detalle_curso(from_number, curso_id)


def build_courses_edit_menu() -> str:
    menu = "*GESTION DE CATALOGO*\n\n"
    menu += "1. Agregar curso\n"
    menu += "2. Eliminar curso\n"
    menu += "3. Editar curso\n"
    menu += "4. Ver cursos disponibles\n"
    menu += "\n0. Volver al menu admin"
    return menu


def build_admin_menu() -> str:
    return (
        "*PANEL DE ADMINISTRACION*\n\n"
        "1. Ver menu actual\n"
        "2. Modificar saludo\n"
        "3. Editar opcion\n"
        "4. Agregar opcion\n"
        "5. Modificar respuesta\n"
        "6. Gestionar catalogo de cursos\n"
        "7. Gestionar asesores y vendedores\n"
        "8. Deshacer cambio\n"
        "9. Desactivar admin\n"
        "10. Gestionar backups\n"
        "11. Notificaciones por email\n"
        "12. Revisión\n"
        "13. Administracion de contactos\n"
        "14. Prompts de respuesta (Gemini)\n\n"
        "0. Volver al menu principal"
    )


def build_contacts_admin_menu() -> str:
    return (
        "*ADMINISTRACION DE CONTACTOS*\n\n"
        "1. Ver formato JSON esperado\n"
        "2. Ver instrucciones para importar backup\n"
        "3. Ver reglas de importacion (datos incompletos)\n\n"
        "4. Subir CSV por WhatsApp\n\n"
        "5. Ver contactos guardados\n\n"
        "0. Volver al menu admin"
    )


def build_vendor_menu() -> str:
    return (
        "*GESTIÓN DE VENDEDORES*\n\n"
        "1. Ver vendedores\n"
        "2. Agregar / Editar / Eliminar vendedor\n"
        "3. Asignar cursos a vendedor\n"
        "4. Ver asignaciones actuales\n\n"
        "0. Volver al menú admin"
    )


def parse_full_name(full_name: str) -> Tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def get_course_vendor_ids(curso: dict) -> List[str]:
    vendor_ids: List[str] = []

    listed = curso.get("vendedor_ids")
    if isinstance(listed, list):
        for vid in listed:
            if isinstance(vid, str) and vid and vid not in vendor_ids:
                vendor_ids.append(vid)

    primary = curso.get("vendedor_id")
    if isinstance(primary, str) and primary and primary not in vendor_ids:
        vendor_ids.append(primary)

    valid_vendors = menu_config.get("vendedores", {})
    return [vid for vid in vendor_ids if vid in valid_vendors]


def build_vendor_list_message() -> str:
    vendedores = menu_config.get("vendedores", {})
    if not vendedores:
        return "No hay vendedores cargados."

    lines = ["*VENDEDORES CARGADOS*", ""]
    for vid in sorted(vendedores.keys(), key=int):
        v = vendedores[vid]
        nombre = f"{v.get('nombre', '')} {v.get('apellido', '')}".strip()
        correo = " ".join(str(v.get("correo", "")).strip().split())
        telefono_raw = " ".join(str(v.get("telefono", "")).strip().split())
        # Se normaliza a minusculas para mantener formato consistente (n/a incluido).
        telefono = telefono_raw.lower() if telefono_raw else "n/a"

        lines.append(f"{vid}. *{nombre}*")
        lines.append("CORREO")
        lines.append(correo or "n/a")
        lines.append("TELÉFONO")
        lines.append(telefono)
        lines.append("")
    return "\n".join(lines)


def build_vendor_edit_fields_menu(vendor_id: str) -> str:
    vendedor = menu_config.get("vendedores", {}).get(vendor_id, {})
    nombre = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()
    return (
        f"*EDITAR VENDEDOR*\n\n"
        + build_labeled_data_block([
            ("Vendedor", f"{vendor_id}. {nombre}"),
            ("Correo actual", vendedor.get('correo', '')),
            ("Teléfono actual", vendedor.get('telefono', '')),
        ])
        + "\n\n"
        "¿Qué campo querés editar?\n"
        "1. Nombre completo\n"
        "2. Correo\n"
        "3. Telefono\n\n"
        "0. Volver"
    )


def build_vendor_courses_assignment_message() -> str:
    vendedores = menu_config.get("vendedores", {})
    cursos = menu_config.get("cursos", {})

    if not vendedores:
        return "No hay vendedores cargados."

    lines = ["*CURSOS ASIGNADOS POR VENDEDOR*", ""]
    for vid in sorted(vendedores.keys(), key=int):
        vendedor = vendedores[vid]
        nombre_vendedor = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()
        lines.append(f"{vid}. {nombre_vendedor}")

        cursos_asignados = []
        for cid in sorted(cursos.keys(), key=int):
            curso = cursos[cid]
            if vid in get_course_vendor_ids(curso):
                cursos_asignados.append(f"- {curso.get('nombre', f'Curso {cid}')}")

        if cursos_asignados:
            lines.extend(cursos_asignados)
        else:
            lines.append("- (sin cursos asignados)")
        lines.append("")

    lines.append("0. Volver")
    return "\n".join(lines)


def build_vendor_courses_toggle_message(vendor_id: str) -> str:
    vendedores = menu_config.get("vendedores", {})
    cursos = menu_config.get("cursos", {})
    vendedor = vendedores.get(vendor_id, {})
    nombre_v = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()

    lines = [f"*ASIGNAR CURSOS — {nombre_v}*", ""]
    for cid in sorted(cursos.keys(), key=int):
        curso = cursos[cid]
        assigned = vendor_id in get_course_vendor_ids(curso)
        mark = "✓" if assigned else "◦"
        lines.append(f"{cid}. [{mark}] {curso.get('nombre', f'Curso {cid}')}")
    lines.append("")
    lines.append("Ingresá el número del curso para asignar/quitar")
    lines.append("0. Volver")
    return "\n".join(lines)


def build_vendor_add_confirmation(vendor_draft: dict) -> str:
    return (
        "*REVISION DE VENDEDOR*\n\n"
        + build_labeled_data_block([
            ("Nombre completo", vendor_draft.get('full_name', '')),
            ("Correo", vendor_draft.get('correo', '')),
            ("Teléfono", vendor_draft.get('telefono', '')),
        ])
        + "\n\n"
        "1. Guardar\n"
        "2. Editar\n"
        "0. Cancelar"
    )


def choose_vendor_for_course(curso: dict) -> dict:
    vendor_ids = get_course_vendor_ids(curso)
    vendedores = menu_config.get("vendedores", {})

    if not vendor_ids and vendedores:
        vendor_ids = [sorted(vendedores.keys(), key=int)[0]]

    candidates = [vendedores.get(vid, {}) for vid in vendor_ids if vid in vendedores]
    if not candidates:
        return {}

    with_phone = [v for v in candidates if normalize_number(v.get("telefono", ""))]
    pool = with_phone or candidates
    return random.choice(pool)


def build_backup_menu() -> str:
    backups = list_backups()
    count = len(backups)
    count_str = f"({count} backup{'s' if count != 1 else ''} guardado{'s' if count != 1 else ''})"
    return (
        f"*RESPALDOS Y RECUPERACION {count_str}*\n\n"
        "1. Crear backup de configuracion actual\n"
        "2. Ver o restaurar backup\n\n"
        "0. Volver al menu admin"
    )


def build_email_admin_menu() -> str:
    cfg = menu_config.get("email_notificacion_admin", {})
    estado = "✅ Activo" if cfg.get("activo", True) else "❌ Inactivo"
    destinatario = cfg.get("destinatario", "info@cursala.com.ar")
    asunto = cfg.get("asunto", "")
    cuerpo = cfg.get("cuerpo_intro", "")
    return (
        f"*NOTIFICACIONES POR EMAIL*\n\n"
        + build_labeled_data_block([
            ("Estado", estado),
            ("Destinatario", destinatario),
            ("Asunto", asunto),
            ("Intro", f"{cuerpo[:60]}{'...' if len(cuerpo) > 60 else ''}"),
        ])
        + "\n\n"
        "1. Activar/Desactivar\n"
        "2. Cambiar destinatario\n"
        "3. Editar asunto\n"
        "4. Editar texto de introducción\n\n"
        "0. Volver al menú admin"
    )


def get_gemini_prompt_rules() -> List[str]:
    rules = menu_config.get("gemini_prompt_rules", [])
    if not isinstance(rules, list):
        return []
    cleaned: List[str] = []
    for rule in rules:
        normalized_rule = " ".join(str(rule).split()).strip()
        if normalized_rule:
            cleaned.append(normalized_rule)
    return cleaned


def build_prompt_rules_admin_menu() -> str:
    total = len(get_gemini_prompt_rules())
    return (
        "*PROMPTS DE RESPUESTA (GEMINI)*\n\n"
        f"Reglas activas: {total}\n\n"
        "1. Ver reglas activas\n"
        "2. Agregar regla\n"
        "3. Editar regla\n"
        "4. Eliminar regla\n\n"
        "0. Volver al menú admin"
    )


def build_prompt_rules_list_message() -> str:
    rules = get_gemini_prompt_rules()
    if not rules:
        return "No hay reglas personalizadas cargadas todavía."

    lines = ["*REGLAS ACTIVAS PARA GEMINI*", ""]
    for idx, rule in enumerate(rules, start=1):
        lines.append(f"{idx}. {rule}")
    return "\n".join(lines)


def build_prompt_rules_select_message(action_label: str) -> str:
    rules = get_gemini_prompt_rules()
    if not rules:
        return "No hay reglas cargadas para seleccionar."

    lines = [f"*{action_label.upper()} REGLA DE GEMINI*", ""]
    for idx, rule in enumerate(rules, start=1):
        snippet = rule if len(rule) <= 110 else rule[:107] + "..."
        lines.append(f"{idx}. {snippet}")
    lines.append("")
    lines.append("0. Volver")
    return "\n".join(lines)


def build_gemini_prompt_rules_block() -> str:
    rules = get_gemini_prompt_rules()
    if not rules:
        return ""

    lines = [
        "REGLAS PERSONALIZADAS DEL NEGOCIO (ALTA PRIORIDAD):",
        "- Cumplí estas reglas de forma estricta antes de responder.",
    ]
    for rule in rules:
        lines.append(f"- {rule}")
    return "\n".join(lines) + "\n\n"


# ============================================================
# SECCION 8 - VALIDACIONES DE ENTRADA Y MENSAJES DE CONFIRMACION
# ============================================================
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


def validar_solo_numeros(texto: str) -> bool:
    """Valida que el texto contenga solo números, sin límite de cantidad."""
    limpio = "".join(ch for ch in texto if ch.isdigit())
    return len(limpio) > 0


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
        "*REVISIÓN DE SOLCITUD*\n\n"
        "*Acciones disponibles*\n"
        "1. Confirmar\n"
        "2. Ver datos\n"
        "0. Volver al menu principal"
    )


def build_empresa_datos_menu(data: dict) -> str:
    return (
        "*DATOS CARGADOS*\n\n"
        + build_labeled_data_block([
            ("Empresa", data.get('empresa', '')),
            ("CUIT", data.get('cuit', '')),
            ("Provincia", data.get('provincia', '')),
            ("Correo", data.get('correo', '')),
            ("Necesidades", data.get('necesidades', '')),
        ])
        + "\n\n"
        "*Acciones disponibles*\n"
        "1. Editar\n"
        "2. Enviar\n"
        "3. Volver"
    )


def build_empresa_editar_campos_menu() -> str:
    return (
        "*EDITAR DATOS DE SOLICITUD*\n\n"
        "1. Nombre de la empresa\n"
        "2. CUIT\n"
        "3. Provincia\n"
        "4. Correo\n"
        "5. Necesidades de formación\n\n"
        "0. Volver"
    )


def build_profesional_confirmacion(data: dict) -> str:
    return (
        "*REVISION DE PERFIL DOCENTE*\n\n"
        + build_labeled_data_block([
            ("Nombre y apellido", data.get('nombre_apellido', '')),
            ("Nacionalidad", data.get('nacionalidad', '')),
            ("DNI", data.get('dni', '')),
            ("Curso a dictar", data.get('descripcion_curso', '')),
        ])
        + "\n\n"
        "*Acciones disponibles*\n"
        "C. Continuar con carga de CV\n"
        "1. Editar nombre y apellido\n"
        "2. Editar nacionalidad\n"
        "3. Editar DNI\n"
        "4. Editar descripcion del curso\n"
        "0. Volver al menu principal"
    )


def build_asesor_empresa_confirmacion(data: dict) -> str:
    return (
        "*REVISION DE CONTACTO EMPRESA*\n\n"
        + build_labeled_data_block([
            ("Empresa", data.get('empresa_nombre', '')),
            ("Correo", data.get('empresa_correo', '')),
            ("Email", data.get('empresa_email', '')),
            ("Motivo", data.get('motivo', '')),
        ])
        + "\n\n"
        "*Acciones disponibles*\n"
        "C. Confirmar y enviar\n"
        "1. Editar nombre de empresa\n"
        "2. Editar correo\n"
        "3. Editar email\n"
        "4. Editar motivo\n"
        "0. Volver al menu principal"
    )


def build_asesor_persona_confirmacion(data: dict) -> str:
    return (
        "*REVISIÓN DE CONTACTO PERSONAL*\n\n"
        + build_labeled_data_block([
            ("Nombre completo", data.get('nombre_completo', '')),
            ("DNI", data.get('dni', '')),
            ("Teléfono", data.get('telefono', '')),
            ("Correo", data.get('correo', '')),
            ("Motivo", data.get('motivo', '')),
        ])
        + "\n\n"
        "*Acciones disponibles*\n"
        "1. Confirmar y enviar\n"
        "2. Editar datos"
    )


def build_asesor_persona_edit_menu() -> str:
    return (
        "*¿Qué dato querés editar?*\n\n"
        "1. Nombre completo\n"
        "2. DNI\n"
        "3. Teléfono\n"
        "4. Correo\n"
        "5. Motivo\n\n"
        "0. Volver a la revisión"
    )


# ============================================================
# SECCION 9 - INTEGRACION CON WHATSAPP (ENVIO DE MENSAJES)
# ============================================================
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
    outbound_message = apply_contact_name_to_message(to_number, message)
    enviar_payload_whatsapp(
        destino,
        {
            "type": "text",
            "text": {"body": outbound_message}
        },
        outbound_message,
    )


def extract_url_suffix(url: str, prefixes: list[str]) -> Optional[str]:
    clean_url = (url or "").strip()
    for prefix in prefixes:
        if clean_url.startswith(prefix):
            return clean_url[len(prefix):]
    return None

def course_url_template_enabled() -> bool:
    return bool(COURSE_URL_TEMPLATE_NAME)


# ============================================================
# SECCION 10 - DETALLE DE CURSOS Y BOTONES INTERACTIVOS
# ============================================================
def enviar_curso_cta_url_boton(
    to_number: str,
    curso_id: str,
    button_label: str,
    button_url: str,
    body_text: str,
    footer_text: Optional[str] = None,
) -> bool:
    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number
    clean_url = (button_url or "").strip()
    clean_label = (button_label or "").strip()[:20]
    clean_body = (body_text or "").strip()[:1024]
    clean_footer = (footer_text or "").strip()[:60]

    if not clean_url or not clean_label or not clean_body:
        print(
            f"⚠️ CTA URL inválido. curso_id={curso_id} label={clean_label!r} has_url={bool(clean_url)} has_body={bool(clean_body)}"
        )
        return False

    payload = {
        "recipient_type": "individual",
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {"text": clean_body},
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": clean_label,
                    "url": clean_url,
                },
            },
        },
    }

    if clean_footer:
        payload["interactive"]["footer"] = {"text": clean_footer}

    sent = enviar_payload_whatsapp(destino, payload, f"cta_url:{button_label} course:{curso_id}")
    if not sent:
        print(f"⚠️ Meta rechazó CTA URL. curso_id={curso_id} label={clean_label!r}")
    return sent


def enviar_detalle_curso_cta_url(to_number: str, curso_id: str) -> bool:
    curso = menu_config["cursos"].get(curso_id)
    if not curso:
        return False

    descripcion = curso.get("descripcion", "") or "Encontrá toda la información del curso en los accesos rápidos."
    nombre = curso.get("nombre", "Curso")

    sent_view = enviar_curso_cta_url_boton(
        to_number,
        curso_id,
        "VER CURSO",
        curso.get("link_web", ""),
        f"📘 *{nombre}*\n\n{descripcion}",
        "Acceso directo al curso",
    )
    if not sent_view:
        print(f"⚠️ No se pudo enviar CTA URL VER CURSO para curso_id={curso_id}")
        return False

    sent_syllabus = enviar_curso_cta_url_boton(
        to_number,
        curso_id,
        "TEMARIO",
        curso.get("link_descarga", ""),
        f"📘 *{nombre}*\n\nAbri el programa completo desde este boton.",
        "Acceso directo al temario",
    )
    if not sent_syllabus:
        print(f"⚠️ No se pudo enviar CTA URL TEMARIO para curso_id={curso_id}")
        return False

    enviar_respuesta(to_number, "Si querés hablar con un asesor para comprar este curso, escribí 3. Para volver al inicio, escribí 0.")
    return True


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
    menu_trace("course_detail_send_enter", to_number, curso_id=curso_id)
    curso = menu_config["cursos"].get(curso_id)
    if not curso:
        enviar_respuesta(to_number, "Curso no encontrado.")
        return
    menu_trace("course_detail_send_text_menu", to_number, curso_id=curso_id)
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
    normalized_text = normalize_menu_command(text)
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


def _detectar_intereses_gemini(user_message: str, from_number: str) -> None:
    """Detecta menciones de cursos en el mensaje libre y los registra en Firestore."""
    msg_normalized = normalize_text_for_filter(user_message)
    detectados = []
    for c in menu_config.get("cursos", {}).values():
        nombre = c.get("nombre", "")
        if nombre and normalize_text_for_filter(nombre) in msg_normalized:
            detectados.append(nombre)
    if detectados:
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            telefono=from_number,
            intereses=detectados,
            evento="gemini_interes_detectado",
        )


def detect_course_interest_labels(user_message: str) -> List[str]:
    """Detecta cursos mencionados en texto libre para etiquetar el contacto."""
    normalized_msg = normalize_text_for_filter(user_message)
    labels: List[str] = []
    for curso in menu_config.get("cursos", {}).values():
        nombre = " ".join(str(curso.get("nombre", "")).strip().split())
        if not nombre:
            continue
        if normalize_text_for_filter(nombre) in normalized_msg:
            labels.append(nombre)
    return labels


def responder_con_gemini(user_text: str, from_number: str, session: dict) -> Optional[str]:
    """Genera una respuesta conversacional con Gemini para mensajes fuera del flujo deterministico."""
    if not ENABLE_GEMINI_FALLBACK or not gemini_client:
        return None

    user_message = (user_text or "").strip()
    if not user_message:
        return None

    # Registrar intereses mencionados en el mensaje
    _detectar_intereses_gemini(user_message, from_number)

    # Construir contexto del catalogo de cursos
    catalog_lines = []
    for cid, c in menu_config.get("cursos", {}).items():
        desc = (c.get("descripcion") or "").strip()
        catalog_lines.append(f"  {cid}. {c['nombre']}: {desc}")
    catalog_text = "\n".join(catalog_lines) if catalog_lines else "  (sin cursos configurados)"

    # Contexto del curso activo si el usuario esta en el detalle de uno
    curso_context = ""
    if session.get("in_course_detail") and session.get("current_course"):
        cur = menu_config.get("cursos", {}).get(session["current_course"], {})
        if cur:
            curso_context = (
                f"\nContexto: el usuario esta explorando el curso '{cur.get('nombre', '')}'. "
                f"Descripcion: {cur.get('descripcion', '')}. "
                "Podes dar informacion tecnica detallada sobre este programa y sus contenidos.\n"
            )

    # Historial de conversacion (ultimas 6 intervenciones)
    history = session.get("gemini_history", [])
    history_text = ""
    if history:
        lines = []
        for msg in history[-6:]:
            role_label = "Usuario" if msg["role"] == "user" else "Asistente"
            lines.append(f"{role_label}: {msg['text']}")
        history_text = "\nHistorial reciente de la conversacion:\n" + "\n".join(lines) + "\n"

    custom_rules_block = build_gemini_prompt_rules_block()

    prompt = (
        "Sos el asistente conversacional de Cursala, empresa argentina de formacion tecnica y profesional.\n\n"
        "TU ROL:\n"
        "- Responder con confianza y profundidad tecnica sobre los cursos y sus areas tematicas.\n"
        "- Entablar conversacion para descubrir el perfil del usuario: sector, experiencia, objetivos laborales.\n"
        "- Hacer una pregunta de seguimiento cuando necesites mas contexto para orientarlo bien.\n"
        "- Recomendar el curso mas adecuado cuando tengas suficiente informacion sobre sus necesidades.\n"
        "- Responder en espanol rioplatense, tono profesional y cercano.\n"
        "- Respuestas de hasta 5 lineas salvo que la pregunta tecnica requiera mas detalle.\n\n"
        "LIMITES:\n"
        "- Solo derivar a asesor (indicar que escriba 4) para consultas sobre PRECIOS, FECHAS o INSCRIPCION concreta.\n"
        "- No inventar datos especificos que no estes seguro. Si no sabes algo, decilo con honestidad.\n"
        "- No redirigir al menu estatico si podes responder directamente.\n\n"
        f"{custom_rules_block}"
        f"Catalogo de cursos disponibles en Cursala:\n{catalog_text}\n"
        f"{curso_context}"
        f"{history_text}"
        f"\nMensaje del usuario: {user_message}"
    )

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        answer = (getattr(response, "text", None) or "").strip()
        if not answer:
            return None

        # Actualizar historial de conversacion (maximo 12 entradas = 6 exchanges)
        history.append({"role": "user", "text": user_message[:400]})
        history.append({"role": "model", "text": answer[:400]})
        session["gemini_history"] = history[-12:]

        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            telefono=from_number,
            evento="gemini_fallback_respuesta",
            extra_fields={
                "gemini_model": GEMINI_MODEL,
                "pending_action": session.get("pending_action"),
            },
        )
        return answer
    except Exception as exc:
        print(f"Gemini fallback error: {exc}")
        return None


# ============================================================
# SECCION 11 - MOTOR DE FLUJO DEL USUARIO FINAL
# ============================================================
def _enviar_correos_formulario(
    nombre: str,
    correo_usuario: str,
    telefono: str,
    menu_origen: str,
    datos_adicionales: dict,
) -> None:
    datos_lineas = "\n".join([f"- {k}: {v}" for k, v in datos_adicionales.items()])
    datos_html = "".join([f"<li><b>{k}:</b> {v}</li>" for k, v in datos_adicionales.items()])

    if validar_correo(correo_usuario):
        ok_usuario, detalle_usuario = enviar_correo_brevo(
            to_email=correo_usuario.strip(),
            to_name=nombre or "Usuario",
            subject="Confirmación de solicitud - Cursala",
            html_content=(
                f"<p>Hola {nombre or 'Usuario'},</p>"
                f"<p>Recibimos correctamente tu solicitud de <b>{menu_origen}</b>.</p>"
                f"<p>Datos registrados:</p><ul>{datos_html}</ul>"
                "<p>Gracias por contactarte con Cursala.</p>"
            ),
            text_content=(
                f"Hola {nombre or 'Usuario'},\n\n"
                f"Recibimos correctamente tu solicitud de {menu_origen}.\n"
                f"Datos registrados:\n{datos_lineas}\n\n"
                "Gracias por contactarte con Cursala."
            ),
        )
        if ok_usuario:
            print(f"✅ Correo de confirmación enviado al usuario {correo_usuario}: {detalle_usuario}")
        else:
            print(f"⚠️ Error enviando correo al usuario {correo_usuario}: {detalle_usuario}")

    internos = {"info@cursala.com.ar", "info@mail.cursala.com.ar"}
    cfg_dest = menu_config.get("email_notificacion_admin", {}).get("destinatario", "").strip()
    if cfg_dest:
        internos.add(cfg_dest)

    for destinatario in sorted(internos):
        ok_admin, detalle_admin = enviar_notificacion_evento(
            tipo_evento="formulario_completado",
            telefono=normalize_number(telefono),
            nombre=nombre,
            menu_origen=menu_origen,
            destinatario=destinatario,
            asunto=f"Nuevo formulario completado: {menu_origen}",
            cuerpo_intro=f"Se completó un formulario de {menu_origen}.",
            datos_adicionales=datos_adicionales,
        )
        if ok_admin:
            print(f"✅ Correo interno enviado a {destinatario}: {detalle_admin}")
        else:
            print(f"⚠️ Error enviando correo interno a {destinatario}: {detalle_admin}")


def _disparar_notificacion_primer_contacto(
    from_number: str,
    session: dict,
    nombre: str = "",
    menu_origen: str = "registro",
    datos_adicionales: dict = None,
) -> None:
    """Envía notificación a info@cursala.com.ar cuando un usuario completa su registro.

    Usa Firestore para garantizar que la notificación se envíe solo una vez por usuario,
    incluso si el servidor se reinicia. El flag de sesión evita lecturas repetidas.
    """
    if datos_adicionales is None:
        datos_adicionales = {}

    session["notificacion_admin_enviada"] = True  # evitar llamadas múltiples en la misma sesión

    if firestore_db is None:
        return

    email_cfg = menu_config.get("email_notificacion_admin", {})
    if not email_cfg.get("activo", True):
        return

    try:
        normalized = normalize_number(from_number)
        doc_ref = firestore_db.collection(FIRESTORE_COLLECTION).document(normalized)
        doc = doc_ref.get()

        if doc.exists and doc.to_dict().get("notificacion_admin_enviada"):
            return  # ya fue notificado anteriormente

        destinatario = email_cfg.get("destinatario", "info@cursala.com.ar")
        asunto = email_cfg.get("asunto", "Nuevo contacto en WhatsApp Bot - Cursala")
        cuerpo_intro = email_cfg.get("cuerpo_intro", "Se ha registrado un nuevo usuario en el bot de Cursala.")

        ok, detalle = procesar_notificacion_registro(
            telefono=normalized,
            nombre=nombre,
            menu_origen=menu_origen,
            destinatario=destinatario,
            asunto=asunto,
            cuerpo_intro=cuerpo_intro,
            datos_adicionales=datos_adicionales,
        )

        if ok:
            print(f"✅ Notificación admin enviada a {destinatario}: {detalle}")
            doc_ref.set(
                {
                    "notificacion_admin_enviada": True,
                    "notificacion_admin_message_id": detalle,
                },
                merge=True,
            )
        else:
            print(f"⚠️ Error enviando notificación admin: {detalle}")

    except Exception as e:
        print(f"⚠️ Error en _disparar_notificacion_primer_contacto: {e}")


def manejar_usuario(from_number: str, text_body: str):
    """Procesa cada mensaje entrante del usuario no-admin.

    Este bloque concentra el flujo conversacional completo:
    - navegacion de menu principal y submenus,
    - captura/edicion de datos (empresa, profesional, asesor),
    - seleccion de cursos,
    - transiciones de estado usando session["pending_action"].
    """
    session = get_admin_session(from_number)
    now_ts = time.time()
    last_interaction_at = float(session.get("last_interaction_at", 0) or 0)
    if last_interaction_at and (now_ts - last_interaction_at) > USER_INACTIVITY_TIMEOUT_SECONDS:
        reset_user_flow(session)
        session["user_name"] = ""
        session["gemini_history"] = []
    session["last_interaction_at"] = now_ts

    text = text_body.strip()
    text_lower = text.lower()
    command_text = normalize_menu_command(text_body)
    command_lower = command_text.lower()
    menu_trace(
        "user_input",
        from_number,
        raw=text_body,
        command=command_text,
        session=course_session_snapshot(session),
    )
    upsert_user_profile_firestore(
        whatsapp_number=from_number,
        telefono=from_number,
        evento="mensaje_entrante",
        extra_fields={
            "contacto_agendado": True,
            "agendado_por": "webhook_whatsapp",
        },
    )

    detected_interests = detect_course_interest_labels(text_body)
    if detected_interests:
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            telefono=from_number,
            intereses=detected_interests,
            evento="interes_detectado_texto_libre",
        )

    empresa_actions = {
        "onboarding_nombre",
        "empresa_nombre",
        "empresa_cuit",
        "empresa_provincia",
        "empresa_correo",
        "empresa_necesidades",
        "empresa_confirmacion",
        "empresa_ver_datos",
        "empresa_edit_select",
        "empresa_edit_valor",
        "empresa_edit_confirm",
        "empresa_post_confirmacion",
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
        "asesor_persona_dni",
        "asesor_persona_telefono",
        "asesor_persona_correo",
        "asesor_persona_motivo",
        "asesor_persona_confirmacion",
        "asesor_persona_edit_menu",
        "asesor_persona_edit_nombre",
        "asesor_persona_edit_dni",
        "asesor_persona_edit_telefono",
        "asesor_persona_edit_correo",
        "asesor_persona_edit_motivo",
    }

    if command_lower in ["salir", "exit"]:
        reset_user_flow(session)
        session["user_name"] = ""
        session["gemini_history"] = []
        enviar_respuesta(
            from_number,
            "✅ Sesión finalizada.\n\n"
            "Cuando quieras volver, escribí *Hola* y te pediré tu nombre nuevamente."
        )
        return

    if command_lower in ["hola", "menu", "inicio"]:
        saved_name = get_saved_contact_name(from_number, session)
        if not saved_name:
            session["post_onboarding_command"] = None
            session["pending_action"] = "onboarding_nombre"
            enviar_respuesta(
                from_number,
                "¡Hola! Antes de comenzar, ¿me compartís tu nombre?\n\n"
                "0. Volver al menú principal"
            )
            return
        reset_user_flow(session)
        menu_trace("route_main_menu", from_number, command=command_text)
        track_user_interest(from_number, "menu_principal", "navegacion_menu")
        enviar_respuesta(from_number, build_main_menu(include_greeting=False))
        return

    if command_lower == "admin":
        if not is_admin(from_number):
            enviar_respuesta(from_number, "❌ No autorizado.")
            return
        session["awaiting_admin_password"] = True
        enviar_respuesta(from_number, "Por favor, ingresá la contraseña:")
        return

    saved_name = get_saved_contact_name(from_number, session)

    if session.get("pending_action") == "onboarding_nombre":
        if command_text == "0":
            session["pending_action"] = None
            session["post_onboarding_command"] = None
            enviar_respuesta(from_number, build_main_menu())
            return

        if not validar_texto_sin_numeros(text_body, min_len=2):
            enviar_respuesta(
                from_number,
                "⚠️ Ingresá un nombre válido (sin números).\n"
                "Ejemplo: *Juan* o *Juan Pérez*\n\n"
                "0. Volver al menú principal"
            )
            return

        user_name = sanitize_contact_name(text_body)
        session["user_name"] = user_name
        session["pending_action"] = None
        deferred_command = str(session.pop("post_onboarding_command", "") or "").strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=user_name,
            telefono=from_number,
            evento="onboarding_nombre_capturado",
            extra_fields={"nombre_contacto": user_name},
        )
        if resume_post_onboarding_flow(from_number, deferred_command, session):
            return
        enviar_respuesta(
            from_number,
            f"¡Bienvenido {user_name}! 👋\n\nGracias por comunicarte con Cursala.\n\n" + build_main_menu(user_name=user_name)
        )
        return

    if not saved_name and session.get("pending_action") is None:
        session["post_onboarding_command"] = command_text
        session["pending_action"] = "onboarding_nombre"
        saludo = saludo_por_horario()
        enviar_respuesta(
            from_number,
            f"*{saludo}* Antes de comenzar, ¿me compartís tu nombre?\n\n"
            "0. Volver al menú principal"
        )
        return

    if session.get("pending_action") in (empresa_actions | profesional_actions | asesor_actions) and command_text == "0":
        reset_user_flow(session)
        enviar_respuesta(from_number, "↩️ Volviste al menú principal.\n\n" + build_main_menu(include_greeting=False))
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
        if not validar_solo_numeros(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El CUIT ingresado no es válido. Debe contener solo números.\n"
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
        enviar_respuesta(from_number, "Por favor, describí las necesidades de formación de tu empresa:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_necesidades"
        return

    if session["pending_action"] == "empresa_necesidades":
        session["temp_course_data"]["necesidades"] = text_body
        session["pending_action"] = "empresa_confirmacion"
        enviar_respuesta(from_number, build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_confirmacion":
        if text == "1":
            data = session["temp_course_data"]
            upsert_user_profile_firestore(
                whatsapp_number=from_number,
                nombre=data.get("empresa", ""),
                telefono=from_number,
                intereses=["capacitaciones_empresas"],
                evento="empresa_confirmada",
                extra_fields={
                    "empresa": {
                        "nombre": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia_declarada": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                    }
                },
                etiqueta_cliente="lead_empresa",
            )
            resumen = (
                "✅ Gracias por la información.\n\n"
                "Hemos registrado los siguientes datos:\n\n"
                + build_labeled_data_block([
                    ("Empresa", data.get('empresa', '')),
                    ("CUIT", data.get('cuit', '')),
                    ("Provincia", data.get('provincia', '')),
                    ("Correo", data.get('correo', '')),
                    ("Necesidades de formación", data.get('necesidades', '')),
                ])
                + "\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad para brindarte la información solicitada.\n\n"
                "1. Ir al menú principal"
            )
            enviar_respuesta(from_number, resumen)

            _enviar_correos_formulario(
                nombre=data.get("empresa", ""),
                correo_usuario=data.get("correo", ""),
                telefono=from_number,
                menu_origen="Capacitaciones para empresas",
                datos_adicionales={
                    "Empresa": data.get("empresa", ""),
                    "CUIT": data.get("cuit", ""),
                    "Provincia": data.get("provincia", ""),
                    "Correo": data.get("correo", ""),
                    "Necesidades": data.get("necesidades", ""),
                },
            )

            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session,
                    nombre=data.get("empresa", ""),
                    menu_origen="Capacitación empresarial",
                    datos_adicionales={
                        "empresa": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                        "necesidades_formacion": data.get("necesidades", ""),
                    },
                )
            session["pending_action"] = "empresa_post_confirmacion"
        elif text == "2":
            session["pending_action"] = "empresa_ver_datos"
            enviar_respuesta(from_number, build_empresa_datos_menu(session["temp_course_data"]))
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_empresa_confirmacion(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_ver_datos":
        if text == "1":
            session["pending_action"] = "empresa_edit_select"
            enviar_respuesta(from_number, build_empresa_editar_campos_menu())
        elif text == "2":
            data = session["temp_course_data"]
            upsert_user_profile_firestore(
                whatsapp_number=from_number,
                nombre=data.get("empresa", ""),
                telefono=from_number,
                intereses=["capacitaciones_empresas"],
                evento="empresa_confirmada",
                extra_fields={
                    "empresa": {
                        "nombre": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia_declarada": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                    }
                },
                etiqueta_cliente="lead_empresa",
            )
            resumen = (
                "✅ Gracias por la información.\n\n"
                "Hemos registrado los siguientes datos:\n\n"
                + build_labeled_data_block([
                    ("Empresa", data.get('empresa', '')),
                    ("CUIT", data.get('cuit', '')),
                    ("Provincia", data.get('provincia', '')),
                    ("Correo", data.get('correo', '')),
                    ("Necesidades de formación", data.get('necesidades', '')),
                ])
                + "\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad para brindarte la información solicitada.\n\n"
                "1. Ir al menú principal"
            )
            enviar_respuesta(from_number, resumen)

            _enviar_correos_formulario(
                nombre=data.get("empresa", ""),
                correo_usuario=data.get("correo", ""),
                telefono=from_number,
                menu_origen="Capacitaciones para empresas",
                datos_adicionales={
                    "Empresa": data.get("empresa", ""),
                    "CUIT": data.get("cuit", ""),
                    "Provincia": data.get("provincia", ""),
                    "Correo": data.get("correo", ""),
                    "Necesidades": data.get("necesidades", ""),
                },
            )

            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session,
                    nombre=data.get("empresa", ""),
                    menu_origen="Capacitación empresarial",
                    datos_adicionales={
                        "empresa": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                        "necesidades_formacion": data.get("necesidades", ""),
                    },
                )
            session["pending_action"] = "empresa_post_confirmacion"
        elif text == "3":
            session["pending_action"] = "empresa_confirmacion"
            enviar_respuesta(from_number, build_empresa_confirmacion(session["temp_course_data"]))
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_empresa_datos_menu(session["temp_course_data"]))
        return

    if session["pending_action"] == "empresa_post_confirmacion":
        if text == "1":
            reset_user_flow(session)
            enviar_respuesta(from_number, build_main_menu(include_greeting=False))
        else:
            enviar_respuesta(from_number, "Seleccioná una opción válida:\n\n1. Ir al menú principal")
        return

    if session["pending_action"] == "empresa_edit_select":
        fields = {
            "1": "empresa",
            "2": "cuit",
            "3": "provincia",
            "4": "correo",
            "5": "necesidades",
        }
        labels = {
            "empresa": "Nombre de la empresa",
            "cuit": "CUIT",
            "provincia": "Provincia",
            "correo": "Correo",
            "necesidades": "Necesidades de formación",
        }
        if text == "0":
            session["pending_action"] = "empresa_ver_datos"
            enviar_respuesta(from_number, build_empresa_datos_menu(session["temp_course_data"]))
            return
        if text not in fields:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_empresa_editar_campos_menu())
            return

        field = fields[text]
        session["temp_field"] = field
        valor_actual = session["temp_course_data"].get(field, "")
        enviar_respuesta(
            from_number,
            f"Campo: {labels[field]}\n"
            f"Valor actual: {valor_actual}\n\n"
            "Ingresá el nuevo valor:\n"
            "2. Volver"
        )
        session["pending_action"] = "empresa_edit_valor"
        return

    if session["pending_action"] == "empresa_edit_valor":
        field = session.get("temp_field")
        if text == "2":
            session["pending_action"] = "empresa_edit_select"
            enviar_respuesta(from_number, build_empresa_editar_campos_menu())
            return

        nuevo_valor = text_body.strip()
        if field == "empresa" and not validar_nombre_empresa(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ El nombre de la empresa no es válido.\n\n2. Volver")
            return
        if field == "cuit" and not validar_solo_numeros(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ El CUIT debe contener solo números.\n\n2. Volver")
            return
        if field == "provincia" and not validar_provincia(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ Provincia inválida.\n\n2. Volver")
            return
        if field == "correo" and not validar_correo(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ Correo inválido.\n\n2. Volver")
            return
        if field == "necesidades" and len(nuevo_valor) < 5:
            enviar_respuesta(from_number, "⚠️ Ingresá una necesidad más detallada.\n\n2. Volver")
            return

        if field == "cuit":
            nuevo_valor = "".join(ch for ch in nuevo_valor if ch.isdigit())
        if field == "provincia":
            nuevo_valor = nuevo_valor.title()

        session["temp_course_data"]["edit_pending_value"] = nuevo_valor
        valor_actual = session["temp_course_data"].get(field, "")
        enviar_respuesta(
            from_number,
            f"Valor actual: {valor_actual}\n"
            f"Nuevo valor: {nuevo_valor}\n\n"
            "1. Aceptar cambio\n"
            "2. Volver"
        )
        session["pending_action"] = "empresa_edit_confirm"
        return

    if session["pending_action"] == "empresa_edit_confirm":
        if text == "1":
            field = session.get("temp_field")
            nuevo_valor = session["temp_course_data"].get("edit_pending_value", "")
            session["temp_course_data"][field] = nuevo_valor
            session["temp_course_data"].pop("edit_pending_value", None)
            session["pending_action"] = "empresa_ver_datos"
            enviar_respuesta(from_number, "✅ Cambio aplicado.\n\n" + build_empresa_datos_menu(session["temp_course_data"]))
        elif text == "2":
            session["temp_course_data"].pop("edit_pending_value", None)
            session["pending_action"] = "empresa_edit_select"
            enviar_respuesta(from_number, build_empresa_editar_campos_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n1. Aceptar cambio\n2. Volver")
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
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            intereses=["quiero_capacitar"],
            evento="captura_profesional_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
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
            session["pending_action"] = "pro_edit_nacionalidad"
            enviar_respuesta(from_number, "Ingresá la nueva *nacionalidad*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "pro_edit_dni"
            enviar_respuesta(from_number, "Ingresá el nuevo *DNI* (solo números):\n\n0. Volver al menú principal")
        elif text == "4":
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
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            evento="edicion_profesional_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
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
            intereses=["quiero_capacitar"],
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
            etiqueta_cliente="lead_profesional",
        )

        resumen = (
            "✅ ¡Postulación recibida!\n\n"
            "Datos registrados:\n\n"
            + build_labeled_data_block([
                ("Nombre y apellido", registro['nombre_apellido']),
                ("Profesión", registro['profesion']),
                ("Nacionalidad", registro['nacionalidad']),
                ("DNI", registro['dni']),
                ("Curso a dictar", registro['descripcion_curso']),
                ("CV", "carga confirmada"),
            ])
            + "\n\n"
            "Nuestro equipo revisará tu propuesta y te contactará a la brevedad.\n\n"
            "↩️ Volviste al menú principal.\n\n" + build_main_menu(include_greeting=False)
        )
        enviar_respuesta(from_number, resumen)
        if not session.get("notificacion_admin_enviada"):
            _disparar_notificacion_primer_contacto(
                from_number, session,
                nombre=registro.get("nombre_apellido", ""),
                menu_origen="Profesional docente",
                datos_adicionales={
                    "nombre_apellido": registro.get("nombre_apellido", ""),
                    "profesion": registro.get("profesion", ""),
                    "nacionalidad": registro.get("nacionalidad", ""),
                    "dni": registro.get("dni", ""),
                    "curso_a_dictar": registro.get("descripcion_curso", ""),
                    "cv_confirmado": "Sí" if registro.get("cv_confirmado") else "No",
                },
            )
        reset_user_flow(session)
        return

    if session["pending_action"] == "asesor_tipo":
        if text_lower in ["1", "empresa"]:
            session["temp_asesor_data"] = {"tipo": "empresa"}
            session["pending_action"] = "asesor_empresa_nombre"
            enviar_respuesta(from_number, "Indicános el *nombre de la empresa*:\n\n0. Volver al menú principal")
        elif text_lower in ["2", "persona", "persona fisica", "persona física"]:
            session["temp_asesor_data"] = {"tipo": "persona_fisica"}
            if saved_name:
                session["temp_asesor_data"]["nombre_completo"] = saved_name
                session["pending_action"] = "asesor_persona_dni"
                enviar_respuesta(
                    from_number,
                    f"Perfecto, {saved_name}. Indicános tu *DNI*:\n\n"
                    "0. Volver al menú principal"
                )
            else:
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
                intereses=["hablar_con_asesor", "asesoria_empresa"],
                evento="asesoria_empresa_confirmada",
                extra_fields={"consulta_asesor_empresa": registro},
                etiqueta_cliente="lead_asesoria_empresa",
            )
            enviar_respuesta(
                from_number,
                "✅ Consulta enviada correctamente.\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad.\n\n"
                # Mostramos todos los asesores para contacto inmediato sin depender de una sola asignacion.
                + build_asesores_contacto_message("Hola, quiero hablar con un asesor sobre capacitaciones para empresas.")
                + "\n\n"
                # Al volver no repetimos greeting: solo menu principal de sesion activa.
                "↩️ Volviste al menú principal.\n\n" + build_main_menu(include_greeting=False)
            )
            _enviar_correos_formulario(
                nombre=data.get("empresa_nombre", ""),
                correo_usuario=data.get("empresa_correo", ""),
                telefono=from_number,
                menu_origen="Formulario empresa",
                datos_adicionales={
                    "Empresa": data.get("empresa_nombre", ""),
                    "Correo": data.get("empresa_correo", ""),
                    "Email alternativo": data.get("empresa_email", ""),
                    "Motivo": data.get("motivo", ""),
                },
            )
            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session,
                    nombre=data.get("empresa_nombre", ""),
                    menu_origen="Asesoría para empresa",
                    datos_adicionales={
                        "empresa_nombre": data.get("empresa_nombre", ""),
                        "correo": data.get("empresa_correo", ""),
                        "motivo_consulta": data.get("motivo", ""),
                    },
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
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            intereses=["hablar_con_asesor", "asesoria_persona_fisica"],
            evento="asesor_persona_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
        session["pending_action"] = "asesor_persona_dni"
        enviar_respuesta(from_number, "Indicános tu *DNI*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_dni":
        if not validar_solo_numeros(text_body):
            enviar_respuesta(from_number, "⚠️ El DNI debe contener solo números.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "asesor_persona_telefono"
        enviar_respuesta(from_number, "Indicános tu *teléfono*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_telefono":
        if not validar_telefono(text_body):
            enviar_respuesta(from_number, "⚠️ El teléfono no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["telefono"] = text_body.strip()
        session["pending_action"] = "asesor_persona_correo"
        enviar_respuesta(from_number, "Indicános tu *correo*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["correo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_motivo"
        enviar_respuesta(from_number, "Indicános el *motivo* de tu consulta:\n\n0. Volver al menú principal")
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
        if text == "1":
            data = session["temp_asesor_data"]
            registro = {
                "fecha": datetime.now(ZoneInfo("America/Argentina/Mendoza")).isoformat(),
                "whatsapp": normalize_number(from_number),
                "tipo": "persona_fisica",
                "nombre_completo": data.get("nombre_completo", ""),
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
                intereses=["hablar_con_asesor", "asesoria_persona_fisica"],
                evento="asesoria_persona_confirmada",
                extra_fields={"consulta_asesor_persona": registro},
                etiqueta_cliente="lead_asesoria_persona",
            )
            enviar_respuesta(
                from_number,
                "✅ Consulta enviada correctamente.\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad.\n\n"
                # Listado visible de asesores para que el usuario pueda contactar de inmediato.
                + build_asesores_contacto_message("Hola, quiero hablar con un asesor sobre inscripciones.")
                + "\n\n"
                # Se mantiene experiencia de sesion activa: menu sin saludo inicial.
                "↩️ Volviste al menú principal.\n\n" + build_main_menu(include_greeting=False)
            )
            _enviar_correos_formulario(
                nombre=data.get("nombre_completo", ""),
                correo_usuario=data.get("correo", ""),
                telefono=from_number,
                menu_origen="Formulario persona",
                datos_adicionales={
                    "Nombre completo": data.get("nombre_completo", ""),
                    "DNI": data.get("dni", ""),
                    "Teléfono": data.get("telefono", ""),
                    "Correo": data.get("correo", ""),
                    "Motivo": data.get("motivo", ""),
                },
            )
            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session,
                    nombre=data.get("nombre_completo", ""),
                    menu_origen="Asesoría persona física",
                    datos_adicionales={
                        "nombre_completo": data.get("nombre_completo", ""),
                        "telefono": data.get("telefono", ""),
                        "dni": data.get("dni", ""),
                        "correo": data.get("correo", ""),
                        "motivo_consulta": data.get("motivo", ""),
                    },
                )
            reset_user_flow(session)
        elif text == "2":
            session["pending_action"] = "asesor_persona_edit_menu"
            enviar_respuesta(from_number, build_asesor_persona_edit_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_menu":
        if text == "1":
            session["pending_action"] = "asesor_persona_edit_nombre"
            enviar_respuesta(from_number, "Ingresá el nuevo *nombre completo*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "asesor_persona_edit_dni"
            enviar_respuesta(from_number, "Ingresá el nuevo *DNI*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "asesor_persona_edit_telefono"
            enviar_respuesta(from_number, "Ingresá el nuevo *teléfono*:\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "asesor_persona_edit_correo"
            enviar_respuesta(from_number, "Ingresá el nuevo *correo*:\n\n0. Volver al menú principal")
        elif text == "5":
            session["pending_action"] = "asesor_persona_edit_motivo"
            enviar_respuesta(from_number, "Ingresá el nuevo *motivo*:\n\n0. Volver al menú principal")
        elif text == "0":
            session["pending_action"] = "asesor_persona_confirmacion"
            enviar_respuesta(from_number, build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_asesor_persona_edit_menu())
        return

    if session["pending_action"] == "asesor_persona_edit_nombre":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(from_number, "⚠️ Nombre completo inválido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["nombre_completo"] = text_body.strip()
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            evento="edicion_asesor_persona_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.\n\n" + build_asesor_persona_confirmacion(session["temp_asesor_data"]))
        return

    if session["pending_action"] == "asesor_persona_edit_dni":
        if not validar_solo_numeros(text_body):
            enviar_respuesta(from_number, "⚠️ El DNI debe contener solo números.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
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

    direct_course_action = parse_course_action_identifier(command_text)
    if direct_course_action is not None:
        curso_id, action = direct_course_action
        menu_trace("route_direct_course_action", from_number, command=command_text, curso_id=curso_id, action=action)
        handle_course_detail_action(from_number, curso_id, action)
        return

    direct_course_selection = parse_course_selection(command_text)
    if direct_course_selection is not None:
        menu_trace("route_direct_course_selection", from_number, command=command_text, curso_id=direct_course_selection)
        session["in_course_menu"] = True
        session["in_course_detail"] = True
        session["current_course"] = direct_course_selection
        track_user_interest(from_number, menu_config["cursos"][direct_course_selection]["nombre"], "curso_seleccionado")
        enviar_detalle_curso(from_number, direct_course_selection)
        return

    if session["in_course_detail"]:
        curso_id = session["current_course"]
        selected_action = resolve_course_detail_action(text, curso_id)
        menu_trace(
            "route_in_course_detail",
            from_number,
            command=command_text,
            curso_id=curso_id,
            selected_action=selected_action,
            session=course_session_snapshot(session),
        )
        if selected_action in {"0", "1", "2", "3"}:
            handle_course_detail_action(from_number, curso_id, selected_action)
        else:
            menu_trace("route_in_course_detail_invalid", from_number, command=command_text, curso_id=curso_id)
            respuesta_ia = responder_con_gemini(text_body, from_number, session)
            if respuesta_ia:
                enviar_respuesta(from_number, respuesta_ia)
                enviar_detalle_curso(from_number, curso_id)
                return
            enviar_respuesta(from_number, "Opción inválida. Elegí VER CURSO, TEMARIO, 3 o 0.")
            enviar_detalle_curso(from_number, curso_id)
        return

    if session["in_course_menu"]:
        if command_text == "0":
            menu_trace("route_course_menu_home", from_number, command=command_text)
            session["in_course_menu"] = False
            # Retorno desde submenu: mostrar menu principal sin greeting para no reiniciar contexto.
            enviar_respuesta(from_number, build_main_menu(include_greeting=False))
        elif command_text in menu_config["cursos"] or direct_course_selection is not None:
            selected_course_id = command_text if command_text in menu_config["cursos"] else direct_course_selection
            menu_trace("route_course_menu_select", from_number, command=command_text, curso_id=selected_course_id)
            session["in_course_detail"] = True
            session["current_course"] = selected_course_id
            track_user_interest(from_number, menu_config["cursos"][selected_course_id]["nombre"], "curso_seleccionado")
            enviar_detalle_curso(from_number, selected_course_id)
        else:
            menu_trace("route_course_menu_invalid", from_number, command=command_text, available_courses=sorted(menu_config["cursos"].keys(), key=int))
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_courses_menu())
        return

    if session.get("in_response_menu"):
        if command_text == "0":
            session["in_response_menu"] = False
            session["last_response_option"] = None
            enviar_respuesta(from_number, build_main_menu(include_greeting=False))
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa: 0 para volver")
        return

    if command_text == "1":
        menu_trace("route_main_option_courses", from_number, command=command_text)
        session["in_course_menu"] = True
        track_user_interest(from_number, "cursos_disponibles", "menu_opcion_1", etiqueta_cliente="interesado_cursos")
        enviar_respuesta(from_number, build_courses_menu())
        return

    if command_text == "2":
        session["temp_course_data"] = {}
        session["pending_action"] = "empresa_nombre"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "capacitaciones_empresas", "menu_opcion_2", etiqueta_cliente="interesado_empresa")
        enviar_respuesta(
            from_number,
            "Excelente. Para poder asesorarte mejor, indicános el nombre de la empresa:\n\n0. Volver al menú principal"
        )
        return

    if command_text == "3":
        session["temp_prof_data"] = {}
        if saved_name:
            session["temp_prof_data"]["nombre_apellido"] = saved_name
            session["pending_action"] = "pro_nacionalidad"
            prompt_profesional = (
                f"¡Excelente, {saved_name}! Ahora indicános tu *nacionalidad*:\n\n"
                "0. Volver al menú principal"
            )
        else:
            session["pending_action"] = "pro_nombre_apellido"
            prompt_profesional = (
                "¡Excelente! Vamos a registrar tu perfil para dictar capacitaciones.\n\n"
                "Indicános tu *Nombre y apellido*:\n\n"
                "0. Volver al menú principal"
            )
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "quiero_capacitar", "menu_opcion_3", etiqueta_cliente="interesado_profesional")
        enviar_respuesta(from_number, prompt_profesional)
        return

    if command_text == "4":
        session["temp_asesor_data"] = {}
        session["pending_action"] = "asesor_tipo"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "hablar_con_asesor", "menu_opcion_4", etiqueta_cliente="interesado_asesoria")
        enviar_respuesta(
            from_number,
            "Para hablar con un asesor, elegí el tipo de consulta:\n\n"
            "1. EMPRESA\n"
            "2. PERSONA FÍSICA\n\n"
            "0. Volver al menú principal"
        )
        return

    if command_text in menu_config["responses"]:
        msg = menu_config["responses"][command_text] + "\n\n0. ← Volver al menú principal"
        session["in_response_menu"] = True
        session["last_response_option"] = command_text
        enviar_respuesta(from_number, msg)
        return

    respuesta_ia = responder_con_gemini(text_body, from_number, session)
    if respuesta_ia:
        enviar_respuesta(from_number, respuesta_ia)
        return

    enviar_respuesta(
        from_number,
        "No pude interpretar tu mensaje.\n\n"
        "Escribí *MENU* para ver las opciones o *4* para hablar con un asesor.\n\n"
        + build_main_menu(),
    )


# ============================================================
# SECCION 12 - MOTOR DE FLUJO ADMINISTRATIVO
# ============================================================
def manejar_admin(from_number: str, text_body: str):
    """Procesa mensajes del administrador y delega en flujo usuario cuando corresponde.

    El estado admin comparte sesion por numero y permite:
    - editar menu y respuestas,
    - gestionar cursos, vendedores y backups,
    - volver a flujo normal cuando admin no esta activo.
    """
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
            detalle = (
                f"📝 CONTENIDO ACTUAL DEL CURSO\n\n"
                f"ID: {text}\n"
                f"Nombre: {curso.get('nombre', '')}\n"
                f"Descripción: {curso.get('descripcion', '')}\n"
                f"Link web: {curso.get('link_web', '')}\n"
                f"Link descarga: {curso.get('link_descarga', '')}\n\n"
                "1. Editar\n"
                "2. Volver"
            )
            enviar_respuesta(from_number, detalle)
            session["pending_action"] = "edit_course_overview"
        else:
            enviar_respuesta(from_number, "❌ Curso no encontrado. Intenta de nuevo.\n\n" + build_courses_menu())
        return

    if session["pending_action"] == "edit_course_overview":
        if text == "1":
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            menu_edit = f"✏️ EDITAR CURSO: {curso.get('nombre', 'N/A')}\n\n"
            menu_edit += "1. Nombre\n"
            menu_edit += "2. Descripción\n"
            menu_edit += "3. Link web\n"
            menu_edit += "4. Link descarga\n"
            menu_edit += "\n0. Volver\n\nElegí qué campo querés editar:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
        elif text == "2":
            session["pending_action"] = None
            session["current_course"] = None
            session["temp_field"] = None
            session["temp_course_data"].pop("edit_pending_value", None)
            enviar_respuesta(from_number, build_courses_edit_menu())
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Escribí 1 para editar o 2 para volver.")
        return

    if session["pending_action"] == "edit_course_field":
        fields = {"1": "nombre", "2": "descripcion", "3": "link_web", "4": "link_descarga"}
        field_name = {
            "nombre": "Nombre",
            "descripcion": "Descripción",
            "link_web": "Link web",
            "link_descarga": "Link descarga",
        }
        if text == "0":
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            detalle = (
                f"📝 CONTENIDO ACTUAL DEL CURSO\n\n"
                f"ID: {curso_id}\n"
                f"Nombre: {curso.get('nombre', '')}\n"
                f"Descripción: {curso.get('descripcion', '')}\n"
                f"Link web: {curso.get('link_web', '')}\n"
                f"Link descarga: {curso.get('link_descarga', '')}\n\n"
                "1. Editar\n"
                "2. Volver"
            )
            enviar_respuesta(from_number, detalle)
            session["pending_action"] = "edit_course_overview"
        elif text in fields:
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            session["temp_field"] = fields[text]
            campo = session["temp_field"]
            valor_actual = curso.get(campo, "")
            enviar_respuesta(
                from_number,
                f"Campo: {field_name.get(campo, campo)}\n"
                f"Valor actual: {valor_actual}\n\n"
                "Ingresá el nuevo valor:"
            )
            session["pending_action"] = "awaiting_field_value"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Elegí 1, 2, 3, 4 o 0.")
        return

    if session["pending_action"] == "awaiting_field_value":
        session["temp_course_data"]["edit_pending_value"] = text_body
        curso_id = session.get("current_course")
        field = session.get("temp_field")
        field_name = {
            "nombre": "Nombre",
            "descripcion": "Descripción",
            "link_web": "Link web",
            "link_descarga": "Link descarga",
        }
        curso = menu_config["cursos"].get(curso_id, {})
        valor_actual = curso.get(field, "")

        enviar_respuesta(
            from_number,
            f"✏️ Confirmar actualización\n\n"
            f"Campo: {field_name.get(field, field)}\n"
            f"Valor actual: {valor_actual}\n"
            f"Nuevo valor: {text_body}\n\n"
            "1. Enviar\n"
            "2. Volver"
        )
        session["pending_action"] = "confirm_course_field_update"
        return

    if session["pending_action"] == "confirm_course_field_update":
        if text == "1":
            curso_id = session.get("current_course")
            field = session.get("temp_field")
            nuevo_valor = session["temp_course_data"].get("edit_pending_value", "")
            menu_config["cursos"][curso_id][field] = nuevo_valor
            save_menu_config(menu_config)
            enviar_respuesta(from_number, "✅ Campo actualizado exitosamente.\n\n" + build_courses_edit_menu())
            session["pending_action"] = None
            session["temp_field"] = None
            session["current_course"] = None
            session["temp_course_data"].pop("edit_pending_value", None)
        elif text == "2":
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            menu_edit = f"✏️ EDITAR CURSO: {curso.get('nombre', 'N/A')}\n\n"
            menu_edit += "1. Nombre\n"
            menu_edit += "2. Descripción\n"
            menu_edit += "3. Link web\n"
            menu_edit += "4. Link descarga\n"
            menu_edit += "\n0. Volver\n\nElegí qué campo querés editar:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
            session["temp_course_data"].pop("edit_pending_value", None)
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Escribí 1 para enviar o 2 para volver.")
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

        if text == "11":
            enviar_respuesta(from_number, build_email_admin_menu())
            session["pending_action"] = "email_admin_menu"
            return

        if text == "12":
            enviar_respuesta(from_number, build_runtime_revision_message())
            session["pending_action"] = "revision_info"
            return

        if text == "13":
            enviar_respuesta(from_number, build_contacts_admin_menu())
            session["pending_action"] = "contacts_admin_menu"
            return

        if text == "14":
            enviar_respuesta(from_number, build_prompt_rules_admin_menu())
            session["pending_action"] = "prompt_rules_menu"
            return

        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_admin_menu())
        return

    if session["pending_action"] == "revision_info":
        session["pending_action"] = None
        enviar_respuesta(from_number, build_admin_menu())
        return

    if session["pending_action"] == "contacts_admin_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
            return

        if text == "1":
            ejemplo = (
                "*FORMATO JSON DE BACKUP*\n\n"
                "{\n"
                "  \"origen\": \"backup_whatsapp\",\n"
                "  \"evento_default\": \"importacion_backup\",\n"
                "  \"contactos\": [\n"
                "    {\"whatsapp_number\": \"5492615031839\"},\n"
                "    {\"phone\": \"+54 9 261 238 0499\", \"nombre\": \"Maria\", \"etiqueta_cliente\": \"interesado_empresa\"},\n"
                "    {\"whatsapp_number\": \"5492615925777\", \"intereses\": [\"cursos_disponibles\"], \"extra_fields\": {\"empresa\": {\"nombre\": \"ACME\"}}}\n"
                "  ]\n"
                "}\n\n"
                "Campo obligatorio por contacto: telefono (whatsapp_number / phone / telefono / numero)."
            )
            enviar_respuesta(from_number, ejemplo + "\n\n" + build_contacts_admin_menu())
            return

        if text == "2":
            instrucciones = (
                "*IMPORTAR BACKUP A FIRESTORE*\n\n"
                "Endpoint: POST /admin/firestore/contacts/import\n"
                "Header requerido: x-admin-key\n"
                "Body: JSON con array 'contactos'\n\n"
                "PowerShell (ejemplo):\n"
                "$headers = @{\"x-admin-key\"=\"TU_ADMIN_KEY\"}\n"
                "$body = Get-Content .\\contactos_backup.json -Raw\n"
                "Invoke-RestMethod -Uri \"https://TU-SERVICIO/admin/firestore/contacts/import\" -Method Post -Headers $headers -ContentType \"application/json\" -Body $body"
            )
            enviar_respuesta(from_number, instrucciones + "\n\n" + build_contacts_admin_menu())
            return

        if text == "3":
            reglas = (
                "*REGLAS DE IMPORTACION*\n\n"
                "1) Si no hay telefono valido, se omite el contacto.\n"
                "2) Si hay telefono, se guarda aunque falten otros datos.\n"
                "3) Se deduplica por telefono normalizado dentro del mismo JSON.\n"
                "4) Si el telefono ya existe en Firestore, se ignora (no se sobreescribe).\n"
                "5) Campos opcionales: nombre, etiqueta_cliente, intereses, extra_fields, ultimo_evento."
            )
            enviar_respuesta(from_number, reglas + "\n\n" + build_contacts_admin_menu())
            return

        if text == "4":
            session["pending_action"] = "contacts_admin_waiting_csv"
            enviar_respuesta(
                from_number,
                "📎 Enviá ahora el archivo CSV como *documento* por este chat.\n\n"
                "Columnas sugeridas: whatsapp_number|phone|telefono|numero, nombre, etiqueta_cliente, intereses.\n"
                "Para cancelar escribí 0."
            )
            return

        if text == "5":
            enviar_respuesta(from_number, build_contacts_saved_list_message(limit=20) + "\n\n" + build_contacts_admin_menu())
            return

        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_contacts_admin_menu())
        return

    if session["pending_action"] == "contacts_admin_waiting_csv":
        if text == "0":
            session["pending_action"] = "contacts_admin_menu"
            enviar_respuesta(from_number, build_contacts_admin_menu())
            return
        enviar_respuesta(from_number, "📎 Esperando archivo CSV como documento. Si querés cancelar, escribí 0.")
        return

    if session["pending_action"] == "prompt_rules_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
            return

        if text == "1":
            enviar_respuesta(from_number, build_prompt_rules_list_message() + "\n\n" + build_prompt_rules_admin_menu())
            return

        if text == "2":
            enviar_respuesta(
                from_number,
                "Escribí la nueva regla para Gemini.\n"
                "Ejemplo: Si consultan por precio, informar que hay 3 cuotas sin interes.\n\n"
                "0. Volver"
            )
            session["pending_action"] = "prompt_rules_add"
            return

        if text == "3":
            if not get_gemini_prompt_rules():
                enviar_respuesta(from_number, "No hay reglas para editar.\n\n" + build_prompt_rules_admin_menu())
                return
            enviar_respuesta(from_number, build_prompt_rules_select_message("Editar"))
            session["pending_action"] = "prompt_rules_edit_select"
            return

        if text == "4":
            if not get_gemini_prompt_rules():
                enviar_respuesta(from_number, "No hay reglas para eliminar.\n\n" + build_prompt_rules_admin_menu())
                return
            enviar_respuesta(from_number, build_prompt_rules_select_message("Eliminar"))
            session["pending_action"] = "prompt_rules_delete_select"
            return

        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_prompt_rules_admin_menu())
        return

    if session["pending_action"] == "prompt_rules_add":
        if text == "0":
            session["pending_action"] = "prompt_rules_menu"
            enviar_respuesta(from_number, build_prompt_rules_admin_menu())
            return

        new_rule = " ".join(text_body.split()).strip()
        if not new_rule:
            enviar_respuesta(from_number, "⚠️ La regla no puede estar vacía. Ingresala nuevamente:\n\n0. Volver")
            return

        rules = get_gemini_prompt_rules()
        rules.append(new_rule)
        menu_config["gemini_prompt_rules"] = rules
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(f"Regla Gemini agregada: {new_rule[:80]}")
        session["pending_action"] = "prompt_rules_menu"
        enviar_respuesta(from_number, "✅ Regla agregada correctamente.\n\n" + build_prompt_rules_admin_menu())
        return

    if session["pending_action"] == "prompt_rules_edit_select":
        if text == "0":
            session["pending_action"] = "prompt_rules_menu"
            session["temp_option"] = None
            enviar_respuesta(from_number, build_prompt_rules_admin_menu())
            return

        rules = get_gemini_prompt_rules()
        if not text.isdigit() or int(text) < 1 or int(text) > len(rules):
            enviar_respuesta(from_number, "❌ Número inválido.\n\n" + build_prompt_rules_select_message("Editar"))
            return

        index = int(text) - 1
        session["temp_option"] = str(index)
        enviar_respuesta(
            from_number,
            f"Regla actual:\n{rules[index]}\n\n"
            "Escribí la nueva versión de la regla:\n\n"
            "0. Volver"
        )
        session["pending_action"] = "prompt_rules_edit_value"
        return

    if session["pending_action"] == "prompt_rules_edit_value":
        if text == "0":
            session["pending_action"] = "prompt_rules_edit_select"
            session["temp_option"] = None
            enviar_respuesta(from_number, build_prompt_rules_select_message("Editar"))
            return

        index_raw = session.get("temp_option")
        if index_raw is None or not str(index_raw).isdigit():
            session["pending_action"] = "prompt_rules_menu"
            enviar_respuesta(from_number, "⚠️ No pude identificar la regla a editar.\n\n" + build_prompt_rules_admin_menu())
            return

        rules = get_gemini_prompt_rules()
        index = int(str(index_raw))
        if index < 0 or index >= len(rules):
            session["pending_action"] = "prompt_rules_menu"
            session["temp_option"] = None
            enviar_respuesta(from_number, "⚠️ La regla seleccionada ya no existe.\n\n" + build_prompt_rules_admin_menu())
            return

        updated_rule = " ".join(text_body.split()).strip()
        if not updated_rule:
            enviar_respuesta(from_number, "⚠️ La regla no puede estar vacía. Ingresala nuevamente:\n\n0. Volver")
            return

        previous_rule = rules[index]
        rules[index] = updated_rule
        menu_config["gemini_prompt_rules"] = rules
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(
            f"Regla Gemini editada: '{previous_rule[:60]}' -> '{updated_rule[:60]}'"
        )
        session["pending_action"] = "prompt_rules_menu"
        session["temp_option"] = None
        enviar_respuesta(from_number, "✅ Regla actualizada correctamente.\n\n" + build_prompt_rules_admin_menu())
        return

    if session["pending_action"] == "prompt_rules_delete_select":
        if text == "0":
            session["pending_action"] = "prompt_rules_menu"
            enviar_respuesta(from_number, build_prompt_rules_admin_menu())
            return

        rules = get_gemini_prompt_rules()
        if not text.isdigit() or int(text) < 1 or int(text) > len(rules):
            enviar_respuesta(from_number, "❌ Número inválido.\n\n" + build_prompt_rules_select_message("Eliminar"))
            return

        index = int(text) - 1
        removed_rule = rules.pop(index)
        menu_config["gemini_prompt_rules"] = rules
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(f"Regla Gemini eliminada: {removed_rule[:80]}")
        session["pending_action"] = "prompt_rules_menu"
        enviar_respuesta(from_number, "✅ Regla eliminada correctamente.\n\n" + build_prompt_rules_admin_menu())
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
            return

        if text == "1":
            enviar_respuesta(from_number, build_vendor_list_message() + "\n\n0. Volver")
            session["pending_action"] = "vendor_view_list"
            return

        if text == "2":
            enviar_respuesta(
                from_number,
                "¿Qué deseas hacer?\n\n"
                "1. Agregar vendedor\n"
                "2. Eliminar vendedor\n"
                "3. Editar vendedor\n\n"
                "0. Volver"
            )
            session["pending_action"] = "vendor_add_remove_menu"
            return

        if text == "3":
            vendedores = menu_config.get("vendedores", {})
            if not vendedores:
                enviar_respuesta(from_number, "⚠️ No hay vendedores cargados.\n\n" + build_vendor_menu())
                return
            enviar_respuesta(
                from_number,
                "Seleccioná el vendedor al que querés asignar cursos:\n\n"
                + build_vendor_list_message()
                + "\n\n0. Volver"
            )
            session["pending_action"] = "vendor_assign_select_vendor"
            return

        if text == "4":
            enviar_respuesta(from_number, build_vendor_courses_assignment_message())
            session["pending_action"] = "vendor_view_courses"
            return

        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_menu())
        return

    if session["pending_action"] == "vendor_view_list":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_list_message() + "\n\n0. Volver")
        return

    if session["pending_action"] == "vendor_add_remove_menu":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session.pop("temp_edit_vendor_id", None)
            enviar_respuesta(from_number, build_vendor_menu())
            return

        if text == "1":
            session.setdefault("temp_course_data", {})["vendor_draft"] = {}
            enviar_respuesta(from_number, "Ingresá *nombre completo* del vendedor:\n\n0. Volver")
            session["pending_action"] = "vendor_add_full_name"
            return

        if text == "2":
            vendedores = menu_config.get("vendedores", {})
            if not vendedores:
                enviar_respuesta(from_number, "⚠️ No hay vendedores para eliminar.\n\n" + build_vendor_menu())
                session["pending_action"] = "vendor_menu"
                return
            enviar_respuesta(
                from_number,
                "Seleccioná el número del vendedor a eliminar:\n\n"
                + build_vendor_list_message()
                + "\n\n0. Volver"
            )
            session["pending_action"] = "vendor_delete_select"
            return

        if text == "3":
            vendedores = menu_config.get("vendedores", {})
            if not vendedores:
                enviar_respuesta(from_number, "⚠️ No hay vendedores para editar.\n\n" + build_vendor_menu())
                session["pending_action"] = "vendor_menu"
                return
            enviar_respuesta(
                from_number,
                "Seleccioná el número del vendedor a editar:\n\n"
                + build_vendor_list_message()
                + "\n\n0. Volver"
            )
            session["pending_action"] = "vendor_edit_select"
            return

        enviar_respuesta(
            from_number,
            "❌ Opción inválida.\n\n"
            "¿Qué deseas hacer?\n\n"
            "1. Agregar vendedor\n"
            "2. Eliminar vendedor\n"
            "3. Editar vendedor\n\n"
            "0. Volver"
        )
        return

    if session["pending_action"] == "vendor_edit_select":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            session.pop("temp_edit_vendor_id", None)
            enviar_respuesta(from_number, "¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return

        vendedores = menu_config.get("vendedores", {})
        if text not in vendedores:
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.\n\n" + build_vendor_list_message() + "\n\n0. Volver")
            return

        session["temp_edit_vendor_id"] = text
        session["pending_action"] = "vendor_edit_field"
        enviar_respuesta(from_number, build_vendor_edit_fields_menu(text))
        return

    if session["pending_action"] == "vendor_edit_field":
        if text == "0":
            session["pending_action"] = "vendor_edit_select"
            session.pop("temp_field", None)
            enviar_respuesta(
                from_number,
                "Seleccioná el número del vendedor a editar:\n\n"
                + build_vendor_list_message()
                + "\n\n0. Volver"
            )
            return

        fields = {"1": "nombre_completo", "2": "correo", "3": "telefono"}
        if text not in fields:
            vendor_id = session.get("temp_edit_vendor_id", "")
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_edit_fields_menu(vendor_id))
            return

        session["temp_field"] = fields[text]
        prompts = {
            "nombre_completo": "Ingresá el nuevo *nombre completo*:\n\n0. Volver",
            "correo": "Ingresá el nuevo *correo*:\n\n0. Volver",
            "telefono": "Ingresá el nuevo *telefono*:\n\n0. Volver",
        }
        session["pending_action"] = "vendor_edit_value"
        enviar_respuesta(from_number, prompts[fields[text]])
        return

    if session["pending_action"] == "vendor_edit_value":
        if text == "0":
            session["pending_action"] = "vendor_edit_field"
            vendor_id = session.get("temp_edit_vendor_id", "")
            session.pop("temp_field", None)
            enviar_respuesta(from_number, build_vendor_edit_fields_menu(vendor_id))
            return

        vendor_id = session.get("temp_edit_vendor_id", "")
        vendedores = menu_config.get("vendedores", {})
        vendedor = vendedores.get(vendor_id)
        if not vendedor:
            session["pending_action"] = "vendor_add_remove_menu"
            session.pop("temp_edit_vendor_id", None)
            session.pop("temp_field", None)
            enviar_respuesta(from_number, "⚠️ El vendedor ya no existe.\n\n¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return

        field = session.get("temp_field")
        value = text_body.strip()

        if field == "correo" and not validar_correo(value):
            enviar_respuesta(from_number, "⚠️ El correo no es válido. Ingresalo nuevamente:\n\n0. Volver")
            return
        if field == "telefono" and not validar_telefono(value):
            enviar_respuesta(from_number, "⚠️ El teléfono no es válido. Ingresalo nuevamente:\n\n0. Volver")
            return
        if field == "nombre_completo":
            nombre, apellido = parse_full_name(value)
            if not nombre:
                enviar_respuesta(from_number, "⚠️ Nombre inválido. Ingresalo nuevamente:\n\n0. Volver")
                return
            before = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()
            vendedor["nombre"] = nombre
            vendedor["apellido"] = apellido
            after = f"{nombre} {apellido}".strip()
        elif field == "correo":
            before = vendedor.get("correo", "")
            vendedor["correo"] = value
            after = value
        else:
            before = vendedor.get("telefono", "")
            vendedor["telefono"] = value
            after = value

        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(
            f"Vendedor {vendor_id} editado ({field}): '{before}' → '{after}'"
        )
        session["pending_action"] = "vendor_edit_field"
        session.pop("temp_field", None)
        enviar_respuesta(from_number, "✅ Dato actualizado correctamente.\n\n" + build_vendor_edit_fields_menu(vendor_id))
        return

    if session["pending_action"] == "vendor_add_full_name":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            session.setdefault("temp_course_data", {}).pop("vendor_draft", None)
            enviar_respuesta(from_number, "¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return

        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        draft["full_name"] = text_body.strip()
        enviar_respuesta(from_number, "Ingresá *correo* del vendedor:\n\n0. Volver")
        session["pending_action"] = "vendor_add_correo"
        return

    if session["pending_action"] == "vendor_add_correo":
        if text == "0":
            session["pending_action"] = "vendor_add_full_name"
            enviar_respuesta(from_number, "Ingresá *nombre completo* del vendedor:\n\n0. Volver")
            return

        if not validar_correo(text_body.strip()):
            enviar_respuesta(from_number, "⚠️ El correo no es válido. Ingresalo nuevamente:\n\n0. Volver")
            return

        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        draft["correo"] = text_body.strip()
        enviar_respuesta(from_number, "Ingresá *telefono* del vendedor:\n\n0. Volver")
        session["pending_action"] = "vendor_add_telefono"
        return

    if session["pending_action"] == "vendor_add_telefono":
        if text == "0":
            session["pending_action"] = "vendor_add_correo"
            enviar_respuesta(from_number, "Ingresá *correo* del vendedor:\n\n0. Volver")
            return

        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        draft["telefono"] = text_body.strip()
        enviar_respuesta(from_number, build_vendor_add_confirmation(draft))
        session["pending_action"] = "vendor_add_confirm"
        return

    if session["pending_action"] == "vendor_add_confirm":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            session.setdefault("temp_course_data", {}).pop("vendor_draft", None)
            enviar_respuesta(from_number, "Carga cancelada.\n\n¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return

        if text == "2":
            enviar_respuesta(
                from_number,
                "¿Qué campo querés editar?\n\n"
                "1. Nombre completo\n"
                "2. Correo\n"
                "3. Telefono\n\n"
                "0. Volver"
            )
            session["pending_action"] = "vendor_add_edit_field"
            return

        if text == "1":
            draft = session.setdefault("temp_course_data", {}).get("vendor_draft", {})
            full_name = draft.get("full_name", "")
            nombre, apellido = parse_full_name(full_name)
            max_id = max([int(k) for k in menu_config["vendedores"].keys()]) if menu_config["vendedores"] else 0
            nuevo_id = str(max_id + 1)
            menu_config["vendedores"][nuevo_id] = {
                "nombre": nombre,
                "apellido": apellido,
                "telefono": draft.get("telefono", ""),
                "correo": draft.get("correo", ""),
            }
            save_menu_config(menu_config)
            session.setdefault("change_history", []).append(f"Vendedor agregado: {full_name}")
            session.setdefault("temp_course_data", {}).pop("vendor_draft", None)
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, "✅ Vendedor guardado correctamente.\n\n" + build_vendor_menu())
            return

        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_add_confirmation(session.setdefault("temp_course_data", {}).get("vendor_draft", {})))
        return

    if session["pending_action"] == "vendor_add_edit_field":
        if text == "0":
            draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
            session["pending_action"] = "vendor_add_confirm"
            enviar_respuesta(from_number, build_vendor_add_confirmation(draft))
            return

        fields = {"1": "full_name", "2": "correo", "3": "telefono"}
        if text not in fields:
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n1. Nombre completo\n2. Correo\n3. Telefono\n\n0. Volver")
            return

        session["temp_field"] = fields[text]
        field_names = {"full_name": "nombre completo", "correo": "correo", "telefono": "telefono"}
        enviar_respuesta(from_number, f"Ingresá nuevo {field_names[fields[text]]}:\n\n0. Volver")
        session["pending_action"] = "vendor_add_edit_value"
        return

    if session["pending_action"] == "vendor_add_edit_value":
        if text == "0":
            session["pending_action"] = "vendor_add_edit_field"
            enviar_respuesta(from_number, "¿Qué campo querés editar?\n\n1. Nombre completo\n2. Correo\n3. Telefono\n\n0. Volver")
            return

        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        field = session.get("temp_field")
        if field == "correo" and not validar_correo(text_body.strip()):
            enviar_respuesta(from_number, "⚠️ El correo no es válido. Ingresalo nuevamente:\n\n0. Volver")
            return
        draft[field] = text_body.strip()
        session["temp_field"] = None
        session["pending_action"] = "vendor_add_confirm"
        enviar_respuesta(from_number, build_vendor_add_confirmation(draft))
        return

    if session["pending_action"] == "vendor_delete_select":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            enviar_respuesta(from_number, "¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return

        if text not in menu_config.get("vendedores", {}):
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.\n\n" + build_vendor_list_message() + "\n\n0. Volver")
            return

        if len(menu_config.get("vendedores", {})) <= 1:
            enviar_respuesta(from_number, "⚠️ No podés eliminar el único vendedor disponible.")
            return

        deleted_vendor = menu_config["vendedores"].pop(text)
        remaining_ids = sorted(menu_config["vendedores"].keys(), key=int)
        fallback_id = remaining_ids[0] if remaining_ids else ""

        for curso in menu_config.get("cursos", {}).values():
            current_ids = [vid for vid in get_course_vendor_ids(curso) if vid != text]
            if current_ids:
                curso["vendedor_ids"] = current_ids
                curso["vendedor_id"] = current_ids[0]
            else:
                curso["vendedor_ids"] = [fallback_id] if fallback_id else []
                curso["vendedor_id"] = fallback_id

        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(
            f"Vendedor eliminado: {deleted_vendor.get('nombre', '')} {deleted_vendor.get('apellido', '')}".strip()
        )
        session["pending_action"] = "vendor_menu"
        enviar_respuesta(from_number, "✅ Vendedor eliminado de todo el bot.\n\n" + build_vendor_menu())
        return

    if session["pending_action"] == "vendor_view_courses":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_courses_assignment_message())
        return

    if session["pending_action"] == "vendor_assign_select_vendor":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        vendedores = menu_config.get("vendedores", {})
        if text not in vendedores:
            enviar_respuesta(
                from_number,
                "❌ Vendedor no encontrado.\n\n"
                + build_vendor_list_message()
                + "\n\n0. Volver"
            )
            return
        session["temp_assign_vendor_id"] = text
        enviar_respuesta(from_number, build_vendor_courses_toggle_message(text))
        session["pending_action"] = "vendor_assign_courses_toggle"
        return

    if session["pending_action"] == "vendor_assign_courses_toggle":
        vendor_id = session.get("temp_assign_vendor_id", "")
        if text == "0":
            session.pop("temp_assign_vendor_id", None)
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        cursos = menu_config.get("cursos", {})
        if text not in cursos:
            enviar_respuesta(from_number, "❌ Curso no válido.\n\n" + build_vendor_courses_toggle_message(vendor_id))
            return
        curso = cursos[text]
        current_ids = get_course_vendor_ids(curso)
        if vendor_id in current_ids:
            new_ids = [vid for vid in current_ids if vid != vendor_id]
            if not new_ids:
                remaining = [vid for vid in menu_config.get("vendedores", {}).keys() if vid != vendor_id]
                new_ids = [remaining[0]] if remaining else []
        else:
            new_ids = current_ids + [vendor_id]
        curso["vendedor_ids"] = new_ids
        curso["vendedor_id"] = new_ids[0] if new_ids else ""
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Guardado.\n\n" + build_vendor_courses_toggle_message(vendor_id))
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

    if session["pending_action"] == "email_admin_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text == "1":
            current = menu_config.get("email_notificacion_admin", {}).get("activo", True)
            menu_config.setdefault("email_notificacion_admin", {})["activo"] = not current
            save_menu_config(menu_config)
            estado = "✅ Activado" if not current else "❌ Desactivado"
            enviar_respuesta(from_number, f"{estado}.\n\n" + build_email_admin_menu())
        elif text == "2":
            dest = menu_config.get("email_notificacion_admin", {}).get("destinatario", "")
            enviar_respuesta(
                from_number,
                f"📧 Destinatario actual: *{dest}*\n\nIngresá el nuevo email destinatario:\n\n0. Volver"
            )
            session["pending_action"] = "email_edit_destinatario"
        elif text == "3":
            asunto = menu_config.get("email_notificacion_admin", {}).get("asunto", "")
            enviar_respuesta(
                from_number,
                f"📝 Asunto actual:\n{asunto}\n\nIngresá el nuevo asunto:\n\n0. Volver"
            )
            session["pending_action"] = "email_edit_asunto"
        elif text == "4":
            cuerpo = menu_config.get("email_notificacion_admin", {}).get("cuerpo_intro", "")
            enviar_respuesta(
                from_number,
                f"📝 Texto de introducción actual:\n{cuerpo}\n\nIngresá el nuevo texto:\n\n0. Volver"
            )
            session["pending_action"] = "email_edit_cuerpo"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_email_admin_menu())
        return

    if session["pending_action"] == "email_edit_destinatario":
        if text == "0":
            session["pending_action"] = "email_admin_menu"
            enviar_respuesta(from_number, build_email_admin_menu())
            return
        if not validar_correo(text_body.strip()):
            enviar_respuesta(from_number, "⚠️ El email no es válido. Ingresá uno correcto:\n\n0. Volver")
            return
        menu_config.setdefault("email_notificacion_admin", {})["destinatario"] = text_body.strip()
        save_menu_config(menu_config)
        session["pending_action"] = "email_admin_menu"
        enviar_respuesta(from_number, "✅ Destinatario actualizado.\n\n" + build_email_admin_menu())
        return

    if session["pending_action"] == "email_edit_asunto":
        if text == "0":
            session["pending_action"] = "email_admin_menu"
            enviar_respuesta(from_number, build_email_admin_menu())
            return
        menu_config.setdefault("email_notificacion_admin", {})["asunto"] = text_body.strip()
        save_menu_config(menu_config)
        session["pending_action"] = "email_admin_menu"
        enviar_respuesta(from_number, "✅ Asunto actualizado.\n\n" + build_email_admin_menu())
        return

    if session["pending_action"] == "email_edit_cuerpo":
        if text == "0":
            session["pending_action"] = "email_admin_menu"
            enviar_respuesta(from_number, build_email_admin_menu())
            return
        menu_config.setdefault("email_notificacion_admin", {})["cuerpo_intro"] = text_body.strip()
        save_menu_config(menu_config)
        session["pending_action"] = "email_admin_menu"
        enviar_respuesta(from_number, "✅ Texto de introducción actualizado.\n\n" + build_email_admin_menu())
        return

    enviar_respuesta(from_number, "❌ Opción inválida. " + build_admin_menu())


# ============================================================
# SECCION 13 - WEBHOOK DE META WHATSAPP
# ============================================================
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
    """Punto de entrada principal para eventos de WhatsApp Cloud API.

    - Lee payload del webhook.
    - Extrae mensajes de usuario (si existen).
    - Deriva el texto a manejar_admin, que decide si va por flujo admin o usuario.
    """
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
            for msg in messages:
                from_number = msg.get("from", "")
                message_type = msg.get("type")
                # Capturar BSUID (Business-Scoped User ID) para cumplimiento Meta marzo 2026
                from_user_id = msg.get("from_user_id")

                if from_number:
                    upsert_user_profile_firestore(
                        whatsapp_number=from_number,
                        telefono=from_number,
                        evento="webhook_message_received",
                        extra_fields={
                            "contacto_agendado": True,
                            "agendado_por": "webhook_whatsapp",
                            "ultimo_tipo_mensaje": message_type or "unknown",
                        },
                        bsuid=from_user_id,
                    )
                    
                    # Guardar BSUID en sesión para futuro uso (mayo 2026 cuando APIs lo soporten)
                    if from_user_id:
                        session = get_admin_session(from_number)
                        validated_bsuid = validate_bsuid(from_user_id)
                        if validated_bsuid:
                            session["bsuid"] = validated_bsuid

                menu_trace(
                    "webhook_message_received",
                    from_number,
                    revision=APP_VERSION,
                    message_type=message_type,
                    bsuid_present=(from_user_id is not None),
                )

                text_body = extract_message_text(msg)
                if text_body is not None:
                    print(f"De {from_number}: {text_body}")
                    menu_trace("webhook_text_extracted", from_number, text=text_body)
                    manejar_admin(from_number, text_body)
                else:
                    if message_type == "document" and process_admin_csv_document_message(from_number, msg):
                        menu_trace("webhook_admin_csv_processed", from_number)
                    else:
                        print(f"Mensaje no soportado. Tipo recibido: {message_type}")
                        menu_trace("webhook_unsupported_message", from_number, message_type=message_type)

    except Exception as e:
        print(f"Error en webhook: {e}")
        import traceback
        traceback.print_exc()

    return {"status": "ok"}


# ============================================================
# SECCION 14 - ARRANQUE LOCAL (DESARROLLO)
# ============================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)