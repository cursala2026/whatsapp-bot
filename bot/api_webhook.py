"""bot/api_webhook.py — Rutas HTTP del webhook de WhatsApp Cloud API."""

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from bot.config import APP_VERSION, VERIFY_TOKEN, logger
from bot.database import (
    _is_message_processed,
    _mark_message_processed,
    upsert_user_profile_firestore,
)
from bot.flow_admin import manejar_admin, process_admin_csv_document_message
from bot.menus import extract_message_text, menu_trace
from bot.state_manager import get_admin_session
from bot.utils import validate_bsuid

router = APIRouter()


# ---------------------------------------------------------------------------
# Background processor
# ---------------------------------------------------------------------------

def _process_webhook_payload(data: dict) -> None:
    """Procesa el payload del webhook de modo síncrono en background.

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
                upsert_user_profile_firestore(
                    whatsapp_number=from_number,
                    telefono=from_number,
                    evento="webhook_message_received",
                    extra_fields={
                        "contacto_agendado": True,
                        "agendado_por": "webhook_whatsapp",
                        "ultimo_tipo_mensaje": message_type or "unknown",
                    },
                    bsuid=validated_bsuid,
                )
            elif validated_bsuid:
                upsert_user_profile_firestore(
                    whatsapp_number=validated_bsuid,
                    telefono="",
                    evento="webhook_message_received",
                    extra_fields={
                        "contacto_agendado": False,
                        "agendado_por": "webhook_whatsapp_bsuid",
                        "ultimo_tipo_mensaje": message_type or "unknown",
                    },
                    bsuid=validated_bsuid,
                )

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
                if message_type == "document" and process_admin_csv_document_message(identifier, msg):
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
