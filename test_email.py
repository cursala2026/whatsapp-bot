"""Script de prueba aislado para verificar la integración con Brevo.

Uso:
    python test_email.py

Requiere .env con:
    BREVO_API_KEY=...
    MAIL_FROM_EMAIL=...
    MAIL_FROM_NAME=Cursala
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

from email_service import procesar_notificacion_registro
from templates_email import armar_correo_notificacion_registro

DESTINATARIO_TEST = (
    sys.argv[1].strip()
    if len(sys.argv) > 1 and sys.argv[1].strip()
    else os.getenv("TEST_EMAIL_DESTINATARIO", "info@cursala.com.ar").strip()
)

print("=" * 60)
print("TEST DE INTEGRACIÓN BREVO - CURSALA BOT")
print("=" * 60)

api_key = os.getenv("BREVO_API_KEY", "")
from_email = os.getenv("MAIL_FROM_EMAIL", "")
from_name = os.getenv("MAIL_FROM_NAME", "Cursala")

print(f"BREVO_API_KEY:   {'✅ cargada (' + api_key[:12] + '...)' if api_key else '❌ NO encontrada'}")
print(f"MAIL_FROM_EMAIL: {'✅ ' + from_email if from_email else '❌ NO encontrado'}")
print(f"MAIL_FROM_NAME:  {from_name}")
print()

if not api_key or not from_email:
    print("❌ Faltan variables en .env. Creá el archivo con BREVO_API_KEY y MAIL_FROM_EMAIL.")
    exit(1)

print(f"Enviando correo de prueba a: {DESTINATARIO_TEST}")
print()

ok, detalle = procesar_notificacion_registro(
    telefono="5492615031839",
    nombre="Usuario de Prueba",
    menu_origen="test_script",
    destinatario=DESTINATARIO_TEST,
    asunto="[TEST] Nuevo contacto en WhatsApp Bot - Cursala",
    cuerpo_intro="Este es un correo de prueba generado por test_email.py para verificar la integración con Brevo.",
)

if ok:
    print(f"✅ Correo enviado correctamente.")
    print(f"   messageId: {detalle}")
else:
    print(f"❌ Error al enviar el correo:")
    print(f"   {detalle}")
