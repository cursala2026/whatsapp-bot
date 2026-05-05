import json
import os
import re
import unicodedata

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))


def normalize_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def norm_text(v: str) -> str:
    s = str(v or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def canonical_label(raw: str) -> str:
    mapping = {
        "redes y telecom": "Redes y telecom",
        "end": "END",
        "diseno de candrias": "Diseño de cañdrias",
        "soldadura": "Soldadura",
        "contacto ig": "Contacto IG",
        "diseno mecanico": "diseño mecánico",
        "pymes": "Pymes",
        "instrumentacion": "Instrumentación",
        "cliente potencial": "Cliente potencial",
        "mineria": "Mineria",
        "logistica": "LOGÍSTICA",
    }
    return mapping.get(norm_text(raw), "")


def main() -> None:
    project_id = os.getenv("FIREBASE_PROJECT_ID", "datosbotcursala")
    credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "datosbotcursala-ece7381fd9d7.json")
    collection = os.getenv("FIRESTORE_COLLECTION", "contactos_whatsapp")

    if not os.path.isabs(credentials_path):
        credentials_path = os.path.join(ROOT, credentials_path)

    if not firebase_admin._apps:
        cred = credentials.Certificate(credentials_path)
        firebase_admin.initialize_app(cred, {"projectId": project_id})

    last_backup_path = os.path.join(ROOT, "RECUPERACION DE CONTACTOS", "exports", "last_backup.json")
    if not os.path.exists(last_backup_path):
        raise RuntimeError("No existe last_backup.json en RECUPERACION DE CONTACTOS/exports")

    with open(last_backup_path, "r", encoding="utf-8") as f:
        last_meta = json.load(f)

    json_path = (last_meta.get("files") or {}).get("json")
    if not json_path:
        raise RuntimeError("last_backup.json no trae ruta de JSON completo")
    if not os.path.exists(json_path):
        json_path = os.path.join(ROOT, "RECUPERACION DE CONTACTOS", "exports", os.path.basename(json_path))
    if not os.path.exists(json_path):
        raise RuntimeError(f"No se encontró JSON de backup: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        contacts = json.load(f)

    db = firestore.client()

    desired_by_number = {}
    for item in contacts:
        if str(item.get("source") or "").strip() != "WA Business":
            continue
        label = canonical_label(item.get("label", ""))
        if not label:
            continue
        num = normalize_digits(item.get("number"))
        if not num:
            continue
        name = " ".join(str(item.get("name") or item.get("pushname") or "").strip().split())
        desired_by_number[num] = {
            "label": label,
            "name": name,
        }

    existing_docs = {d.id: (d, d.to_dict() or {}) for d in db.collection(collection).stream()}

    updated = 0
    created = 0
    removed = 0

    for number, desired in desired_by_number.items():
        if number in existing_docs:
            doc, data = existing_docs[number]
            patch = {}
            current_label = " ".join(str(data.get("etiqueta_cliente") or "").strip().split())
            if current_label != desired["label"]:
                patch["etiqueta_cliente"] = desired["label"]
            current_name = " ".join(str(data.get("nombre") or "").strip().split())
            if desired["name"] and not current_name:
                patch["nombre"] = desired["name"]
                patch["nombre_whatsapp"] = desired["name"]
            if patch:
                doc.reference.set(patch, merge=True)
                updated += 1
        else:
            payload = {
                "whatsapp_number": number,
                "telefono": {
                    "normalizado": number,
                    "e164": f"+{number}",
                },
                "etiqueta_cliente": desired["label"],
                "contacto_agendado": False,
                "agendado_por": "wa_backup_sync",
                "actualizado_en": firestore.SERVER_TIMESTAMP,
            }
            if desired["name"]:
                payload["nombre"] = desired["name"]
                payload["nombre_whatsapp"] = desired["name"]
            db.collection(collection).document(number).set(payload, merge=True)
            created += 1

    # Limpiar etiquetas fuera del set actual de WA labels canónicas
    desired_numbers = set(desired_by_number.keys())
    for doc_id, (doc, data) in existing_docs.items():
        current_label = " ".join(str(data.get("etiqueta_cliente") or "").strip().split())
        if not current_label:
            continue
        if doc_id not in desired_numbers:
            doc.reference.update({"etiqueta_cliente": firestore.DELETE_FIELD})
            removed += 1

    print(f"desired_wa_labeled={len(desired_by_number)}")
    print(f"updated_existing={updated}")
    print(f"created_missing={created}")
    print(f"removed_not_in_latest_backup={removed}")


if __name__ == "__main__":
    main()
