# Bot de WhatsApp Cursala

## Objetivo del proyecto

Este repositorio contiene el bot de WhatsApp de Cursala. El sistema atiende consultas entrantes por WhatsApp, guía al usuario por flujos estructurados, registra información comercial en Firestore, envía notificaciones por correo y expone un modo Admin conversacional para operar el menú, el catálogo y parte de la configuración sin editar el código manualmente.

Este archivo es el manual vivo del bot. Cada cambio funcional relevante debe reflejarse aquí en el mismo momento en que se modifica el comportamiento del sistema.

## Qué hace el bot hoy

El bot actualmente permite:

- Dar la bienvenida al contacto y pedir su nombre antes de comenzar.
- Mostrar un menú principal configurable desde `menu_config.json`.
- Guiar al usuario por el catálogo de cursos.
- Mostrar detalle por curso con accesos directos a sitio web, temario y contacto con asesor.
- Capturar leads de empresas interesadas en capacitaciones.
- Capturar postulaciones de profesionales que quieren dictar capacitaciones.
- Capturar solicitudes para hablar con un asesor, tanto para empresa como para persona física.
- Guardar trazabilidad del contacto y sus intereses en Firestore.
- Enviar correos automáticos de confirmación y notificaciones internas.
- Responder texto libre con Gemini cuando el fallback conversacional está habilitado.
- Permitir administración conversacional del contenido y de configuraciones clave desde WhatsApp mediante modo Admin.

## Arquitectura general

La aplicación corre sobre FastAPI y expone endpoints HTTP para Meta WhatsApp Cloud API y administración técnica. El archivo principal es `main.py`, que concentra:

- configuración y variables de entorno,
- endpoints de salud y administración,
- utilidades de validación y persistencia,
- construcción de menús,
- envío de mensajes a WhatsApp,
- flujo conversacional del usuario,
- flujo conversacional del administrador,
- integración opcional con Gemini,
- integración con Firestore y Brevo.

### Componentes principales

- `main.py`: núcleo del bot, webhook, menús, flujos, admin y Firestore.
- `menu_config.json`: contenido editable del menú, cursos, vendedores, reglas de Gemini y revisión de menú.
- `email_service.py`: integración con Brevo para envío de correos.
- `templates_email.py`: armado de plantillas HTML y texto plano.
- `enviar.py`: utilidad CLI para enviar mensajes salientes por WhatsApp Cloud API.
- `test_email.py`: script para probar integración de correo con Brevo.
- `Dockerfile`: imagen base para despliegue.

## Dependencias principales

Según `requirements.txt`, el proyecto utiliza:

- `fastapi`
- `uvicorn[standard]`
- `python-dotenv`
- `requests`
- `firebase-admin`
- `google-genai`

## Variables de entorno relevantes

El bot depende de un archivo `.env` o variables equivalentes en runtime.

### WhatsApp / Meta

- `ACCESS_TOKEN`: token de acceso para WhatsApp Cloud API.
- `VERIFY_TOKEN`: token de verificación del webhook.
- `PHONE_NUMBER_ID`: identificador del número configurado en Meta.
- `TEST_RECIPIENT`: si está definido, redirige respuestas salientes a ese número para pruebas.

### Admin y operación

- `ADMIN_NUMBER`: número habilitado para ingresar al modo Admin.
- `ADMIN_KEY`: contraseña del modo Admin.
- `K_SERVICE`
- `K_REVISION`
- `K_CONFIGURATION`

Estas últimas se usan para mostrar información de revisión del despliegue desde el panel Admin.

### Gemini

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `ENABLE_GEMINI_FALLBACK`

Si `ENABLE_GEMINI_FALLBACK=false`, el bot no responde con IA fuera de los flujos determinísticos.

### Firestore

- `FIREBASE_CREDENTIALS_PATH`
- `FIREBASE_PROJECT_ID`
- `FIRESTORE_COLLECTION`

Si Firebase no está configurado correctamente, el bot sigue funcionando, pero sin persistencia en Firestore ni endpoints administrativos dependientes de esa base.

### Email / Brevo

- `BREVO_API_KEY`
- `MAIL_FROM_EMAIL`
- `MAIL_FROM_NAME`
- `TEST_EMAIL_DESTINATARIO`

### Templates opcionales de curso

- `COURSE_URL_TEMPLATE_NAME`
- `COURSE_URL_TEMPLATE_LANGUAGE`
- `COURSE_URL_TEMPLATE_MODE`

## Fuente funcional del menú

El archivo `menu_config.json` define buena parte del comportamiento visible del bot:

- `greeting`: saludo principal.
- `options`: opciones numeradas del menú principal.
- `responses`: respuestas asociadas a opciones editables.
- `cursos`: catálogo de cursos con nombre, descripción, links y vendedor asociado.
- `vendedores`: asesores/vendedores configurados.
- `email_notificacion_admin`: configuración de notificaciones internas.
- `gemini_prompt_rules`: reglas adicionales que enriquecen el prompt conversacional.
- `revision`: versión y fecha/hora del último cambio guardado del menú.

### Cursos cargados actualmente

Actualmente el menú incluye estos cursos:

1. Exploración Minera
2. Soldadura
3. Piping
4. Redes y telecomunicaciones
5. Instrumentación y control
6. Ordená tu Pyme
7. Ensayos No destructivos
8. Logística para Pymes
9. Auxiliar técnico Perforación Rotary
10. Auxiliar técnico en fluidos de perforación
11. Control de desviación en sondajes diamantinos

### Vendedores cargados actualmente

Actualmente figuran:

1. Luis Varela
2. Angelo Micieli
3. Martín Olivares

Observación: en el `menu_config.json` actual los teléfonos de los vendedores figuran como `N/A`. Eso afecta el contacto clickeable por WhatsApp, ya que el bot solo genera enlaces directos si el número es válido.

## Flujo general del usuario

El bot trabaja con una sesión en memoria por número de teléfono. Además, cuando Firestore está disponible, complementa esa sesión con persistencia comercial.

### 1. Onboarding inicial

Cuando el usuario escribe por primera vez o no tiene nombre cargado en sesión:

- el bot saluda según horario,
- solicita el nombre,
- valida que el nombre no tenga números,
- guarda el nombre en sesión,
- registra el nombre en Firestore si está disponible.

Si el usuario había enviado un comando antes de completar el onboarding, el bot intenta reanudar automáticamente el flujo pendiente después de capturar el nombre.

### 2. Menú principal

Las opciones visibles actuales son:

1. Cursos Disponibles
2. Capacitaciones para empresas
3. Quiero capacitar
4. Quiero hablar con un asesor

El menú principal se puede mostrar:

- con saludo, cuando es un ingreso inicial,
- sin saludo, cuando el usuario vuelve desde un subflujo y ya está en sesión activa.

### 3. Opción 1: Cursos disponibles

El bot:

- marca interés en cursos en Firestore,
- muestra el catálogo numerado,
- permite ingresar el número del curso,
- también admite atajos por texto como `c1`, `c2`, etc.,
- abre un menú de detalle por curso.

#### Detalle de curso

Cada curso muestra:

- nombre del curso,
- descripción,
- acceso para ver curso,
- acceso para ver temario,
- acceso para hablar con asesor de inscripción,
- opción para volver al menú principal.

Acciones disponibles por curso:

- `1`: ver curso.
- `2`: ver programa o temario.
- `3`: contactar asesor de inscripción.
- `0`: volver al menú principal.

El bot soporta identificadores directos del tipo:

- `course:{id}:view`
- `course:{id}:syllabus`
- `course:{id}:buy`

Si hay integración CTA/template disponible, intenta enviar botones enriquecidos. Si falla, hace fallback mostrando nuevamente el detalle del curso.

### 4. Opción 2: Capacitaciones para empresas

Este flujo registra leads empresariales.

Datos solicitados:

- nombre de la empresa,
- CUIT,
- provincia,
- correo de contacto,
- necesidades de formación.

Validaciones actuales:

- nombre de empresa sin números,
- CUIT con solo números,
- provincia dentro del listado argentino admitido,
- correo con formato básico válido.

Luego el bot permite:

- confirmar,
- ver datos,
- editar campos,
- volver al menú principal.

#### Al confirmar una solicitud empresarial

El sistema:

- guarda/actualiza datos del contacto en Firestore,
- etiqueta comercialmente el lead como `lead_empresa`,
- envía correo de confirmación al usuario si el correo es válido,
- envía correos internos a Cursala,
- dispara notificación de primer contacto si todavía no se había enviado,
- devuelve al usuario un resumen y luego lo deja volver al menú principal.

### 5. Opción 3: Quiero capacitar

Este flujo está pensado para personas interesadas en postularse como profesionales/docentes.

Datos solicitados:

- nombre y apellido,
- nacionalidad,
- DNI,
- descripción del curso que quiere dictar.

Luego muestra una revisión de perfil con acciones para:

- continuar,
- editar nombre,
- editar nacionalidad,
- editar DNI,
- editar descripción,
- volver al menú principal.

#### Carga de CV

Después de confirmar, el bot envía un link de Google Drive definido en constante (`CV_UPLOAD_URL`) para que el usuario cargue su CV. El usuario debe responder `LISTO` para finalizar.

#### Al confirmar la postulación

El sistema:

- guarda un registro local en `profesionales_interesados.json`,
- guarda/actualiza el lead en Firestore,
- etiqueta comercialmente el lead como `lead_profesional`,
- notifica internamente si corresponde,
- devuelve un resumen completo,
- regresa al menú principal.

### 6. Opción 4: Quiero hablar con un asesor

Este flujo bifurca en dos caminos:

1. Empresa
2. Persona física

#### Asesoría para empresa

Solicita:

- nombre de la empresa,
- correo,
- email alternativo,
- motivo de la consulta.

Luego muestra una revisión y permite:

- confirmar y enviar,
- editar cada campo,
- volver al menú principal.

Al confirmar:

- guarda un registro local en `asesor_consultas.json`,
- guarda/actualiza el lead en Firestore,
- etiqueta el lead como `lead_asesoria_empresa`,
- envía correos de confirmación e internos,
- muestra la lista de asesores disponibles,
- devuelve al menú principal.

#### Asesoría para persona física

Solicita:

- nombre completo,
- DNI,
- teléfono,
- correo,
- motivo.

Después muestra una revisión y permite:

- confirmar y enviar,
- editar datos.

Al confirmar:

- guarda un registro local en `asesor_consultas.json`,
- guarda/actualiza el lead en Firestore,
- etiqueta el lead como `lead_asesoria_persona`,
- envía correos al usuario e internos,
- muestra la lista de asesores disponibles,
- vuelve al menú principal.

### 7. Respuestas configurables adicionales

Si el usuario ingresa una opción numérica que existe en `menu_config["responses"]` y no está siendo manejada por un flujo especial, el bot responde con el texto configurado y habilita un modo de retorno simple con `0`.

### 8. Texto libre y fallback con Gemini

Cuando el mensaje no coincide con un flujo estructurado:

- el bot intenta detectar intereses por nombre de curso mencionado,
- si Gemini está habilitado, genera una respuesta conversacional,
- si no puede resolver, muestra un mensaje de ayuda y reexpone el menú principal.

#### Qué hace Gemini en este proyecto

Gemini se usa como fallback conversacional, no como motor principal del menú.

Se le pasa contexto sobre:

- catálogo de cursos,
- curso actual si el usuario está dentro de un detalle,
- historial reciente de conversación,
- reglas personalizadas definidas en `gemini_prompt_rules`.

Reglas importantes del prompt actual:

- responder como asistente de Cursala,
- mantener tono profesional y cercano,
- no inventar datos inciertos,
- derivar a asesor solo para precio, fechas o inscripción concreta,
- recomendar cursos cuando tenga suficiente contexto.

## Persistencia y trazabilidad

### Sesión en memoria

Cada número tiene una sesión con estado, incluyendo:

- flags de navegación,
- `pending_action`,
- curso actual,
- datos temporales de empresa/profesional/asesor,
- historial breve de Gemini,
- nombre de usuario,
- marca de última interacción.

Hay un timeout de inactividad de 300 segundos. Si se supera, el flujo se reinicia y se limpia parte del contexto de sesión.

### Firestore

Cuando está configurado, el bot persiste un perfil por número normalizado en la colección definida por `FIRESTORE_COLLECTION`.

Información que puede guardar:

- teléfono normalizado,
- nombre,
- nombre normalizado,
- provincia inferida por código de área,
- intereses detectados,
- etiquetas de interés,
- indicadores de eventos,
- información de formularios,
- flags de notificación enviada,
- etiqueta comercial del lead,
- código de contacto.

### Inferencia de provincia

El bot intenta inferir provincia argentina a partir del número telefónico usando una tabla interna de códigos de área. Si no puede inferirla, marca provincia como `Desconocida`.

## Integración de correo

El envío de correos se realiza por Brevo desde `email_service.py`.

### Tipos de correo utilizados

- Confirmación al usuario cuando completa formularios y hay correo válido.
- Notificación interna al equipo de Cursala ante nuevos contactos o eventos.
- Notificación única de primer contacto, evitando duplicados mediante una marca persistida en Firestore.

### Plantillas

Las plantillas están en `templates_email.py` y actualmente incluyen:

- correo de bienvenida,
- notificación de registro/evento con datos tabulados.

### Script de prueba

`test_email.py` permite validar la configuración de Brevo y enviar un correo de prueba a una dirección destino.

## Modo Admin

El modo Admin se activa por chat de WhatsApp.

### Requisitos para entrar

- el mensaje debe provenir del número configurado en `ADMIN_NUMBER`,
- el usuario debe escribir `admin`,
- luego debe ingresar la contraseña `ADMIN_KEY`.

Si el número no coincide, el bot responde `No autorizado`.

### Menú Admin actual

Opciones actuales:

1. Ver menú actual
2. Modificar saludo
3. Editar opción
4. Agregar opción
5. Modificar respuesta
6. Gestionar catálogo de cursos
7. Gestionar asesores y vendedores
8. Deshacer cambio
9. Desactivar admin
10. Gestionar backups
11. Notificaciones por email
12. Revisión
13. Administración de contactos
14. Prompts de respuesta (Gemini)
0. Volver al menú principal

### 1. Ver menú actual

Muestra el menú principal actual para verificar cómo lo ve el usuario final.

### 2. Modificar saludo

Permite reemplazar el texto de `greeting` del menú.

### 3. Editar opción

Permite elegir una opción existente del menú principal y modificar su texto visible.

### 4. Agregar opción

Permite agregar una nueva opción al menú principal definiendo:

- título de la opción,
- respuesta asociada.

La nueva opción se guarda con el siguiente ID disponible.

### 5. Modificar respuesta

Permite editar el texto de una respuesta existente dentro de `responses`.

### 6. Gestionar catálogo de cursos

Este submódulo administra los cursos configurados.

Permite:

- agregar curso,
- eliminar curso,
- editar curso,
- listar cursos.

#### Agregar curso

Solicita:

- nombre,
- link del curso,
- link PDF/temario.

Luego permite confirmar o editar antes de guardar. El curso queda asociado por defecto al vendedor `1` si no se configura otra cosa.

#### Editar curso

Permite seleccionar un curso y editar:

- nombre,
- descripción,
- link web,
- link de descarga.

#### Eliminar curso

Permite seleccionar un curso, confirmar eliminación y luego reorganiza los IDs para mantener secuencia correlativa.

### 7. Gestionar asesores y vendedores

Este módulo administra la entidad `vendedores`, que además se usa como fuente para mostrar asesores al usuario.

Permite:

- ver vendedores,
- agregar vendedor,
- eliminar vendedor,
- editar vendedor,
- asignar cursos a vendedor,
- ver asignaciones actuales.

#### Datos de vendedor

Cada vendedor maneja:

- nombre,
- apellido,
- correo,
- teléfono.

#### Asignación de cursos

El sistema soporta asignaciones mediante `vendedor_id` y `vendedor_ids`. Si un curso no tiene vendedores definidos y existe al menos uno cargado, el sistema puede tomar el primero como fallback.

### 8. Deshacer cambio

Existe un historial básico de cambios en sesión (`change_history`).

Importante: hoy esta opción informa el último cambio registrado, pero no constituye un rollback completo de la configuración. Es un deshacer informativo/parcial, no una reversión transaccional total del estado.

### 9. Desactivar admin

Sale del modo Admin y devuelve al flujo normal del bot.

### 10. Gestionar backups

El sistema soporta backups del menú.

Funciones implementadas en código:

- crear backup timestamped de `menu_config.json`,
- listar backups,
- restaurar backup.

Los backups se guardan en `menu_backups`.

### 11. Notificaciones por email

El panel Admin incluye un menú para gestionar:

- estado activo/inactivo,
- destinatario,
- asunto,
- texto de introducción.

Estos valores viven en `menu_config["email_notificacion_admin"]`.

### 12. Revisión

Muestra información operativa útil para diagnóstico:

- `APP_VERSION`,
- servicio runtime,
- revisión de deploy,
- configuración de deploy,
- versión de menú,
- fecha y hora del último cambio de menú.

### 13. Administración de contactos

Este módulo ayuda a operar Firestore y cargas históricas.

Opciones actuales:

1. Ver formato JSON esperado
2. Ver instrucciones para importar backup
3. Ver reglas de importación
4. Subir CSV por WhatsApp
5. Ver contactos guardados

#### Importación por JSON

Se documenta el formato esperado para importar contactos a Firestore mediante endpoint HTTP.

#### Reglas de importación

El importador aplica estas reglas:

- si no hay teléfono válido, el contacto se omite,
- si hay teléfono, se guarda aunque falten otros datos,
- se deduplica por teléfono dentro del payload,
- si el teléfono ya existe en Firestore, no se sobreescribe,
- se aceptan campos opcionales como nombre, intereses, etiqueta y `extra_fields`.

#### Subida CSV por WhatsApp

El admin puede enviar un archivo CSV como documento por el chat. El bot:

- valida que sea CSV,
- descarga el archivo desde Meta usando el `media_id`,
- parsea encabezados flexibles,
- detecta teléfonos desde varias columnas posibles,
- importa los contactos a Firestore,
- va informando progreso por porcentaje,
- muestra resumen final de importación.

#### Ver contactos guardados

Lista los contactos más recientes o disponibles desde Firestore, mostrando:

- nombre,
- teléfono,
- etiqueta comercial.

### 14. Prompts de respuesta (Gemini)

Permite administrar reglas de negocio que se agregan al prompt de Gemini.

Acciones actuales:

- ver reglas activas,
- agregar regla,
- editar regla,
- eliminar regla.

Las reglas se persisten en `menu_config.json`.

## Endpoints HTTP expuestos

### `GET /version`

Devuelve:

- versión de la app,
- `phone_number_id`,
- si el `VERIFY_TOKEN` está cargado,
- configuración template de curso.

### `GET /admin/firestore/users`

Permite consultar usuarios de Firestore con filtros por:

- provincia,
- interés,
- límite.

Requiere header `x-admin-key`.

### `GET /admin/firestore/users/{telefono}`

Devuelve el documento asociado a un número concreto. Requiere header `x-admin-key`.

### `POST /admin/firestore/contacts/import`

Importa contactos a Firestore a partir de un payload JSON. Requiere header `x-admin-key`.

### Webhook de WhatsApp

El proyecto está preparado para operar como webhook de Meta dentro de `main.py`, procesando mensajes entrantes y derivándolos al motor de usuario o al motor admin según el número y el estado de sesión.

## Envío de mensajes a WhatsApp

Todo envío usa WhatsApp Cloud API por `requests` hacia el endpoint:

- `https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages`

Tipos de envío manejados por el sistema:

- texto simple,
- CTAs o mensajes enriquecidos para cursos cuando la integración está disponible,
- descarga de archivos adjuntos desde Meta para el caso de CSV enviado al admin.

## Archivos de salida local generados por el sistema

Según el flujo, el bot puede generar o mantener:

- `profesionales_interesados.json`: postulaciones de personas que quieren capacitar.
- `asesor_consultas.json`: consultas derivadas a asesor.
- `menu_backups/*.json`: respaldos del menú cuando se usan backups.

## Script auxiliar de envío manual

`enviar.py` permite disparar mensajes por WhatsApp Cloud API desde línea de comandos a:

- un número puntual con `--to`,
- una lista de números con `--numbers-file`.

Es útil para pruebas operativas o campañas controladas.

## Despliegue

El `Dockerfile` usa:

- `python:3.11-slim`,
- instala dependencias desde `requirements.txt`,
- expone puerto `8080`,
- arranca con `uvicorn main:app --host 0.0.0.0 --port 8080`.

También fija por defecto:

- `FIREBASE_CREDENTIALS_PATH=/secrets/firebase.json`

Pensado para despliegue donde la credencial se monte como secreto.

## Limitaciones y observaciones actuales

- La sesión principal vive en memoria. Si el proceso reinicia, ese estado se pierde.
- El modo `Deshacer cambio` del Admin no implementa rollback real de configuración completa.
- Los teléfonos `N/A` en vendedores impiden generar enlaces directos válidos de WhatsApp.
- Algunas funciones administrativas dependen fuertemente de que Firestore esté operativo.
- El fallback de Gemini solo funciona si la integración está correctamente configurada y habilitada.

## Mantenimiento obligatorio del README

Este archivo debe actualizarse siempre que ocurra cualquiera de estos cambios:

- se agrega o elimina una opción del menú principal,
- cambia un flujo conversacional,
- cambia la lógica de captura de datos,
- se agregan nuevos cursos,
- se modifica la lógica del modo Admin,
- se agregan endpoints,
- cambia la integración con Firestore, Brevo o Gemini,
- cambia una validación de negocio,
- cambia el proceso de despliegue.

### Regla de mantenimiento

Toda modificación funcional del bot debe incluir también la actualización de este README dentro del mismo cambio de trabajo.

## Checklist para futuras actualizaciones del manual

Antes de cerrar cualquier cambio del bot, verificar:

1. Si cambió el flujo del usuario, actualizar la sección correspondiente.
2. Si cambió el modo Admin, actualizar sus opciones y comportamiento.
3. Si cambió `menu_config.json`, reflejar nuevas opciones, cursos o reglas.
4. Si cambió integración externa, actualizar variables de entorno y operación.
5. Si cambió persistencia o trazabilidad, actualizar Firestore/archivos locales.
6. Si cambió despliegue, actualizar Docker y notas operativas.

## Estado documental actual

Este README fue actualizado para reflejar el comportamiento observable en el código actual del repositorio al 26/03/2026.