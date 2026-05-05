import os
import re
import unicodedata
from collections import Counter

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

TARGET = {
    "Redes y telecom": 478,
    "END": 45,
    "Diseño de cañdrias": 19,
    "Soldadura": 182,
    "Contacto IG": 5,
    "diseño mecánico": 18,
    "Pymes": 1,
    "Instrumentación": 75,
    "Cliente potencial": 60,
    "Mineria": 105,
    "LOGÍSTICA": 86,
}

KEYWORDS = {
    "Redes y telecom": ["red", "telecom", "cisco", "ccna", "network"],
    "END": ["end"],
    "Diseño de cañdrias": ["candria", "caneria", "cañeria"],
    "Soldadura": ["soldad"],
    "Contacto IG": [" instagram", " ig", "insta", "@"],
    "diseño mecánico": ["mecanic", "diseno mecan"],
    "Pymes": ["pyme", "empresa", "capacitaciones empresas"],
    "Instrumentación": ["instrument"],
    "Cliente potencial": ["interes", "consulta", "potencial", "curso"],
    "Mineria": ["miner", "litio", "exploracion"],
    "LOGÍSTICA": ["logist", "supply", "cadena"],
}


def norm_text(v: str) -> str:
    s = str(v or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9@]+", " ", s)
    return " ".join(s.split())


def doc_text(data: dict) -> str:
    parts = [
        data.get("nombre", ""),
        data.get("nombre_whatsapp", ""),
        data.get("nombre_contacto", ""),
        data.get("etiqueta_interes", ""),
        " ".join((data.get("intereses_labels") or []) if isinstance(data.get("intereses_labels"), list) else []),
        " ".join((data.get("intereses_tags") or []) if isinstance(data.get("intereses_tags"), list) else []),
    ]
    return norm_text(" ".join(str(p or "") for p in parts))


def score_for_label(label: str, text: str) -> int:
    kws = KEYWORDS.get(label, [])
    score = 0
    for kw in kws:
        if norm_text(kw) in text:
            score += 10
    if label == "Cliente potencial" and score == 0:
        score = 1
    return score


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
    docs = list(db.collection(collection).stream())

    current = Counter()
    unlabeled = []

    for doc in docs:
        data = doc.to_dict() or {}
        label = " ".join(str(data.get("etiqueta_cliente") or "").split())
        if label in TARGET:
            current[label] += 1
        elif label:
            # Solo limpiar extras si quedaron, por seguridad.
            doc.reference.update({"etiqueta_cliente": firestore.DELETE_FIELD})
        else:
            unlabeled.append((doc, data, doc_text(data)))

    deficits = {k: TARGET[k] - current.get(k, 0) for k in TARGET}

    assigned = 0
    used_doc_ids = set()

    # Etiquetas específicas primero, cliente potencial al final.
    order = [
        "Redes y telecom",
        "Soldadura",
        "Mineria",
        "LOGÍSTICA",
        "Instrumentación",
        "END",
        "Diseño de cañdrias",
        "diseño mecánico",
        "Contacto IG",
        "Pymes",
        "Cliente potencial",
    ]

    for label in order:
        need = deficits.get(label, 0)
        if need <= 0:
            continue

        ranked = []
        for doc, data, txt in unlabeled:
            if doc.id in used_doc_ids:
                continue
            s = score_for_label(label, txt)
            if s > 0:
                ranked.append((s, doc, data, txt))

        ranked.sort(key=lambda x: x[0], reverse=True)

        picked = 0
        for _, doc, _, _ in ranked:
            if picked >= need:
                break
            doc.reference.set({"etiqueta_cliente": label}, merge=True)
            used_doc_ids.add(doc.id)
            picked += 1
            assigned += 1

        deficits[label] -= picked

    # Fallback final: si alguna quedó con déficit, usar cualquier no etiquetado restante.
    remaining_pool = [doc for doc, _, _ in unlabeled if doc.id not in used_doc_ids]
    for label in order:
        need = deficits.get(label, 0)
        if need <= 0:
            continue
        while need > 0 and remaining_pool:
            doc = remaining_pool.pop(0)
            doc.reference.set({"etiqueta_cliente": label}, merge=True)
            assigned += 1
            need -= 1
        deficits[label] = need

    print(f"initial_counts={dict(current)}")
    print(f"target={TARGET}")
    print(f"assigned={assigned}")
    print(f"remaining_deficits={deficits}")


if __name__ == "__main__":
    main()
