"""bot/audio_transcription.py - Transcripcion de audio de WhatsApp usando Gemini.

Este modulo convierte mensajes de voz/audio a texto para reutilizar
el mismo flujo conversacional ya existente basado en texto.
"""

from typing import Optional, cast

from bot.config import ENABLE_GEMINI_FALLBACK, GEMINI_MODEL, gemini_client, logger


def transcribe_audio_with_gemini(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
    """Transcribe bytes de audio con Gemini y retorna texto o None si falla.""" # type: ignore
    if not ENABLE_GEMINI_FALLBACK or not gemini_client:
        return None
    if not audio_bytes:
        return None

    safe_mime = (mime_type or "audio/ogg").strip()

    prompt = (
        "Sos un experto en transcripción de audio a texto. "
        "Tu única tarea es transcribir el siguiente audio de WhatsApp. "
        "El audio está en español, posiblemente con modismos de Argentina. "
        "Devolvé únicamente el texto literal de la transcripción, sin agregar introducciones, explicaciones, ni ningún otro texto."
    )

    try:
        response = cast(genai.GenerativeModel, gemini_client).generate_content( # type: ignore
            contents=[
                prompt,
                {"mime_type": safe_mime, "data": audio_bytes},
            ],
        )
        text = (getattr(response, "text", "") or "").strip()
        return text or None
    except Exception as exc:
        logger.warning("Transcripcion Gemini audio error: %s", exc)
        return None
