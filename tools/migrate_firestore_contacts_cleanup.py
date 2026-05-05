import os
import re
from typing import Dict, List, Tuple

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
MENU_CONFIG_PATH = os.path.join(ROOT, "menu_config.json")


def normalize_number(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_text(value: str) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def valid_phone(value: str) -> bool:
    digits = normalize_number(value)
    return 10 <= len(digits) <= 15


def load_course_keywords() -> List[Tuple[str, str]]:
    import json

    if not os.path.exists(MENU_CONFIG_PATH):
        return []

    with open(MENU_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    courses = cfg.get("cursos", {})
    out: List[Tuple[str, str]] = []
    for _, c in courses.items():
        name = " ".join(str(c.get("nombre", "")).split()).strip()
        desc = " ".join(str(c.get("descripcion", "")).split()).strip()
        if not name:
            continue
        key_text = normalize_text(f"{name} {desc}")
        out.append((name, key_text))
    return out


def infer_interests(data: Dict, course_keywords: List[Tuple[str, str]]) -> List[str]:
    texts: List[str] = []

    for field in ("ultima_consulta", "descripcion", "consulta", "mensaje", "motivo"):
        if data.get(field):
            texts.append(str(data.get(field)))

    empresa = data.get("empresa") if isinstance(data.get("empresa"), dict) else {}
    if empresa.get("necesidades"):
        texts.append(str(empresa.get("necesidades")))

    cons_emp = data.get("consulta_asesor_empresa") if isinstance(data.get("consulta_asesor_empresa"), dict) else {}
    if cons_emp.get("motivo"):
        texts.append(str(cons_emp.get("motivo")))

    cons_per = data.get("consulta_asesor_persona") if isinstance(data.get("consulta_asesor_persona"), dict) else {}
    if cons_per.get("motivo"):
        texts.append(str(cons_per.get("motivo")))

    post = data.get("postulacion_profesional") if isinstance(data.get("postulacion_profesional"), dict) else {}
    if post.get("descripcion_curso"):
        texts.append(str(post.get("descripcion_curso")))

    gh = data.get("gemini_history") if isinstance(data.get("gemini_history"), list) else []
    for item in gh:
        if isinstance(item, dict) and item.get("text"):
            texts.append(str(item.get("text")))

    blob = normalize_text(" ".join(texts))
    if not blob:
        return []

    found: List[str] = []
    for course_name, key_text in course_keywords:
        # Matching flexible: any word >=5 chars from course name/description in blob
        tokens = [t for t in key_text.split(" ") if len(t) >= 5]
        if not tokens:
            continue
        if any(tok in blob for tok in tokens):
            found.append(course_name)

    # Deduplicate preserving order
    seen = set()
    clean: List[str] = []
    for v in found:
        if v not in seen:
            clean.append(v)
            seen.add(v)
    return clean


def run() -> None:
    load_dotenv(ENV_PATH)

    project_id = os.getenv("FIREBASE_PROJECT_ID", "datosbotcursala")
    credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "datosbotcursala-ece7381fd9d7.json")
    collection = os.getenv("FIRESTORE_COLLECTION", "contactos_whatsapp")

    if not os.path.isabs(credentials_path):
        credentials_path = os.path.join(ROOT, credentials_path)

    if not firebase_admin._apps:
        cred = credentials.Certificate(credentials_path)
        firebase_admin.initialize_app(cred, {"projectId": project_id})

    db = firestore.client()
    course_keywords = load_course_keywords()

    docs = list(db.collection(collection).stream())
    print(f"Coleccion: {collection}")
    print(f"Total docs: {len(docs)}")

    id_mismatch_docs = 0
    fixed_phone_docs = 0
    name_updates = 0
    interest_updates = 0
    interest_removed = 0
    removed_fields = 0
    unresolved_phone = 0

    for doc in docs:
        data = doc.to_dict() or {}
        doc_id = doc.id

        updates: Dict = {"actualizado_en": firestore.SERVER_TIMESTAMP}

        # 1) Limpiar campos solicitados
        updates["origen"] = firestore.DELETE_FIELD
        updates["indicadores.ultimo_evento"] = firestore.DELETE_FIELD
        removed_fields += 1

        # 2) Resolver nombre segun regla
        contacto_agendado = bool(data.get("contacto_agendado", False))
        nombre_actual = " ".join(str(data.get("nombre", "")).split()).strip()
        nombre_contacto = " ".join(str(data.get("nombre_contacto", "")).split()).strip()
        nombre_whatsapp = " ".join(str(data.get("nombre_whatsapp", "")).split()).strip()

        resolved_name = nombre_actual
        if contacto_agendado and nombre_contacto:
            resolved_name = nombre_contacto
        elif (not contacto_agendado) and nombre_whatsapp:
            resolved_name = nombre_whatsapp

        if resolved_name and resolved_name != nombre_actual:
            updates["nombre"] = resolved_name
            updates["nombre_normalizado"] = normalize_text(resolved_name)
            name_updates += 1

        # 3) Intereses: inferir desde conversaciones/datos; si no hay, eliminar campo
        current_labels = data.get("intereses_labels") if isinstance(data.get("intereses_labels"), list) else []
        inferred = infer_interests(data, course_keywords)

        if inferred:
            tags = [normalize_text(x).replace(" ", "_") for x in inferred]
            updates["intereses_labels"] = inferred
            updates["intereses_tags"] = tags
            updates["indicadores_interes"] = {t: True for t in tags}
            updates["etiqueta_interes"] = tags[0].upper() if tags else firestore.DELETE_FIELD
            interest_updates += 1
        elif not current_labels:
            updates["intereses_labels"] = firestore.DELETE_FIELD
            updates["intereses_tags"] = firestore.DELETE_FIELD
            updates["indicadores_interes"] = firestore.DELETE_FIELD
            updates["etiqueta_interes"] = firestore.DELETE_FIELD
            interest_removed += 1

        # 4) Corregir numeros invalidos
        telefono = data.get("telefono") if isinstance(data.get("telefono"), dict) else {}
        tel_norm = normalize_number(telefono.get("normalizado", ""))
        wa_norm = normalize_number(data.get("whatsapp_number", ""))
        bsuid_norm = normalize_number(data.get("bsuid", ""))

        tel_is_bsuid = bool(tel_norm and bsuid_norm and tel_norm == bsuid_norm)
        tel_invalid = (not valid_phone(tel_norm)) or tel_is_bsuid

        id_valid = valid_phone(doc_id)
        tel_valid = valid_phone(tel_norm) and not tel_is_bsuid
        wa_valid = valid_phone(wa_norm) and (wa_norm != bsuid_norm)

        canonical = ""
        if id_valid:
            canonical = doc_id
        elif tel_valid:
            canonical = tel_norm
        elif wa_valid:
            canonical = wa_norm

        if tel_invalid and canonical:
            updates["telefono.normalizado"] = canonical
            updates["telefono.e164"] = f"+{canonical}"
            updates["whatsapp_number"] = canonical
            fixed_phone_docs += 1

        # No destructivo: no mover/eliminar documentos aunque el ID no sea canonico.
        # Dejamos trazabilidad para revision manual futura.
        if (not id_valid) and canonical and canonical != doc_id:
            updates["migracion.phone_doc_id_mismatch"] = True
            updates["migracion.phone_doc_id_original"] = doc_id
            updates["migracion.phone_doc_id_sugerido"] = canonical
            id_mismatch_docs += 1

        if not canonical:
            unresolved_phone += 1
            updates["migracion.phone_needs_review"] = True

        doc.reference.set(updates, merge=True)

    print("\nResumen migracion:")
    print(f"- docs con doc_id no canonico (marcados para revision, no movidos): {id_mismatch_docs}")
    print(f"- docs con telefono corregido: {fixed_phone_docs}")
    print(f"- nombres actualizados: {name_updates}")
    print(f"- intereses actualizados/inferidos: {interest_updates}")
    print(f"- intereses eliminados (sin inferencia): {interest_removed}")
    print(f"- docs con campos origen/ultimo_evento limpiados: {removed_fields}")
    print(f"- docs sin telefono canonico detectable: {unresolved_phone}")

    # Auditoria puntual solicitada por el usuario
    suspects = list(db.collection(collection).where("nombre", ">=", "Instrum").where("nombre", "<=", "Instrum\uf8ff").stream())
    print("\nCoincidencias por nombre 'Instrum*':")
    for s in suspects:
        d = s.to_dict() or {}
        tel = d.get("telefono") if isinstance(d.get("telefono"), dict) else {}
        print({
            "doc_id": s.id,
            "nombre": d.get("nombre", ""),
            "telefono_normalizado": tel.get("normalizado", ""),
            "telefono_e164": tel.get("e164", ""),
            "bsuid": d.get("bsuid", ""),
        })


if __name__ == "__main__":
    run()
