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


@app.get("/health")
async def health():
    return {"status": "ok"}




if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8080')))