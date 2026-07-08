"""bot/api_admin.py — Rutas HTTP administrativas."""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
import io

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
from bot.database import (
    firestore_db,
    upsert_user_profile_firestore,
    generate_contacts_template_excel,
    export_all_contacts_to_xlsx_bytes,
    get_all_contacts_from_firestore,
    get_contacts_by_label,
    get_all_distinct_tags_from_firestore,
)
from bot.menus import (
    menu_config,
    save_menu_config,
    create_menu_backup,
    list_backups,
    restore_menu_backup,
    execute_broadcast_send,
)
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
# MENU CONFIG ADMIN
# ---------------------------------------------------------------------------

@router.get("/admin/menu-config")
async def admin_get_menu_config(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    return {"ok": True, "config": menu_config}


@router.put("/admin/menu-config")
async def admin_put_menu_config(
    payload: dict,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    new_config = payload.get("config") if isinstance(payload, dict) else None
    if not isinstance(new_config, dict):
        raise HTTPException(status_code=400, detail="'config' debe ser un objeto JSON")

    required = ["greeting", "options", "responses", "cursos", "vendedores", "email_notificacion_admin", "gemini_prompt_rules"]
    for key in required:
        if key not in new_config:
            raise HTTPException(status_code=400, detail=f"Falta clave obligatoria en config: {key}")

    menu_config.clear()
    menu_config.update(new_config)
    save_menu_config(menu_config)
    return {"ok": True, "message": "menu_config actualizado"}


@router.get("/admin/menu-config/backups")
async def admin_list_menu_backups(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    backups = list_backups()
    return {"ok": True, "count": len(backups), "backups": backups}


@router.post("/admin/menu-config/backup")
async def admin_create_menu_backup(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    filename = create_menu_backup(menu_config)
    return {"ok": True, "filename": filename}


@router.post("/admin/menu-config/backups/restore")
async def admin_restore_menu_backup(
    payload: dict,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    filename = str((payload or {}).get("filename", "")).strip()
    if not filename:
        raise HTTPException(status_code=400, detail="'filename' es obligatorio")

    config_ref = [menu_config]
    restored = restore_menu_backup(filename, config_ref)
    if not restored:
        raise HTTPException(status_code=404, detail="Backup no encontrado")

    menu_config.clear()
    menu_config.update(config_ref[0])
    return {"ok": True, "message": f"Backup restaurado: {filename}"}


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
    imported = 0
    skipped_no_phone = 0
    skipped_dup = 0
    skipped_existing = 0
    skipped_invalid = 0
    failed = 0
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


@router.get("/admin/firestore/labels")
async def admin_firestore_labels(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)
    labels = get_all_distinct_tags_from_firestore(limit=5000)
    return {"ok": True, "count": len(labels), "labels": labels}


@router.get("/admin/firestore/contacts/export-xlsx")
async def admin_export_contacts_xlsx(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
    limit: int = Query(default=5000, ge=1, le=5000),
    label_filter: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
):
    _check_admin_key(x_admin_key)
    try:
        file_bytes, count = export_all_contacts_to_xlsx_bytes(
            limit=limit,
            label_filter=label_filter,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exportando XLSX: {e}")

    filename = "contactos_export.xlsx"
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "x-export-count": str(count),
        },
    )


@router.get("/admin/export-all-contacts-xlsx")
async def admin_export_all_contacts_xlsx_compat(
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
    limit: int = Query(default=5000, ge=1, le=5000),
):
    return await admin_export_contacts_xlsx(
        x_admin_key=x_admin_key,
        limit=limit,
        label_filter=None,
        date_from=None,
        date_to=None,
    )


# ---------------------------------------------------------------------------
# GET /admin/download-contacts-template
# ---------------------------------------------------------------------------

@router.get("/admin/download-contacts-template")
async def download_contacts_template(x_admin_key: Optional[str] = Header(None)):
    """Descarga plantilla Excel para carga de contactos."""
    _check_admin_key(x_admin_key)
    
    try:
        template_bytes = generate_contacts_template_excel()
    except Exception as e:
        logger.error("Error generando plantilla Excel: %s", e)
        raise HTTPException(status_code=500, detail=f"Error generando plantilla: {str(e)}")
    
    return StreamingResponse(
        io.BytesIO(template_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_contactos.xlsx"},
    )


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


@router.post("/admin/broadcast/send")
async def admin_broadcast_send(
    payload: dict,
    x_admin_key: Optional[str] = Header(default=None, alias="x-admin-key"),
):
    _check_admin_key(x_admin_key)

    filter_mode = str((payload or {}).get("filter_mode", "all")).strip().lower()
    label = str((payload or {}).get("label", "")).strip()
    msg_type = str((payload or {}).get("msg_type", "text")).strip().lower()
    message = str((payload or {}).get("message", "")).strip()
    template_name = str((payload or {}).get("template_name", "mensaje_inicial")).strip()
    template_lang = str((payload or {}).get("template_lang", "es")).strip()

    if filter_mode not in {"all", "label"}:
        raise HTTPException(status_code=400, detail="filter_mode debe ser 'all' o 'label'")
    if msg_type not in {"text", "template"}:
        raise HTTPException(status_code=400, detail="msg_type debe ser 'text' o 'template'")

    if msg_type == "text" and not message:
        raise HTTPException(status_code=400, detail="message es obligatorio para msg_type='text'")
    if msg_type == "template" and not template_name:
        raise HTTPException(status_code=400, detail="template_name es obligatorio para msg_type='template'")

    if filter_mode == "all":
        contacts = get_all_contacts_from_firestore(limit=5000)
    else:
        if not label:
            raise HTTPException(status_code=400, detail="label es obligatorio cuando filter_mode='label'")
        contacts = get_contacts_by_label(label, limit=5000)

    if not contacts:
        return {"ok": True, "enviados": 0, "fallidos": 0, "errores": [], "message": "No hay contactos para enviar"}

    result = execute_broadcast_send(
        contacts=contacts,
        msg_type=msg_type,
        message=message,
        template_name=template_name,
        template_lang=template_lang,
    )

    return {
        "ok": True,
        "total": len(contacts),
        "enviados": result.get("enviados", 0),
        "fallidos": result.get("fallidos", 0),
        "errores": result.get("errores", []),
        "filter_mode": filter_mode,
        "label": label,
        "msg_type": msg_type,
    }
