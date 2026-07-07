# whatsapp-bot (Cursala Bot)

## Descripción del proyecto
Bot de atención al cliente vía WhatsApp con panel de administración de escritorio.
Usa Gemini (google-genai) para generar respuestas, Firestore para persistencia,
y FastAPI como backend de webhooks. Incluye una app de admin standalone
(empaquetada como .exe) para gestión de menús, contactos y vendedores.

## Stack técnico
- **Backend**: FastAPI + Uvicorn (Python)
- **IA**: google-genai (Gemini) para generación de respuestas
- **Base de datos**: Firestore (google-cloud-firestore + firebase-admin)
- **Validación**: Pydantic
- **Reportes**: openpyxl (exportar datos a Excel)
- **Deploy**: Docker + VPS (nginx), con GitHub Actions (.github/workflows)
- **Admin app**: aplicación de escritorio separada en /admin_app, empaquetada con PyInstaller

## Estructura del repo
- `/bot` - lógica principal del bot de WhatsApp
  - `whatsapp_api.py` - integración con la API de WhatsApp
  - `api_webhook.py` - endpoint que recibe mensajes entrantes
  - `api_admin.py` - endpoints de administración
  - `flow_user.py` / `flow_admin.py` - flujos conversacionales de usuario y admin
  - `state_manager.py` - manejo de estado de conversación
  - `database.py` - acceso a Firestore
  - `menus.py` - lógica de menús del bot
  - `audio_transcription.py` - transcripción de notas de voz
  - `config.py` - configuración general
- `/admin_app` - aplicación de escritorio de administración (independiente del bot)
  - `/tabs` - cada pestaña del panel admin (contactos, vendedores, menú, backups, etc.)
- `/tools` - scripts de mantenimiento y migración de datos (sync/migración de Firestore)
- `main.py` - entrada principal de FastAPI. Solo monta routers (`admin_router`,
  `webhook_router`) y arranca uvicorn en local. Toda la lógica de negocio vive en `bot/`.
- `email_service.py` / `templates_email.py` - envío de emails
- `firestore.indexes.json` - índices de Firestore
- `menu_config.json` - configuración del menú del bot

## Comandos importantes
- Instalar dependencias: `pip install -r requirements.txt`
- Correr backend (dev, con auto-reload): `uvicorn main:app --reload --port 8080`
- Correr backend (como en producción): `python main.py`
- Health check: `GET /health`
- Deploy a VPS: `./deploy-vps.sh`
- Docker: `docker-compose up`
- Admin app (dev): `./admin_app/run.sh`
- Build del ejecutable admin: `./admin_app/build_exe.sh`

## Convenciones de código
- Async/await para endpoints de FastAPI y llamadas a Firestore.
- Modelos de datos con Pydantic para validar payloads de webhooks.
- Los flujos de conversación separan claramente lógica de usuario (`flow_user.py`)
  de lógica de administración (`flow_admin.py`) — no mezclar responsabilidades.
- Variable de entorno `GEMINI_MODEL` define el modelo (default: gemini-2.5-flash-lite).

## Seguridad — NUNCA hacer esto
- No leer, mostrar ni loguear el contenido de `.env`, `/secrets`, ni `.admin_config.json`.
- No modificar `firestore.indexes.json` sin confirmar el impacto en producción.
- No tocar `/admin_app/dist` ni `/admin_app/build` (son artefactos generados, no código fuente).

## Al hacer commits
Mensajes en español, formato: `tipo: descripción breve`
(ej. `fix: corrige timeout en transcripción de audio`, `feat: agrega export a excel de contactos`)
EOF