"""Script local de prueba para enviar un mensaje directo a Meta Cloud API.

Uso esperado:
- Diagnostico rapido de credenciales y conectividad fuera del bot principal.

Advertencia:
- Este script no se usa en produccion.
- No debe ejecutarse con tokens reales hardcodeados en entornos compartidos.
"""

import os
import requests
from dotenv import load_dotenv

# ============================================================
# SECCION 1 - CREDENCIALES Y PARAMETROS DE PRUEBA
# ============================================================
# Script de utilidad para enviar un mensaje de prueba directo a WhatsApp Cloud API.
# Las credenciales se leen desde .env, nunca hardcodeadas en el archivo.
load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
TO_NUMBER = os.getenv("TEST_RECIPIENT")

if not ACCESS_TOKEN or not PHONE_NUMBER_ID or not TO_NUMBER:
    raise SystemExit(
        "Faltan variables de entorno. Revisá que .env tenga ACCESS_TOKEN, "
        "PHONE_NUMBER_ID y TEST_RECIPIENT."
    )

# ============================================================
# SECCION 2 - CONSTRUCCION DE REQUEST HTTP
# ============================================================
url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

payload = {
    "messaging_product": "whatsapp",
    "to": TO_NUMBER,
    "type": "text",
    "text": {
        "body": "Hola, esta es una prueba desde Python local."
    }
}

# ============================================================
# SECCION 3 - EJECUCION Y LOG DE RESULTADO
# ============================================================
response = requests.post(url, headers=headers, json=payload)

print("Código de respuesta:", response.status_code)
print("Respuesta:")
print(response.text)