"""bot/api_webhook.py — Endpoints del webhook de WhatsApp Cloud API.

Diseno operativo:
- Cargar catálogo de cursos desde un caché en disco al iniciar.
- Responder HTTP 200 lo antes posible para evitar reintentos de Meta.
- Procesar payload en background task.
- Aplicar idempotencia por msg_id para no duplicar acciones.
"""

import httpx
import time
import json
import os
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from bot.config import APP_VERSION, VERIFY_TOKEN, logger
from bot.database import (
    _is_message_processed,
    _mark_message_processed,
    _run_bg,
    upsert_user_profile_firestore,
)
from bot.menus import extract_message_text, menu_trace
from bot.state_manager import get_admin_session
from bot.utils import validate_bsuid
from bot.whatsapp_api import download_whatsapp_media_content
from bot.audio_transcription import transcribe_audio_with_gemini # type: ignore

router = APIRouter()

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DEL CACHÉ DE CURSOS (OPCIÓN A)
# ---------------------------------------------------------------------------
CACHE_FILE_PATH = "/app/cache/courses_cache.json"

def _load_courses_from_disk() -> list:
    """Carga los cursos desde el archivo de caché en disco, si existe."""
    if not os.path.exists(CACHE_FILE_PATH):
        return []
    try:
        with open(CACHE_FILE_PATH, "r") as f:
            logger.info("Cargando catálogo de cursos desde caché en disco.")
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("No se pudo leer el caché de cursos en disco: %s", e)
        return []

def _save_courses_to_disk(courses: list) -> None:
    """Guarda la lista de cursos en un archivo JSON en disco."""
    os.makedirs(os.path.dirname(CACHE_FILE_PATH), exist_ok=True)
    with open(CACHE_FILE_PATH, "w") as f:
        json.dump(courses, f)

CACHED_COURSES = _load_courses_from_disk()
LAST_FETCH_TIME = 0
CACHE_TTL_SECONDS = 900  # 15 minutos

async def obtener_cursos_actualizados(force_refresh: bool = False) -> list:
    """Trae los cursos de la API de la web. Si pasaron menos de 15 minutos,

    devuelve lo que está guardado en la memoria RAM para máxima velocidad.
    """
    global CACHED_COURSES, LAST_FETCH_TIME
    current_time = time.time()
    
    if not force_refresh and CACHED_COURSES and (current_time - LAST_FETCH_TIME < CACHE_TTL_SECONDS):
        return CACHED_COURSES

    # Apuntamos a la ruta original que devuelve un objeto con la clave "data".
    url_api_web = "https://cursala.com.ar/api/courses/home"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            respuesta = await client.get(url_api_web)
            if respuesta.status_code == 200:
                # Extraemos la lista de cursos desde la clave "data".
                response_data = respuesta.json()
                if not isinstance(response_data, dict):
                    logger.warning("[API Web] La respuesta no es un diccionario JSON como se esperaba. Usando caché previo.")
                    # No se actualiza CACHED_COURSES para mantener la última versión válida,
                    # pero si no hay nada en caché, devolvemos una lista vacía.
                    return CACHED_COURSES if CACHED_COURSES is not None else []
                
                CACHED_COURSES = response_data.get("data", [])
                LAST_FETCH_TIME = current_time
                _save_courses_to_disk(CACHED_COURSES)
                logger.info("[API Web] Catálogo de cursos sincronizado y cacheado correctamente.")
                return CACHED_COURSES
            else:
                logger.warning("[API Web] Error %s al consultar la web. Usando caché previo.", respuesta.status_code)
    except Exception as e:
        logger.error("[API Web] No se pudo conectar con la web de Cursala: %s. Usando caché previo.", e)
        
    # Si la API falla y el caché en memoria está vacío, intentamos usar el de disco.
    if CACHED_COURSES:
        return CACHED_COURSES
    
    return _load_courses_from_disk()

def get_cached_courses() -> list:
    """Función auxiliar síncrona para que flow_admin.py o Gemini puedan

    leer los cursos de la memoria RAM instantáneamente sin usar await.
    """
    global CACHED_COURSES
    return CACHED_COURSES or []


# ---------------------------------------------------------------------------
# Background processor
# ---------------------------------------------------------------------------

async def _process_webhook_payload(data: dict) -> None:
    """Procesa el payload del webhook en una tarea en background.

    Incluye idempotencia por msg_id para evitar doble procesamiento en reintentos.
    """
    from bot.flow_admin import manejar_admin, process_admin_csv_document_message

    logger.debug("Webhook payload recibido: %s", str(data)[:300])
    logger.debug("APP_VERSION webhook: %s", APP_VERSION)

    try:
        entry = data["entry"][0]
        value = entry["changes"][0]["value"]

        messages = value.get("messages")
        statuses = value.get("statuses")

        if messages:
            logger.debug("MENSAJE ENTRANTE: %s", messages)
            # Forzamos la actualización o lectura del catálogo en caché de forma transparente
            await obtener_cursos_actualizados()
            
        if statuses:
            logger.debug("STATUS: %s", statuses)

        if not messages:
            return

        contacts_list = value.get("contacts", [])
        wa_profile_name = ""
        if contacts_list and isinstance(contacts_list[0], dict):
            profile = contacts_list[0].get("profile") or {}
            if isinstance(profile, dict):
                wa_profile_name = " ".join(str(profile.get("name", "")).strip().split())
        contacts_user_id = contacts_list[0].get("user_id") if contacts_list else None

        for msg in messages:
            from_number = msg.get("from", "") or ""
            message_type = msg.get("type")

            from_user_id = msg.get("from_user_id") or contacts_user_id
            validated_bsuid = validate_bsuid(from_user_id) if from_user_id else None

            identifier = from_number if from_number else validated_bsuid
            if not identifier:
                logger.warning("Mensaje sin identificador (sin teléfono ni BSUID). Ignorado.")
                continue

            msg_waid = msg.get("id", "")
            if msg_waid and _is_message_processed(msg_waid):
                logger.info(
                    "[idempotency] Mensaje %s ya procesado para %s. Ignorando reintento.",
                    msg_waid,
                    identifier,
                )
                continue
            if msg_waid:
                _mark_message_processed(msg_waid)

            if from_number:
                _run_bg(
                    upsert_user_profile_firestore,
                    whatsapp_number=from_number,
                    telefono=from_number,
                    evento="webhook_message_received",
                    extra_fields={
                        "contacto_agendado": False,
                        "agendado_por": "whatsapp_profile",
                        "nombre_whatsapp": wa_profile_name,
                        "ultimo_tipo_mensaje": message_type or "unknown",
                    },
                    bsuid=validated_bsuid,
                )
            elif validated_bsuid:
                logger.info("Mensaje con BSUID sin telefono. Se omite upsert de contacto para evitar numero invalido.")

            if validated_bsuid:
                session = get_admin_session(identifier)
                session["bsuid"] = validated_bsuid

            menu_trace(
                "webhook_message_received",
                identifier,
                revision=APP_VERSION,
                message_type=message_type,
                has_phone=bool(from_number),
                bsuid_present=(validated_bsuid is not None),
            )

            text_body = extract_message_text(msg)
            if text_body is not None:
                logger.info("Mensaje de %s: %s", identifier, text_body[:100])
                menu_trace("webhook_text_extracted", identifier, text=text_body) # type: ignore
                await manejar_admin(identifier, text_body)
            else:
                if message_type == "audio":
                    audio_info = msg.get("audio") or {}
                    media_id = audio_info.get("id", "")
                    mime_type = audio_info.get("mime_type", "audio/ogg")
                    session = get_admin_session(identifier)
                    session["skip_name_request_once"] = True
                    session["prefer_brief_style"] = True
                    session["force_conversational_audio_once"] = True
                    session["recent_audio_interaction"] = True

                    if not media_id:
                        logger.warning("Audio sin media_id para %s", identifier)
                        menu_trace("webhook_audio_missing_media_id", identifier)
                        session["force_conversational_audio_once"] = False
                        session["prefer_brief_style"] = False
                        session["recent_audio_interaction"] = False # type: ignore
                        await manejar_admin(identifier, "No pude leer tu audio. Si querés, reenviámelo o escribime tu consulta por texto.")
                        continue

                    ok, audio_bytes, err_msg = await download_whatsapp_media_content(media_id)
                    if not ok or not audio_bytes:
                        logger.warning("No se pudo descargar audio para %s: %s", identifier, err_msg)
                        menu_trace("webhook_audio_download_error", identifier, detail=err_msg)
                        session["force_conversational_audio_once"] = False
                        session["prefer_brief_style"] = False
                        session["recent_audio_interaction"] = False # type: ignore
                        await manejar_admin(identifier, "No pude procesar tu audio en este momento. Reenviámelo o escribime tu consulta y te respondo por acá.")
                        continue

                    transcribed_text = transcribe_audio_with_gemini(audio_bytes, mime_type)
                    if not transcribed_text:
                        logger.info("No se pudo transcribir audio para %s", identifier)
                        menu_trace("webhook_audio_transcription_empty", identifier) # type: ignore
                        session["force_conversational_audio_once"] = False
                        session["prefer_brief_style"] = False
                        session["recent_audio_interaction"] = False # type: ignore
                        await manejar_admin(identifier, "No pude entender el audio. Probá con otro audio más claro o escribime el mensaje por texto.")
                        continue

                    logger.info("Audio transcripto de %s: %s", identifier, transcribed_text[:100])
                    menu_trace("webhook_audio_transcribed", identifier, text=transcribed_text[:200])
                    manejar_admin(identifier, transcribed_text)
                elif message_type == "document" and process_admin_csv_document_message(identifier, msg):
                    menu_trace("webhook_admin_csv_processed", identifier)
                else: # type: ignore
                    logger.debug("Mensaje no soportado. Tipo: %s", message_type)
                    menu_trace("webhook_unsupported_message", identifier, message_type=message_type)

    except Exception as e:
        logger.error("Error procesando webhook: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Invalid token", status_code=403)


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibe eventos de WhatsApp y los procesa en background.

    Retorna 200 inmediatamente para que Meta no reintente por timeout cuando
    Gemini o Firestore tardan más de ~5 s en responder.
    """
    data = await request.json()
    background_tasks.add_task(_process_webhook_payload, data)
    return {"status": "ok"}


@router.get("/test/cursos")
async def test_cursos():
    """Endpoint de diagnóstico para verificar los cursos que el bot está viendo.

    Fuerza un refresco del caché y devuelve la lista de cursos.
    """
    cursos = await obtener_cursos_actualizados(force_refresh=True)
    return {"total": len(cursos), "cursos": cursos}
