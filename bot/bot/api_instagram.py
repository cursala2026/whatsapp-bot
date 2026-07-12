"""bot/api_instagram.py — Endpoint para integración con n8n (Instagram)."""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import os

from bot.flow_user import responder_con_gemini
from bot.state_manager import get_admin_session

router = APIRouter()

INSTAGRAM_API_KEY = os.getenv("INSTAGRAM_API_KEY", "")

class InstagramMessage(BaseModel):
    sender_id: str
    mensaje: str
    canal: str = "instagram"

@router.post("/api/instagram/reply")
async def instagram_reply(
    payload: InstagramMessage,
    x_api_key: str = Header(default=""),
):
    if INSTAGRAM_API_KEY and x_api_key != INSTAGRAM_API_KEY:
        raise HTTPException(status_code=401, detail="No autorizado")

    session = get_admin_session(payload.sender_id)
    respuesta = await responder_con_gemini(payload.mensaje, payload.sender_id, session)

    if not respuesta:
        respuesta = "¡Gracias por escribirnos! En breve te responde alguien de Cursala."

    return {"respuesta": respuesta}
