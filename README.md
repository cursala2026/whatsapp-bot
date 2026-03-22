# whatsapp-bot

Bot de WhatsApp para Cursala, desarrollado con FastAPI y la API de WhatsApp Business de Meta.

## Funcionalidades

- Menú interactivo con opciones guiadas (cursos, empresas, profesionales, asesor).
- Panel de administración para gestionar el menú, cursos y vendedores.
- **Modo híbrido con IA** (Google Gemini): cuando el usuario escribe algo que no coincide con ninguna opción del menú, el bot responde automáticamente mediante inteligencia artificial.

## Configuración de variables de entorno (`.env`)

```
ACCESS_TOKEN=<token de la API de WhatsApp Business>
VERIFY_TOKEN=<token de verificación del webhook>
PHONE_NUMBER_ID=<ID del número de teléfono de WhatsApp>
ADMIN_NUMBER=<número de WhatsApp del administrador>
ADMIN_KEY=<contraseña del panel de administración>

# IA híbrida (opcional pero recomendado)
# Obtené tu clave gratuita en: https://aistudio.google.com/apikey
GEMINI_API_KEY=<tu clave de API de Google Gemini>
```

## Configuración de la IA híbrida (Google Gemini)

La integración usa **Google Gemini 1.5 Flash**, que tiene una **capa gratuita** generosa:

- ✅ 15 solicitudes por minuto
- ✅ 1.500 solicitudes por día
- ✅ Sin necesidad de tarjeta de crédito para el nivel gratuito

### Pasos para obtener la clave:

1. Ingresá a [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Iniciá sesión con tu cuenta de Google.
3. Hacé clic en **"Crear clave de API"**.
4. Copiá la clave generada y agregala al archivo `.env` como `GEMINI_API_KEY`.

Si `GEMINI_API_KEY` no está configurada, el bot continúa funcionando normalmente (sin la respuesta de IA).

## Instalación

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```
