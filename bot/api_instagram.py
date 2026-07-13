"""bot/api_instagram.py — Integración con Instagram (placeholder).

Este módulo existe para que `main.py` pueda importar `router` sin errores.
Reemplazar/expandir con la lógica real cuando se implemente la integración
con Instagram (webhooks, mensajería, etc.).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/instagram", tags=["instagram"])


@router.get("/health")
async def instagram_health():
    """Endpoint de salud simple para confirmar que el router está montado."""
    return {"status": "ok", "modulo": "instagram", "implementado": False}
