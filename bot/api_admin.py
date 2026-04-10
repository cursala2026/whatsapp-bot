"""bot/api_admin.py — Rutas HTTP administrativas."""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query

from bot.config import (
    ACCESS_TOKEN,
    APP_VERSION,
    COURSE_URL_TEMPLATE_MODE,
    COURSE_URL_TEMPLATE_NAME,
    FIRESTORE_COLLECTION,
    PHONE_NUMBER_ID,
    VERIFY_TOKEN,
    logger,
    ADMIN_KEY,
)
from bot.database import firestore_db, upsert_user_profile_firestore
from bot.utils import normalize_number, normalize_interest_tag
from bot.whatsapp_api import enviar_payload_whatsapp

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_admin_key(key: Optional[str]) -> None:
    if not key or key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="No autorizado")


# ---------------------------------------------------------------------------
# GET /version
# ---------------------------------------------------------------------------

@router.get("/version")
async def app_version():
    return {
        "app_version": APP_VERSION,
        "phone_number_id": PHONE_NUMBER_ID,
        "verify_token_loaded": bool(VERIFY_TOKEN),
        "course_url_template_name": COURSE_URL_TEMPLATE_NAME,
        "course_url_template_mode": COURSE_URL_TEMPLATE_MODE,
    }


# ---------------------------------------------------------------------------
# GET /admin/firestore/users
# ---------------------------------------------------------------------------

@router.get("/admin/firestore/users")
async def admin_firestore_users(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
    provincia: Optional[str] = Query(default=None, description="Nombre o slug de provincia"),
    interes: Optional[str] = Query(default=None, description="Interes para filtrar"),
    limit: int = Query(default=50, ge=1, le=200),
):
    _check_admin_key(x_admin_key)
    if firestore_db is None:
        raise HTTPException(status_code=503, detail="Firestore no configurado")

    provincia_slug = normalize_interest_tag(provincia) if provincia else None
    interes_tag = normalize_interest_tag(interes) if interes else None

    query_ref = firestore_db.collection(FIRESTORE_COLLECTION)
    if provincia_slug:
        query_ref = query_ref.where("indicadores.provincia_slug", "==", provincia_slug)
    if interes_tag:
        query_ref = query_ref.where("intereses_tags", "array_contains", interes_tag)

    try:
        docs = query_ref.limit(limit).stream()
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            items.append({
                "id": doc.id,
                "nombre": data.get("nombre", ""),
                "telefono": data.get("telefono", {}).get("normalizado", ""),
                "provincia": data.get("provincia_por_numero", {}),
                "intereses_tags": data.get("intereses_tags", []),
                "intereses_labels": data.get("intereses_labels", []),
                "indicadores": data.get("indicadores", {}),
                "actualizado_en": str(data.get("actualizado_en", "")),
            })
        return {
            "collection": FIRESTORE_COLLECTION,
            "filters": {
                "provincia": provincia or "",
                "provincia_slug": provincia_slug or "",
                "interes": interes or "",
                "interes_tag": interes_tag or "",
                "limit": limit,
            },
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando Firestore: {e}")


# ---------------------------------------------------------------------------
# GET /admin/firestore/users/{telefono}
# ---------------------------------------------------------------------------

@router.get("/admin/firestore/users/{telefono}")
async def admin_firestore_user_by_phone(
    telefono: str,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    if firestore_db is None:
        raise HTTPException(status_code=503, detail="Firestore no configurado")

    normalized = normalize_number(telefono)
    if not normalized:
        raise HTTPException(status_code=400, detail="Telefono invalido")

    try:
        doc = firestore_db.collection(FIRESTORE_COLLECTION).document(normalized).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return {"id": doc.id, "data": doc.to_dict() or {}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando Firestore: {e}")


# ---------------------------------------------------------------------------
# POST /admin/firestore/contacts/import
# ---------------------------------------------------------------------------

def _normalize_intereses_backup(value) -> list:
    if not value:
        return []
    if isinstance(value, str):
        cleaned = " ".join(value.strip().split())
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        out = []
        for item in value:
            s = " ".join(str(item).strip().split())
            if s:
                out.append(s)
        return out
    return []


@router.post("/admin/firestore/contacts/import")
async def admin_import_contacts(
    payload: dict,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    if firestore_db is None:
        raise HTTPException(status_code=503, detail="Firestore no configurado")

    contactos = payload.get("contactos")
    if not isinstance(contactos, list):
        raise HTTPException(status_code=400, detail="'contactos' debe ser una lista")

    origen_default = " ".join(str(payload.get("origen", "backup_json")).strip().split()) or "backup_json"
    evento_default = " ".join(str(payload.get("evento_default", "importacion_backup")).strip().split()) or "importacion_backup"

    seen = set()
    imported = skipped_no_phone = skipped_dup = skipped_existing = skipped_invalid = failed = 0
    failures = []

    for idx, item in enumerate(contactos, start=1):
        if not isinstance(item, dict):
            skipped_invalid += 1
            failures.append({"index": idx, "error": "item_no_es_objeto"})
            continue

        raw_phone = (
            item.get("whatsapp_number")
            or item.get("phone")
            or item.get("telefono")
            or item.get("numero")
        )
        phone = normalize_number(raw_phone)
        if not phone:
            skipped_no_phone += 1
            failures.append({"index": idx, "error": "telefono_invalido"})
            continue
        if phone in seen:
            skipped_dup += 1
            continue
        seen.add(phone)

        try:
            doc = firestore_db.collection(FIRESTORE_COLLECTION).document(phone).get()
            if doc.exists:
                skipped_existing += 1
                continue
        except Exception as e:
            failed += 1
            failures.append({"index": idx, "telefono": phone, "error": str(e)})
            continue

        nombre = " ".join(str(item.get("nombre", "")).strip().split())
        etiqueta = " ".join(str(item.get("etiqueta_cliente", "")).strip().split())
        intereses = _normalize_intereses_backup(item.get("intereses"))
        ultimo_evento = " ".join(str(item.get("ultimo_evento", evento_default)).strip().split()) or "importacion_backup"
        extra_fields = dict(item.get("extra_fields", {})) if isinstance(item.get("extra_fields"), dict) else {}
        extra_fields["origen"] = " ".join(str(item.get("origen", "")).strip().split()) or origen_default
        extra_fields.setdefault("contacto_agendado", True)
        extra_fields.setdefault("agendado_por", "importacion_backup")

        try:
            upsert_user_profile_firestore(
                whatsapp_number=phone,
                nombre=nombre or None,
                telefono=phone,
                intereses=intereses or None,
                evento=ultimo_evento,
                extra_fields=extra_fields,
                etiqueta_cliente=etiqueta or None,
            )
            imported += 1
        except Exception as e:
            failed += 1
            failures.append({"index": idx, "telefono": phone, "error": str(e)})

    return {
        "ok": True,
        "collection": FIRESTORE_COLLECTION,
        "summary": {
            "total_recibidos": len(contactos),
            "importados": imported,
            "omitidos_sin_telefono": skipped_no_phone,
            "omitidos_duplicados": skipped_dup,
            "omitidos_ya_registrados": skipped_existing,
            "omitidos_invalidos": skipped_invalid,
            "fallidos": failed,
        },
        "failures_preview": failures[:25],
    }


# ---------------------------------------------------------------------------
# POST /admin/send-test-message
# ---------------------------------------------------------------------------

@router.post("/admin/send-test-message")
async def admin_send_test_message(
    payload: dict,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    numero = payload.get("numero", "").strip()
    mensaje = payload.get("mensaje", "").strip()
    if not numero or not mensaje:
        raise HTTPException(status_code=400, detail="Falta 'numero' o 'mensaje'")

    normalizado = normalize_number(numero)
    if not normalizado:
        raise HTTPException(status_code=400, detail=f"Número inválido: {numero}")

    destino = f"+{normalizado}" if not normalizado.startswith("+") else normalizado
    exito = enviar_payload_whatsapp(destino, {"type": "text", "text": {"body": mensaje}}, "test-message")
    return {
        "exito": exito,
        "numero_destino": destino,
        "numero_original": numero,
        "mensaje": mensaje,
        "timestamp": datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /admin/send-template
# ---------------------------------------------------------------------------

@router.post("/admin/send-template")
async def admin_send_template(
    payload: dict,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    """Envía plantilla WhatsApp aprobada a una lista de números.

    Body:
    {
        "template_name": "mensaje_inicial",
        "language": "es",
        "image_url": "https://...",
        "numeros": [
            {"telefono": "5492615031839", "nombre": "Juan"},
            "5492615031839"
        ]
    }
    """
    _check_admin_key(x_admin_key)
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise HTTPException(status_code=503, detail="Credenciales WhatsApp no configuradas")

    template_name = (payload.get("template_name") or "mensaje_inicial").strip()
    language = (payload.get("language") or "es").strip()
    image_url = (payload.get("image_url") or "").strip()
    numeros_raw = payload.get("numeros", [])
    if not numeros_raw:
        raise HTTPException(status_code=400, detail="'numeros' es obligatorio y no puede estar vacío")

    exitosos = []
    fallidos = []
    for entry in numeros_raw:
        if isinstance(entry, str):
            telefono_raw, nombre = entry, ""
        elif isinstance(entry, dict):
            telefono_raw = entry.get("telefono", "")
            nombre = (entry.get("nombre") or "").strip()
        else:
            fallidos.append({"entrada": str(entry), "error": "Formato inválido"})
            continue

        numero = normalize_number(telefono_raw)
        if not numero:
            fallidos.append({"entrada": telefono_raw, "error": "Número inválido"})
            continue

        destino = f"+{numero}" if not numero.startswith("+") else numero
        components = []
        if image_url:
            components.append({
                "type": "header",
                "parameters": [{"type": "image", "image": {"link": image_url}}],
            })
        if nombre:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": nombre}],
            })

        msg = {
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components,
            },
        }
        ok = enviar_payload_whatsapp(destino, msg, f"send-template:{template_name}")
        if ok:
            exitosos.append(destino)
        else:
            fallidos.append({"entrada": telefono_raw, "error": "envio_fallido"})

    return {
        "template": template_name,
        "language": language,
        "total": len(exitosos) + len(fallidos),
        "exitosos": len(exitosos),
        "fallidos_count": len(fallidos),
        "fallidos_preview": fallidos[:25],
    }
