"""Script local de prueba para enviar un mensaje directo a Meta Cloud API.

Uso esperado:
- Diagnostico rapido de credenciales y conectividad fuera del bot principal.

Advertencia:
- Este script no se usa en produccion.
- No debe ejecutarse con tokens reales hardcodeados en entornos compartidos.
"""

import requests

# ============================================================
# SECCION 1 - CREDENCIALES Y PARAMETROS DE PRUEBA
# ============================================================
# Script de utilidad para enviar un mensaje de prueba directo a WhatsApp Cloud API.
# Nota: este archivo contiene datos sensibles hardcodeados y solo deberia usarse
# para pruebas locales controladas.
ACCESS_TOKEN = "EAAMvT4T0yxQBQwV2uDPw0RU7LkCCNhoUUFIycdQKdrnhsLeU6uK1ZAJL9p7oyoTc44CBWf6Hc20vIHiII4RQu0JGZCie26ohLmJx0z6QRZCWwizjE7Ei7jvkau807ZAHIs6gC6T4Q9FvxL37958cqVA80a4JbU0DtuEvhTuCsdGKZBvACeXd3dJoti8j9JmmmUj8B3OZAZAYku2sela8hfBya9y9WEvh1d3M7z3LwSL2EwjzLSoV6ZBL9yxB1Glgxl0pPulUmyyyyXg4xFjYOhJlIak5"
PHONE_NUMBER_ID = "1068569519666363"
TO_NUMBER = "+542615031839"

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
