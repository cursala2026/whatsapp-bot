"""bot/audio_transcription.py - Transcripcion de audio de WhatsApp usando Gemini.

Este modulo convierte mensajes de voz/audio a texto para reutilizar
el mismo flujo conversacional ya existente basado en texto.
"""

from typing import Optional

from google.genai import types

from bot.config import ENABLE_GEMINI_FALLBACK, GEMINI_MODEL, gemini_client, logger


def transcribe_audio_with_gemini(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
    """Transcribe bytes de audio con Gemini y retorna texto o None si falla."""
    if not ENABLE_GEMINI_FALLBACK or not gemini_client:
        return None
    if not audio_bytes:
        return None

    safe_mime = (mime_type or "audio/ogg").strip()

    prompt = (
        "Transcribi este audio de WhatsApp en español rioplatense. "
        "Devolve solo la transcripción literal en texto plano, sin explicaciones." 
    )

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                prompt,
                types.Part.from_bytes(data=audio_bytes, mime_type=safe_mime),
            ],
        )
        text = (getattr(response, "text", "") or "").strip()
        return text or None
    except Exception as exc:
        logger.warning("Transcripcion Gemini audio error: %s", exc)
        return None
