import os
import sys

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from bot.database import canonicalize_contact_label


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

    updated = 0
    removed = 0
    unchanged = 0

    for doc in docs:
        data = doc.to_dict() or {}
        current = " ".join(str(data.get("etiqueta_cliente", "")).strip().split())
        canonical = canonicalize_contact_label(current)

        if canonical and canonical != current:
            doc.reference.set({"etiqueta_cliente": canonical}, merge=True)
            updated += 1
        elif not canonical and current:
            doc.reference.update({"etiqueta_cliente": firestore.DELETE_FIELD})
            removed += 1
        else:
            unchanged += 1

    print(f"total_docs={len(docs)}")
    print(f"labels_updated={updated}")
    print(f"labels_removed_not_allowed={removed}")
    print(f"unchanged={unchanged}")


if __name__ == "__main__":
    main()
