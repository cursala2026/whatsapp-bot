import json
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, '.env'))

from bot.database import firestore_db, FIRESTORE_COLLECTION, upsert_user_profile_firestore, canonicalize_contact_label  # noqa: E402


def digits(value: str) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def main() -> None:
    if firestore_db is None:
        raise RuntimeError('Firestore no inicializado')

    backup_path = os.path.join(ROOT, 'RECUPERACION DE CONTACTOS', 'exports', 'backup_2026-04-12_04-10-21.json')
    if not os.path.exists(backup_path):
        raise RuntimeError(f'No existe backup: {backup_path}')

    with open(backup_path, 'r', encoding='utf-8') as f:
        contacts = json.load(f)

    existing_numbers = set()
    for doc in firestore_db.collection(FIRESTORE_COLLECTION).stream():
        data = doc.to_dict() or {}
        n = digits((data.get('telefono') or {}).get('normalizado') or data.get('whatsapp_number') or doc.id)
        if n:
            existing_numbers.add(n)

    to_sync = []
    for c in contacts:
        n = digits(c.get('number'))
        if not (n.startswith('549') and len(n) == 13):
            continue
        if n in existing_numbers:
            continue

        raw_name = ' '.join(str(c.get('name') or c.get('pushname') or '').strip().split())
        raw_label = str(c.get('label') or '').strip()
        canonical_label = canonicalize_contact_label(raw_label)
        is_contact = str(c.get('isContact') or '').strip().lower() in ('si', 'sí', 'yes', 'true')

        extra = {
            'contacto_agendado': bool(is_contact),
            'agendado_por': 'wa_backup_sync',
            'nombre_whatsapp': raw_name,
            'fuente_sync': 'backup_2026-04-12_04-10-21',
        }

        to_sync.append((n, raw_name, canonical_label, extra))

    synced = 0
    for n, raw_name, canonical_label, extra in to_sync:
        upsert_user_profile_firestore(
            whatsapp_number=n,
            nombre=raw_name or None,
            telefono=n,
            evento='wa_backup_missing_sync',
            extra_fields=extra,
            etiqueta_cliente=canonical_label or None,
        )
        synced += 1

    print(f'existing_numbers={len(existing_numbers)}')
    print(f'contacts_in_backup={len(contacts)}')
    print(f'to_sync={len(to_sync)}')
    print(f'synced={synced}')


if __name__ == '__main__':
    main()
