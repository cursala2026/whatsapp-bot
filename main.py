"""Entrada principal de FastAPI para el bot de Cursala.

Este archivo solo monta routers y arranca uvicorn en local.
Toda la logica de negocio vive en el paquete `bot/`.
# Updated 2026-04-18
"""

import os
from fastapi import FastAPI, Request
from bot.api_admin import router as admin_router
from bot.api_webhook import router as webhook_router
from bot.config import gemini_client, GEMINI_MODEL, logger
from google.genai import types

app = FastAPI()
app.include_router(admin_router)
app.include_router(webhook_router)

# Updated error message 2026-04-18
@app.post("/api/chat-web")
async def chat_web(payload: dict):
    message = payload.get("message", "").strip()
    if not message:
        return {
            "response": "Hola, soy el asistente de Indevra. ¿En qué puedo ayudarte con diseño web?"
        }

    try:
        model = gemini_client.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            f"Eres un asistente de Indevra, especializado en diseño web minimalista. Responde de manera profesional y clara. Usuario: {message}",
            generation_config=types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=180,
            ),
        )
        return {"response": response.text.strip()}
    except Exception as e:
        logger.error(f"Error chat-web: {e}")
        return {"response": "Lo siento, hubo un error de conexión. Intenta de nuevo."}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8080')))