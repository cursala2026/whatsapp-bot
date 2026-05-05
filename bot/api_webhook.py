"""bot/api_webhook.py — Endpoints del webhook de WhatsApp Cloud API.

Diseno operativo:
- Responder HTTP 200 lo antes posible para evitar reintentos de Meta.
- Procesar payload en background task.
- Aplicar idempotencia por msg_id para no duplicar acciones.
"""

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from bot.config import APP_VERSION, VERIFY_TOKEN, logger
from bot.database import (
    _is_message_processed,
    _mark_message_processed,
    _run_bg,
    upsert_user_profile_firestore,
)
from bot.flow_admin import manejar_admin, process_admin_csv_document_message
from bot.menus import extract_message_text, menu_trace
from bot.state_manager import get_admin_session
from bot.utils import validate_bsuid
from bot.whatsapp_api import download_whatsapp_media_content
from bot.audio_transcription import transcribe_audio_with_gemini

router = APIRouter()


# ---------------------------------------------------------------------------
# Background processor
# ---------------------------------------------------------------------------

def _process_webhook_payload(data: dict) -> None:
    """Procesa el payload del webhook en una tarea en background.

    Incluye idempotencia por msg_id para evitar doble procesamiento en reintentos.
    """
    logger.debug("Webhook payload recibido: %s", str(data)[:300])
    logger.debug("APP_VERSION webhook: %s", APP_VERSION)

    try:
        entry = data["entry"][0]
        value = entry["changes"][0]["value"]

        messages = value.get("messages")
        statuses = value.get("statuses")

        if messages:
            logger.debug("MENSAJE ENTRANTE: %s", messages)
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
                menu_trace("webhook_text_extracted", identifier, text=text_body)
                manejar_admin(identifier, text_body)
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
                        session["recent_audio_interaction"] = False
                        manejar_admin(identifier, "No pude leer tu audio. Si querés, reenviámelo o escribime tu consulta por texto.")
                        continue

                    ok, audio_bytes, err_msg = download_whatsapp_media_content(media_id)
                    if not ok or not audio_bytes:
                        logger.warning("No se pudo descargar audio para %s: %s", identifier, err_msg)
                        menu_trace("webhook_audio_download_error", identifier, detail=err_msg)
                        session["force_conversational_audio_once"] = False
                        session["prefer_brief_style"] = False
                        session["recent_audio_interaction"] = False
                        manejar_admin(identifier, "No pude procesar tu audio en este momento. Reenviámelo o escribime tu consulta y te respondo por acá.")
                        continue

                    transcribed_text = transcribe_audio_with_gemini(audio_bytes, mime_type)
                    if not transcribed_text:
                        logger.info("No se pudo transcribir audio para %s", identifier)
                        menu_trace("webhook_audio_transcription_empty", identifier)
                        session["force_conversational_audio_once"] = False
                        session["prefer_brief_style"] = False
                        session["recent_audio_interaction"] = False
                        manejar_admin(identifier, "No pude entender el audio. Probá con otro audio más claro o escribime el mensaje por texto.")
                        continue

                    logger.info("Audio transcripto de %s: %s", identifier, transcribed_text[:100])
                    menu_trace("webhook_audio_transcribed", identifier, text=transcribed_text[:200])
                    manejar_admin(identifier, transcribed_text)
                elif message_type == "document" and process_admin_csv_document_message(identifier, msg):
                    menu_trace("webhook_admin_csv_processed", identifier)
                else:
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
