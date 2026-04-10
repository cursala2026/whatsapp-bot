"""bot/database.py — Firestore: inicialización, upsert de perfiles, idempotencia.

Importa de bot.config y bot.utils. No importa otros módulos de bot/.
"""

import os
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from bot.config import (
    logger,
    FIREBASE_CREDENTIALS_PATH,
    FIREBASE_PROJECT_ID,
    FIRESTORE_COLLECTION,
)
from bot.utils import (
    normalize_number,
    normalize_text_for_filter,
    normalize_interest_tag,
    build_contact_code,
    infer_argentina_province_from_phone,
    validate_bsuid,
    _normalize_intereses_backup,
)

try:
    import firebase_admin  # type: ignore[import-not-found]
    from firebase_admin import credentials, firestore  # type: ignore[import-not-found]
except Exception:
    firebase_admin = None
    credentials = None
    firestore = None

try:
    from odoo_client import odoo_upsert_contact
    ODOO_ENABLED = True
except Exception as _odoo_import_err:
    import logging
    logging.getLogger("cursala_bot").warning("[Odoo] No se pudo importar odoo_client: %s", _odoo_import_err)
    ODOO_ENABLED = False
    def odoo_upsert_contact(*args, **kwargs):
        return None


# ============================================================
# INICIALIZACIÓN DE FIRESTORE
# ============================================================

def init_firestore_client():
    if firebase_admin is None or credentials is None or firestore is None:
        logger.warning("firebase_admin no esta instalado. Firestore deshabilitado.")
        return None
    if firebase_admin._apps:
        return firestore.client()
    if not os.path.exists(FIREBASE_CREDENTIALS_PATH):
        logger.warning("No se encontro credencial de Firebase en: %s", FIREBASE_CREDENTIALS_PATH)
        logger.warning("Firestore deshabilitado hasta configurar FIREBASE_CREDENTIALS_PATH.")
        return None
    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        if FIREBASE_PROJECT_ID:
            firebase_admin.initialize_app(cred, {"projectId": FIREBASE_PROJECT_ID})
        else:
            firebase_admin.initialize_app(cred)
        logger.info("Firestore inicializado correctamente")
        return firestore.client()
    except Exception as e:
        logger.error("Error inicializando Firestore: %s", e)
        return None


# Singleton global
firestore_db = init_firestore_client()


# ============================================================
# UPSERT DE PERFIL
# ============================================================

def upsert_user_profile_firestore(
    whatsapp_number: str,
    nombre: Optional[str] = None,
    telefono: Optional[str] = None,
    intereses: Optional[list] = None,
    evento: str = "",
    extra_fields: Optional[dict] = None,
    etiqueta_cliente: Optional[str] = None,
    bsuid: Optional[str] = None,
):
    if firestore_db is None:
        return

    phone = telefono or whatsapp_number
    normalized_phone = normalize_number(phone)
    if not normalized_phone:
        return

    provincia, area_code = infer_argentina_province_from_phone(normalized_phone)
    provincia_slug = normalize_interest_tag(provincia)

    payload = {
        "origen": "whatsapp_bot",
        "whatsapp_number": normalize_number(whatsapp_number),
        "telefono": {
            "normalizado": normalized_phone,
            "e164": f"+{normalized_phone}",
            "codigo_area": area_code,
        },
        "provincia_por_numero": {
            "nombre": provincia,
            "slug": provincia_slug,
            "codigo_area": area_code,
        },
        "indicadores": {
            "tiene_telefono": True,
            "provincia_slug": provincia_slug,
            "ultimo_evento": evento or "actualizacion",
        },
        "actualizado_en": firestore.SERVER_TIMESTAMP,
    }

    if bsuid:
        bsuid_validated = validate_bsuid(bsuid)
        if bsuid_validated:
            payload["bsuid"] = bsuid_validated
            payload["indicadores"]["tiene_bsuid"] = True

    if nombre:
        clean_name = " ".join(nombre.strip().split())
        payload["nombre"] = clean_name
        payload["nombre_normalizado"] = normalize_text_for_filter(clean_name)
        payload["indicadores"]["tiene_nombre"] = True

    if intereses:
        labels = [" ".join(str(item).strip().split()) for item in intereses if str(item).strip()]
        tags = [normalize_interest_tag(label) for label in labels]
        tags = [tag for tag in tags if tag]
        if labels:
            payload["intereses_labels"] = firestore.ArrayUnion(labels)
        if tags:
            payload["intereses_tags"] = firestore.ArrayUnion(tags)
            payload["indicadores_interes"] = {tag: True for tag in tags}
            primary_tag = tags[0]
            payload["etiqueta_interes"] = primary_tag.upper()
            payload["contacto_codigo"] = build_contact_code(normalized_phone, primary_tag)
            if not etiqueta_cliente:
                etiqueta_cliente = primary_tag.upper()

    if "contacto_codigo" not in payload:
        payload["contacto_codigo"] = build_contact_code(normalized_phone)

    if extra_fields:
        payload.update(extra_fields)

    if etiqueta_cliente:
        payload["etiqueta_cliente"] = etiqueta_cliente

    try:
        firestore_db.collection(FIRESTORE_COLLECTION).document(normalized_phone).set(payload, merge=True)
    except Exception as e:
        logger.warning("Error guardando perfil en Firestore: %s", e)

    if ODOO_ENABLED and normalized_phone:
        try:
            email_odoo = None
            if extra_fields:
                empresa_data = extra_fields.get("empresa", {})
                if isinstance(empresa_data, dict):
                    email_odoo = empresa_data.get("correo")
            tipo_odoo = "company" if (extra_fields or {}).get("empresa") else "person"
            odoo_upsert_contact(
                phone=normalized_phone,
                nombre=nombre,
                email=email_odoo,
                tipo=tipo_odoo,
                etiqueta_cliente=etiqueta_cliente,
                etiquetas=intereses[:5] if intereses else None,
                provincia=provincia,
            )
        except Exception as e:
            logger.warning("[Odoo] Error sincronizando contacto %s: %s", normalized_phone, e)
            if firestore_db is not None:
                try:
                    firestore_db.collection("odoo_sync_pendientes").add({
                        "phone": normalized_phone,
                        "nombre": nombre,
                        "email": email_odoo,
                        "tipo": tipo_odoo,
                        "etiqueta_cliente": etiqueta_cliente,
                        "error": str(e),
                        "pendiente_desde": firestore.SERVER_TIMESTAMP,
                    })
                except Exception as fe:
                    logger.warning("[Odoo] Error guardando en pendientes: %s", fe)


def track_user_interest(
    whatsapp_number: str,
    interest_label: str,
    evento: str = "interes_detectado",
    etiqueta_cliente: Optional[str] = None,
):
    upsert_user_profile_firestore(
        whatsapp_number=whatsapp_number,
        telefono=whatsapp_number,
        intereses=[interest_label],
        evento=evento,
        etiqueta_cliente=etiqueta_cliente,
    )


# ============================================================
# IDEMPOTENCIA DE MENSAJES
# ============================================================

def _is_message_processed(msg_id: str) -> bool:
    if firestore_db is None or not msg_id:
        return False
    try:
        doc = firestore_db.collection("mensajes_procesados").document(msg_id).get()
        return doc.exists
    except Exception as e:
        logger.warning("[idempotency] Error consultando msg_id %s: %s", msg_id, e)
        return False


def _mark_message_processed(msg_id: str) -> None:
    if firestore_db is None or not msg_id:
        return
    try:
        firestore_db.collection("mensajes_procesados").document(msg_id).set({
            "procesado_en": firestore.SERVER_TIMESTAMP,
        })
    except Exception as e:
        logger.warning("[idempotency] Error guardando msg_id %s: %s", msg_id, e)


# ============================================================
# IMPORTAR CONTACTOS DESDE BACKUP/CSV
# ============================================================

def import_contacts_backup_to_firestore(
    payload: dict,
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    contactos = payload.get("contactos")
    if not isinstance(contactos, list):
        raise HTTPException(status_code=400, detail="Formato invalido: 'contactos' debe ser una lista")

    origen_default = " ".join(str(payload.get("origen", "backup_json")).strip().split()) or "backup_json"
    evento_default = " ".join(str(payload.get("evento_default", "importacion_backup")).strip().split()) or "importacion_backup"

    seen_phones = set()
    imported = 0
    skipped_no_phone = 0
    skipped_duplicates = 0
    skipped_existing = 0
    skipped_invalid = 0
    failed = 0
    failures = []
    total_contacts = len(contactos)

    def _tick_progress(processed: int) -> None:
        if not progress_callback:
            return
        percent = 100 if total_contacts == 0 else int((processed / total_contacts) * 100)
        progress_callback(processed, total_contacts, percent)

    for idx, item in enumerate(contactos, start=1):
        if not isinstance(item, dict):
            skipped_invalid += 1
            failures.append({"index": idx, "error": "item_no_es_objeto"})
            _tick_progress(idx)
            continue

        raw_phone = (
            item.get("whatsapp_number")
            or item.get("phone")
            or item.get("telefono")
            or item.get("numero")
        )
        normalized_phone = normalize_number(raw_phone)

        if not normalized_phone:
            skipped_no_phone += 1
            failures.append({"index": idx, "error": "telefono_invalido_o_ausente"})
            _tick_progress(idx)
            continue

        if normalized_phone in seen_phones:
            skipped_duplicates += 1
            _tick_progress(idx)
            continue
        seen_phones.add(normalized_phone)

        try:
            existing_doc = firestore_db.collection(FIRESTORE_COLLECTION).document(normalized_phone).get()
            if existing_doc.exists:
                skipped_existing += 1
                _tick_progress(idx)
                continue
        except Exception as e:
            failed += 1
            failures.append({"index": idx, "telefono": normalized_phone, "error": f"error_verificando_existencia: {e}"})
            _tick_progress(idx)
            continue

        nombre = " ".join(str(item.get("nombre", "")).strip().split())
        etiqueta_cliente = " ".join(str(item.get("etiqueta_cliente", "")).strip().split())
        intereses = _normalize_intereses_backup(item.get("intereses"))
        ultimo_evento = " ".join(str(item.get("ultimo_evento", evento_default)).strip().split()) or "importacion_backup"

        extra_fields: Dict[str, Any] = {}
        if isinstance(item.get("extra_fields"), dict):
            extra_fields.update(item.get("extra_fields", {}))

        origen_item = " ".join(str(item.get("origen", "")).strip().split())
        extra_fields["origen"] = origen_item or origen_default
        extra_fields.setdefault("contacto_agendado", True)
        extra_fields.setdefault("agendado_por", "importacion_backup")

        try:
            upsert_user_profile_firestore(
                whatsapp_number=normalized_phone,
                nombre=nombre or None,
                telefono=normalized_phone,
                intereses=intereses or None,
                evento=ultimo_evento,
                extra_fields=extra_fields,
                etiqueta_cliente=etiqueta_cliente or None,
            )
            imported += 1
        except Exception as e:
            failed += 1
            failures.append({"index": idx, "telefono": normalized_phone, "error": str(e)})
        finally:
            _tick_progress(idx)

    return {
        "ok": True,
        "collection": FIRESTORE_COLLECTION,
        "summary": {
            "total_recibidos": len(contactos),
            "importados": imported,
            "omitidos_sin_telefono": skipped_no_phone,
            "omitidos_duplicados": skipped_duplicates,
            "omitidos_ya_registrados": skipped_existing,
            "omitidos_invalidos": skipped_invalid,
            "fallidos": failed,
        },
        "failures_preview": failures[:25],
    }


# ============================================================
# CONSULTAS DE CONTACTOS PARA BROADCAST
# ============================================================

def get_all_distinct_tags_from_firestore(limit: int = 500) -> list:
    if firestore_db is None:
        return []
    try:
        docs = list(firestore_db.collection(FIRESTORE_COLLECTION).limit(limit).stream())
        tags = set()
        for doc in docs:
            data = doc.to_dict() or {}
            label = " ".join(str(data.get("etiqueta_cliente", "")).strip().split())
            if label and label.lower() not in ("sin_etiqueta", ""):
                tags.add(label)
        return sorted(tags)
    except Exception as e:
        logger.warning("Error obteniendo etiquetas de Firestore: %s", e)
        return []


def get_contacts_by_label(label: str, limit: int = 500) -> list:
    if firestore_db is None:
        return []
    try:
        docs = list(
            firestore_db.collection(FIRESTORE_COLLECTION)
            .where("etiqueta_cliente", "==", label)
            .limit(limit)
            .stream()
        )
        contacts = []
        for doc in docs:
            data = doc.to_dict() or {}
            telefono = (data.get("telefono") or {}).get("normalizado") or doc.id
            if not telefono:
                continue
            nombre = " ".join(str(data.get("nombre", "")).strip().split())
            bsuid = data.get("bsuid") or ""
            contacts.append({"telefono": telefono, "nombre": nombre, "bsuid": bsuid})
        return contacts
    except Exception as e:
        logger.warning("Error consultando contactos por etiqueta '%s': %s", label, e)
        return []


def get_all_contacts_from_firestore(limit: int = 500) -> list:
    if firestore_db is None:
        return []
    try:
        docs = list(firestore_db.collection(FIRESTORE_COLLECTION).limit(limit).stream())
        contacts = []
        for doc in docs:
            data = doc.to_dict() or {}
            telefono = (data.get("telefono") or {}).get("normalizado") or doc.id
            if not telefono:
                continue
            nombre = " ".join(str(data.get("nombre", "")).strip().split())
            bsuid = data.get("bsuid") or ""
            contacts.append({"telefono": telefono, "nombre": nombre, "bsuid": bsuid})
        return contacts
    except Exception as e:
        logger.warning("Error obteniendo todos los contactos de Firestore: %s", e)
        return []


def build_contacts_saved_list_message(limit: int = 20) -> str:
    if firestore_db is None:
        return "⚠️ Firestore no configurado."

    safe_limit = max(1, min(limit, 50))
    docs = []

    try:
        if firestore is not None and hasattr(firestore, "Query"):
            docs = list(
                firestore_db
                .collection(FIRESTORE_COLLECTION)
                .order_by("actualizado_en", direction=firestore.Query.DESCENDING)
                .limit(safe_limit)
                .stream()
            )
        else:
            docs = list(
                firestore_db
                .collection(FIRESTORE_COLLECTION)
                .limit(safe_limit)
                .stream()
            )
    except Exception:
        docs = list(
            firestore_db
            .collection(FIRESTORE_COLLECTION)
            .limit(safe_limit)
            .stream()
        )

    if not docs:
        return "📭 No hay contactos guardados todavía."

    lines = [f"*CONTACTOS GUARDADOS* (últimos {len(docs)})", ""]
    for idx, doc in enumerate(docs, start=1):
        data = doc.to_dict() or {}
        nombre = " ".join(str(data.get("nombre", "")).strip().split()) or "(sin nombre)"
        telefono = (data.get("telefono", {}) or {}).get("normalizado") or doc.id
        etiqueta = " ".join(str(data.get("etiqueta_cliente", "")).strip().split()) or "sin_etiqueta"
        if len(nombre) > 28:
            nombre = nombre[:28].rstrip() + "..."
        lines.append(f"{idx}. {nombre} | {telefono} | {etiqueta}")

    lines.append("")
    lines.append("0. Volver al menú admin")
    return "\n".join(lines)
