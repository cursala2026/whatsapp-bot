# Bot WhatsApp Cursala

## Estado actual del proyecto
Este repositorio contiene el bot oficial de WhatsApp de Cursala, implementado con FastAPI y desplegado en Cloud Run.

El bot atiende consultas entrantes, guia flujos comerciales (cursos, empresas, profesionales, asesoria), guarda trazabilidad en Firestore y habilita un panel Admin conversacional por WhatsApp.

## Arquitectura resumida
- `main.py`: entrada FastAPI, monta routers.
- `bot/api_webhook.py`: webhook GET/POST de Meta.
- `bot/api_admin.py`: endpoints HTTP administrativos.
- `bot/flow_user.py`: flujo del usuario final.
- `bot/flow_admin.py`: flujo admin.
- `bot/menus.py`: construccion de menus/listas y parseos de comandos.
- `bot/database.py`: Firestore, idempotencia e import/export de contactos.
- `bot/whatsapp_api.py`: cliente de envio/recepcion de media en Meta API.
- `bot/state_manager.py`: sesiones en memoria.
- `bot/utils.py`: validaciones y normalizacion.
- `email_service.py` + `templates_email.py`: correo via Brevo.

## Funcionalidades incluidas
- Onboarding con captura de nombre.
- Menu principal configurable por `menu_config.json`.
- Catalogo de cursos con detalle y acciones por curso.
- Flujos de captura para:
  - Empresas (datos de contacto y necesidad de formacion).
  - Profesionales (postulacion para dictar cursos).
  - Asesoria (empresa y persona fisica).
- Modo admin por WhatsApp con:
  - Edicion de menu/opciones/respuestas.
  - Gestion de cursos y vendedores.
  - Gestion de prompts Gemini.
  - Mensajeria masiva por etiquetas.
  - Administracion de contactos (importar/exportar).
- Importacion de contactos por CSV y XLSX.
- Exportacion de contactos a XLSX desde Firestore.
- Persistencia comercial en Firestore.
- Fallback conversacional con Gemini (configurable).
- Notificaciones por correo via Brevo.

## Optimizaciones activas de rendimiento
- Webhook responde 200 inmediatamente y procesa payload en background.
- Idempotencia con cache en memoria + persistencia async en Firestore.
- Escrituras de tracking en background para no bloquear respuesta al usuario.
- Envio de correos en background.
- Export XLSX paginado y con proyeccion de campos para reducir tiempo de lectura.

## Configuracion minima requerida
### Meta WhatsApp Cloud API
- `ACCESS_TOKEN`
- `PHONE_NUMBER_ID`
- `VERIFY_TOKEN`

### Firestore
- `FIREBASE_CREDENTIALS_PATH`
- `FIREBASE_PROJECT_ID`
- `FIRESTORE_COLLECTION`

### Admin
- `ADMIN_NUMBER`
- `ADMIN_KEY`

### Gemini (opcional)
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `ENABLE_GEMINI_FALLBACK`

### Brevo (opcional)
- `BREVO_API_KEY`
- `MAIL_FROM_EMAIL`
- `MAIL_FROM_NAME`

## Lo que NO esta incluido (alcance explicito)
- No incluye panel web/backoffice grafico: toda la operacion es por WhatsApp o endpoints admin.
- No incluye autenticacion OAuth/JWT para usuarios finales.
- No incluye base SQL ni migraciones: solo Firestore.
- No incluye colas dedicadas (Pub/Sub, Celery, Redis Queue).
- No incluye workers separados para tareas largas; se usan hilos en proceso.
- No incluye tests automatizados integrales del flujo completo.
- No incluye pipeline CI/CD versionado en este repo.
- No incluye infraestructura IaC (Terraform, Pulumi, etc.).
- No incluye rate-limiter por usuario/tenant a nivel aplicacion.
- No incluye auditoria completa de cambios de admin con trazabilidad historica formal.
- No incluye multi-tenant: esta orientado a una sola operacion (Cursala).
- No incluye modulo propio de analitica BI o dashboard de metricas.
- No incluye gestion completa de consentimientos/opt-in marketing legal.
- No incluye reintentos persistentes de tareas fallidas con DLQ.
- No incluye alta disponibilidad multi-region.
- No incluye cifrado de campo a nivel aplicacion para PII (se delega a plataforma/servicios).

## Limitaciones operativas conocidas
- Las sesiones de usuario/admin viven en memoria: se pierden al reiniciar instancia.
- Si Firestore no esta disponible, el bot puede responder pero sin persistencia.
- Menus interactivos de Meta tienen limites estrictos (cantidad de filas y largo de titulos).
- Exportaciones grandes de contactos pueden tardar varios minutos segun volumen y red.

## Archivos auxiliares y de soporte
- `main_monolith_backup.py` y carpeta `BACKUP/`: historicos, no forman parte del runtime productivo.
- `RECUPERACION DE CONTACTOS/`: herramienta externa Node.js (operacion local separada).
- `enviar.py` y `delete_contact.py`: scripts manuales de soporte, no se ejecutan en produccion.

## Ejecucion local
1. Crear y activar entorno virtual.
2. Instalar dependencias desde `requirements.txt`.
3. Configurar `.env` con credenciales.
4. Ejecutar:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

## Despliegue
Despliegue esperado por Cloud Run con `--source .` usando el `Dockerfile` del repositorio.

## Mantenimiento recomendado
- Mantener `menu_config.json` consistente con el flujo real.
- Revisar periodicamente validez de tokens Meta/Brevo/Gemini.
- Registrar en este README cualquier cambio funcional relevante.
