import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Inicializar Firebase
cred = credentials.Certificate('datosbotcursala-ece7381fd9d7.json')
firebase_admin.initialize_app(cred)

db = firestore.client()

# Borrar el documento del contacto
db.collection('contactos_whatsapp').document('2615031839').delete()
print('✅ Contacto 2615031839 eliminado de Firestore')
