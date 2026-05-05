import os
from collections import defaultdict

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, '.env'))


def normalize_number(value: str) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def looks_like_real_whatsapp_number(value: str) -> bool:
    digits = normalize_number(value)
    if len(digits) < 10 or len(digits) > 15:
        return False
    if not digits.startswith('54'):
        return False
    return len(digits) in (12, 13)


def score(doc_id: str, data: dict) -> int:
    tel = (data.get('telefono') or {}).get('normalizado', '')
    num = normalize_number(tel or data.get('whatsapp_number', '') or doc_id)
    contacto_agendado = bool(data.get('contacto_agendado', False))
    points = 0
    if looks_like_real_whatsapp_number(num):
        points += 100
    if num.startswith('549'):
        points += 50
    if contacto_agendado:
        points += 5
    return points


def main() -> None:
    project_id = os.getenv('FIREBASE_PROJECT_ID', 'datosbotcursala')
    credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH', 'datosbotcursala-ece7381fd9d7.json')
    collection = os.getenv('FIRESTORE_COLLECTION', 'contactos_whatsapp')

    if not os.path.isabs(credentials_path):
        credentials_path = os.path.join(ROOT, credentials_path)

    if not firebase_admin._apps:
        cred = credentials.Certificate(credentials_path)
        firebase_admin.initialize_app(cred, {'projectId': project_id})

    db = firestore.client()
    docs = list(db.collection(collection).stream())

    grouped = defaultdict(list)
    for doc in docs:
        data = doc.to_dict() or {}
        nombre = ' '.join(str(data.get('nombre', '')).split()).strip()
        if not nombre:
            continue
        grouped[nombre].append((doc, data))

    marked = 0
    reviewed = 0
    for nombre, items in grouped.items():
        if len(items) < 2:
            continue

        ranked = sorted(items, key=lambda pair: score(pair[0].id, pair[1]), reverse=True)
        best_doc, best_data = ranked[0]
        best_num = normalize_number((best_data.get('telefono') or {}).get('normalizado', '') or best_data.get('whatsapp_number', '') or best_doc.id)
        best_valid = looks_like_real_whatsapp_number(best_num)

        for doc, data in ranked[1:]:
            current_num = normalize_number((data.get('telefono') or {}).get('normalizado', '') or data.get('whatsapp_number', '') or doc.id)
            current_valid = looks_like_real_whatsapp_number(current_num)
            updates = {
                'reviewed_duplicate_name': True,
                'duplicate_name': nombre,
                'preferred_number': best_num,
                'migracion_actualizado_en': firestore.SERVER_TIMESTAMP,
            }
            reviewed += 1

            # Si el mejor es valido y este no lo es, bloquear export de este registro.
            if best_valid and not current_valid:
                updates['export_blocked'] = True
                updates['numero_erroneo'] = True
                marked += 1
            else:
                updates['export_blocked'] = False

            doc.reference.set(updates, merge=True)

    print(f'reviewed_duplicates={reviewed}')
    print(f'export_blocked_marked={marked}')

    docs_instrum = list(db.collection(collection).where('nombre', '==', 'Instrum 8').stream())
    print('instrum8_after=')
    for doc in docs_instrum:
        data = doc.to_dict() or {}
        print({
            'id': doc.id,
            'nombre': data.get('nombre', ''),
            'telefono': (data.get('telefono') or {}).get('normalizado', ''),
            'whatsapp_number': data.get('whatsapp_number', ''),
            'export_blocked': data.get('export_blocked'),
            'numero_erroneo': data.get('numero_erroneo'),
            'preferred_number': data.get('preferred_number'),
        })


if __name__ == '__main__':
    main()
