import glob
import json
import os
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

EXPORTS_DIR = os.path.join(ROOT, "RECUPERACION DE CONTACTOS", "exports")

CANONICAL_PRIORITY = {
    "Redes y telecom": 100,
    "Soldadura": 95,
    "Mineria": 92,
    "LOGÍSTICA": 90,
    "END": 88,
    "Instrumentación": 86,
    "diseño mecánico": 84,
    "Diseño de cañdrias": 82,
    "Contacto IG": 80,
    "Pymes": 78,
    "Cliente potencial": 10,
}


def normalize_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _extract_timestamp_from_filename(path: str):
    base = os.path.basename(path)
    # backup_2026-03-23_19-12-17_firestore.json
    token = base.replace("backup_", "").replace("_firestore.json", "")
    try:
        return datetime.strptime(token, "%Y-%m-%d_%H-%M-%S")
    except Exception:
        return None


def canonical_from_backup_slug(raw: str) -> str:
    slug = "_".join(str(raw or "").strip().split()).lower()
    slug = slug.strip("_")
    mapping = {
        "curso_redes": "Redes y telecom",
        "redes": "Redes y telecom",
        "redes_y_telecom": "Redes y telecom",

        "soldadura": "Soldadura",
        "curso_soldadura": "Soldadura",
        "soldadura__cliente_potencial": "Soldadura",

        "mineria": "Mineria",
        "curso_mineria": "Mineria",
        "mineria__cliente_potencial": "Mineria",
        "mineria__redes_y_telecom": "Mineria",

        "logistica": "LOGÍSTICA",
        "curso_logistica": "LOGÍSTICA",

        "end": "END",
        "contacto_ig": "Contacto IG",

        # Cliente potencial solo para señales explícitas de intención comercial.
        "cliente_potencial": "Cliente potencial",
        "interesado": "Cliente potencial",
    }
    return mapping.get(slug, "")


def choose_better_label(current: str, candidate: str) -> str:
    if not candidate:
        return current
    if not current:
        return candidate
    if CANONICAL_PRIORITY.get(candidate, 0) > CANONICAL_PRIORITY.get(current, 0):
        return candidate
    return current


def main() -> None:
    project_id = os.getenv("FIREBASE_PROJECT_ID", "datosbotcursala")
    credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "datosbotcursala-ece7381fd9d7.json")
    collection = os.getenv("FIRESTORE_COLLECTION", "contactos_whatsapp")

    if not os.path.isabs(credentials_path):
        credentials_path = os.path.join(ROOT, credentials_path)

    if not firebase_admin._apps:
        cred = credentials.Certificate(credentials_path)
        firebase_admin.initialize_app(cred, {"projectId": project_id})

    db = firestore.client()

    files = sorted(glob.glob(os.path.join(EXPORTS_DIR, "backup_*_firestore.json")))
    if not files:
        print("no_backup_files_found")
        return

    # Primero procesar archivos más nuevos; si un archivo viejo aporta una etiqueta más específica,
    # la prioridad la conserva.
    files = sorted(files, key=lambda p: _extract_timestamp_from_filename(p) or datetime.min, reverse=True)

    best_label_by_number = {}
    evidence_count = defaultdict(int)

    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        contactos = payload.get("contactos", []) if isinstance(payload, dict) else []
        for item in contactos:
            num = normalize_digits(item.get("whatsapp_number"))
            if not num:
                continue
            candidate = canonical_from_backup_slug(item.get("etiqueta_cliente", ""))
            if not candidate:
                continue
            current = best_label_by_number.get(num, "")
            chosen = choose_better_label(current, candidate)
            best_label_by_number[num] = chosen
            evidence_count[chosen] += 1

    docs = list(db.collection(collection).stream())
    updated = 0
    unmatched = 0

    for doc in docs:
        data = doc.to_dict() or {}
        num = normalize_digits((data.get("telefono") or {}).get("normalizado") or data.get("whatsapp_number") or doc.id)
        target = best_label_by_number.get(num, "")
        if not target:
            unmatched += 1
            continue
        current = " ".join(str(data.get("etiqueta_cliente") or "").strip().split())
        if current != target:
            doc.reference.set({"etiqueta_cliente": target}, merge=True)
            updated += 1

    print(f"backup_files_scanned={len(files)}")
    print(f"numbers_with_label_from_backup={len(best_label_by_number)}")
    print(f"docs_total={len(docs)}")
    print(f"docs_updated={updated}")
    print(f"docs_without_backup_match={unmatched}")
    print("evidence_top_labels=")
    for k in sorted(evidence_count.keys(), key=lambda x: (-evidence_count[x], x)):
        print(f"  {k}: {evidence_count[k]}")


if __name__ == "__main__":
    main()
