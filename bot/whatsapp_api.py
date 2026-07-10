"""bot/whatsapp_api.py — Integracion con WhatsApp Cloud API.

Provee primitivas de transporte:
- Envio de texto, listas interactivas, templates y documentos.
- Descarga/subida de media.
- Manejo de timeout y logging de errores HTTP.
"""

import httpx
from typing import List, Optional, Tuple

from bot.config import (
    logger,
    ACCESS_TOKEN,
    PHONE_NUMBER_ID,
    TEST_RECIPIENT,
    COURSE_URL_TEMPLATE_NAME,
    COURSE_URL_TEMPLATE_LANGUAGE,
    COURSE_URL_TEMPLATE_MODE,
)
from bot.utils import is_bsuid, extract_url_suffix
from bot.state_manager import apply_contact_name_to_message


# ============================================================
# ENVIO DE MENSAJES
# ============================================================

async def enviar_payload_whatsapp(destino: str, payload: dict, log_preview: str) -> bool:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.warning("[Meta] Credenciales no configuradas. Verificar ACCESS_TOKEN y PHONE_NUMBER_ID.")
        return False

    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    if is_bsuid(destino):
        full_payload = {
            "messaging_product": "whatsapp",
            "recipient": destino,
            **payload,
        }
    else:
        full_payload = {
            "messaging_product": "whatsapp",
            "to": destino,
            **payload,
        }

    logger.info("[Meta] Enviando a %s: %s", destino, log_preview[:80])

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=full_payload, timeout=15)
            if not response.is_success:
                logger.warning("[Meta] Respuesta no OK: %s - %s", response.status_code, response.text[:200])
            else:
                logger.debug("[Meta] Respuesta OK: %s", response.status_code)
            return response.is_success
    except httpx.TimeoutException:
        logger.warning("[Meta] Timeout enviando mensaje a %s", destino)
        return False
    except httpx.RequestError as e:
        logger.warning("[Meta] Error HTTP enviando mensaje: %s", e)
        return False
    except Exception as e:
        logger.error("[Meta] Error inesperado enviando mensaje: %s", e)
        return False

async def enviar_respuesta(to_number: str, message: str) -> None:
    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number
    outbound_message = apply_contact_name_to_message(to_number, message)
    await enviar_payload_whatsapp(
        destino,
        {"type": "text", "text": {"body": outbound_message}},
        outbound_message,
    )


# ============================================================
# LISTA INTERACTIVA BASE
# ============================================================

async def enviar_lista_interactiva(
    to_number: str,
    body: str,
    sections: list,
    button_text: str = "Elegí una opción",
    header: Optional[str] = None,
    footer: Optional[str] = None,
) -> bool:
    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number

    interactive: dict = {
        "type": "list",
        "body": {"text": (body or "").strip()[:1024]},
        "action": {
            "button": (button_text or "Elegí una opción")[:20],
            "sections": sections,
        },
    }

    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    payload = {
        "recipient_type": "individual",
        "type": "interactive",
        "interactive": interactive,
    }

    return enviar_payload_whatsapp(destino, payload, f"lista:{button_text}")


# ============================================================
# CTA URL / TEMPLATE DE CURSOS
# ============================================================

def course_url_template_enabled() -> bool:
    return bool(COURSE_URL_TEMPLATE_NAME)


async def enviar_curso_cta_url_boton(
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
        logger.warning(
            "[Meta] CTA URL invalido. curso_id=%s label=%r has_url=%s has_body=%s",
            curso_id, clean_label, bool(clean_url), bool(clean_body),
        )
        return False

    payload: dict = {
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

    sent = await enviar_payload_whatsapp(destino, payload, f"cta_url:{button_label} course:{curso_id}")
    if not sent:
        logger.warning("[Meta] Rechazo CTA URL. curso_id=%s label=%r", curso_id, clean_label)
    return sent


async def enviar_detalle_curso_template_url(to_number: str, curso_id: str) -> bool:
    if not COURSE_URL_TEMPLATE_NAME:
        return False

    # Importación local para romper dependencia circular con menus.py
    from bot.menus import get_unified_courses
    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number
    curso = get_unified_courses().get(curso_id)
    if not curso:
        return False

    template_payload: dict = {
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
                "https://cursala.com.ar/", "http://cursala.com.ar/",
                "https://www.cursala.com.ar/", "http://www.cursala.com.ar/",
            ],
        )
        temario_suffix = extract_url_suffix(
            curso.get("link_descarga", ""),
            [
                "https://drive.google.com/", "http://drive.google.com/",
                "https://www.drive.google.com/", "http://www.drive.google.com/",
            ],
        )

        if not web_suffix or not temario_suffix:
            return False

        template_payload["template"]["components"] = [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": curso.get("nombre", "Curso")}],
            },
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": web_suffix}],
            },
            {
                "type": "button",
                "sub_type": "url",
                "index": "1",
                "parameters": [{"type": "text", "text": temario_suffix}],
            },
        ]

    template_preview = f"template:{COURSE_URL_TEMPLATE_NAME} course:{curso_id}"
    return await enviar_payload_whatsapp(destino, template_payload, template_preview)


# ============================================================
# DESCARGA DE MEDIA DE META
# ============================================================

async def download_whatsapp_media_content(media_id: str) -> Tuple[bool, bytes, str]:
    if not ACCESS_TOKEN:
        return False, b"", "ACCESS_TOKEN no configurado"

    try:
        async with httpx.AsyncClient() as client:
            meta_resp = await client.get(
                f"https://graph.facebook.com/v23.0/{media_id}",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                timeout=30,
            )
            if meta_resp.status_code != 200:
                return False, b"", f"Error consultando media metadata: {meta_resp.status_code}"

            media_url = (meta_resp.json() or {}).get("url", "")
            if not media_url:
                return False, b"", "No se obtuvo URL de descarga"

            file_resp = await client.get(
                media_url,
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                timeout=60,
            )
            if file_resp.status_code != 200:
                return False, b"", f"Error descargando archivo: {file_resp.status_code}"

            return True, file_resp.content, "ok"
    except Exception as e:
        return False, b"", str(e)


# ============================================================
# UPLOAD DE MEDIA Y ENVÍO DE DOCUMENTOS
# ============================================================

async def upload_media_to_meta(content: bytes, filename: str, mime_type: str) -> Optional[str]:
    """Sube bytes a la Media API de Meta y retorna el media_id, o None si falla."""
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.warning("[Meta] upload_media_to_meta: credenciales no configuradas.")
        return None

    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                data={"messaging_product": "whatsapp"},
                files={"file": (filename, content, mime_type)},
                timeout=60,
            )
            if not response.is_success:
                logger.warning(
                    "[Meta] Error subiendo media: %s - %s",
                    response.status_code,
                    response.text[:200],
                )
                return None

            media_id = (response.json() or {}).get("id")
            if not media_id:
                logger.warning("[Meta] upload_media_to_meta: no se recibió media_id.")
                return None

            logger.info("[Meta] Media subido. media_id=%s filename=%s", media_id, filename)
            return media_id
    except Exception as e:
        logger.error("[Meta] upload_media_to_meta error: %s", e)
        return None


async def enviar_documento_whatsapp(
    to_number: str,
    media_id: str,
    filename: str,
    caption: str = "",
) -> bool:
    """Envía un documento ya subido (media_id) como mensaje de WhatsApp."""
    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number

    doc_payload: dict = {"id": media_id, "filename": filename}
    if caption:
        doc_payload["caption"] = caption[:1024]

    return await enviar_payload_whatsapp(
        destino,
        {"type": "document", "document": doc_payload},
        f"documento:{filename}",
    )
