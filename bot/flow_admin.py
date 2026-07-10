"""bot/flow_admin.py — Maquina de estados del administrador.

Incluye:
- Edicion conversacional de menu/cursos/vendedores/prompts.
- Herramientas de administracion de contactos (import/export).
- Procesamiento de documentos CSV/XLSX enviados por WhatsApp.

Las tareas pesadas (por ejemplo exportaciones grandes) se ejecutan en background.
"""
from bot.config import logger, ADMIN_KEY
from bot.utils import (
    normalize_number,
    normalize_menu_command,
    parse_full_name,
    parse_csv_contacts_file,
    parse_xlsx_contacts_file,
    build_upload_progress_message,
    validar_correo,
    validar_telefono,
)
from bot.database import (
    firestore_db,
    upsert_user_profile_firestore,
    get_all_distinct_tags_from_firestore,
    get_contact_label_counts_from_firestore,
    get_contacts_by_label,
    get_all_contacts_from_firestore,
    build_contacts_saved_list_message,
    export_all_contacts_to_csv_bytes,
    export_all_contacts_to_xlsx_bytes,
)
from bot.state_manager import get_admin_session, reset_user_flow
from bot.menus import (
    menu_config,
    save_menu_config,
    create_menu_backup,
    list_backups,
    restore_menu_backup,
    reorganize_course_ids,
    get_course_vendor_ids,
    get_gemini_prompt_rules,
    build_courses_menu,
    build_admin_menu,
    get_unified_courses,
    build_courses_edit_menu,
    build_vendor_menu,
    build_vendor_list_message,
    build_vendor_edit_fields_menu,
    build_vendor_courses_assignment_message,
    build_vendor_courses_toggle_message,
    build_vendor_add_confirmation,
    build_backup_menu,
    build_email_admin_menu,
    build_runtime_revision_message,
    build_prompt_rules_admin_menu,
    build_prompt_rules_list_message,
    build_prompt_rules_select_message,
    build_broadcast_menu,
    build_broadcast_msg_type_menu,
    build_broadcast_tag_list_message,
    build_recovery_export_labels_menu,
    execute_broadcast_send,
    enviar_menu_principal_lista,
    enviar_menu_admin_lista,
    enviar_menu_cursos_edit_lista,
    enviar_menu_contacts_admin_lista,
    build_recovery_contacts_menu,
    enviar_menu_recovery_contacts_lista,
)
from bot.whatsapp_api import (
    enviar_respuesta,
    download_whatsapp_media_content,
    upload_media_to_meta,
    enviar_documento_whatsapp,
)
from bot.flow_user import manejar_usuario, _bg


# ============================================================
# PROCESAMIENTO DE DOCUMENTOS (CSV / EXCEL)
# ============================================================

_ACCEPTED_MIME_TYPES = {
    "text/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}

_ACCEPTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


async def _is_accepted_contacts_file(mime_type: str, filename: str) -> bool:
    for mt in _ACCEPTED_MIME_TYPES:
        if mime_type.startswith(mt):
            return True
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in _ACCEPTED_EXTENSIONS


async def process_admin_csv_document_message(from_number: str, msg: dict) -> bool:
    """Maneja un documento CSV o Excel enviado por el admin. Retorna True si fue procesado."""
    session = get_admin_session(from_number)
    if session.get("pending_action") != "contacts_admin_waiting_csv":
        return False

    doc_info = msg.get("document", {})
    mime_type = doc_info.get("mime_type", "")
    filename = doc_info.get("filename", "") or ""
    media_id = doc_info.get("id", "")

    if not await _is_accepted_contacts_file(mime_type, filename):
        await enviar_respuesta(
            from_number,
            "⚠️ El archivo enviado no es compatible.\n\n"
            "Formatos aceptados: *CSV* o *Excel (.xlsx)*\n\n"
            "0. Cancelar"
        )
        return True

    if not media_id:
        await enviar_respuesta(from_number, "⚠️ No se pudo leer el archivo. Intentá enviarlo nuevamente.")
        return True

    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    is_xlsx = ext in (".xlsx", ".xls") or mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    await enviar_respuesta(from_number, f"⏳ Descargando y procesando el archivo...")

    ok, content_bytes, err_msg = await download_whatsapp_media_content(media_id)
    if not ok or not content_bytes:
        await enviar_respuesta(
            from_number,
            f"❌ No se pudo descargar el archivo.\n"
            f"Detalle: {err_msg}\n\n"
            "Intentá enviarlo nuevamente."
        )
        return True

    if is_xlsx:
        parsed_contacts = parse_xlsx_contacts_file(content_bytes)
    else:
        parsed_contacts = parse_csv_contacts_file(content_bytes)

    if not parsed_contacts:
        await enviar_respuesta(
            from_number,
            "⚠️ No se encontraron contactos válidos en el archivo.\n\n"
            "Revisá que el archivo tenga una columna de teléfono "
            "(Numero / phone / whatsapp_number / telefono)."
        )
        session["pending_action"] = "contacts_admin_menu"
        await enviar_menu_contacts_admin_lista(from_number)
        return True

    total = len(parsed_contacts)
    await enviar_respuesta(from_number, f"📊 {total} contacto(s) encontrado(s). Importando...")

    async def on_progress(processed: int, total_c: int, percent: int) -> None:
        if percent in (25, 50, 75, 100): # type: ignore
            await enviar_respuesta(from_number, f"⏳ Importando... {percent}% ({processed}/{total_c})")

    # La funcionalidad de importación fue deshabilitada temporalmente.
    # Se debe reimplementar si es necesaria.
    result = {
        "summary": {"importados": 0, "omitidos_duplicados": 0, "omitidos_ya_registrados": 0, "omitidos_sin_telefono": 0, "fallidos": total}
    }

    summary_data = result.get("summary", {})
    importados = summary_data.get("importados", 0)
    omitidos_dup = summary_data.get("omitidos_duplicados", 0) + summary_data.get("omitidos_ya_registrados", 0)
    sin_telefono = summary_data.get("omitidos_sin_telefono", 0)
    fallidos = summary_data.get("fallidos", 0)

    summary = (
        f"✅ *IMPORTACIÓN COMPLETADA*\n\n"
        f"Total en archivo: {total}\n"
        f"✅ Importados: {importados}\n"
        f"⏭ Ya existían / duplicados: {omitidos_dup}\n"
        f"⚠️ Sin teléfono válido: {sin_telefono}\n"
        f"❌ Fallidos: {fallidos}"
    )
    failures = result.get("failures_preview", [])
    if failures:
        summary += "\n\nPrimeros errores:\n" + "\n".join(str(f) for f in failures[:3])

    await enviar_respuesta(from_number, summary)
    session["pending_action"] = "contacts_admin_menu"
    await enviar_menu_contacts_admin_lista(from_number)
    return True


def _parse_date_range_input(raw_text: str):
    """Parsea rango de fechas para exportación.

    Formatos válidos:
    - YYYY-MM-DD
    - YYYY-MM-DD a YYYY-MM-DD
    """
    from datetime import datetime

    text = " ".join(str(raw_text or "").strip().split())
    if not text:
        return None, None, "⚠️ Ingresá una fecha. Ej: 2026-04-12"

    parts = [p.strip() for p in text.lower().split(" a ") if p.strip()]
    if len(parts) == 1:
        date_from = parts[0]
        date_to = parts[0]
    elif len(parts) == 2:
        date_from, date_to = parts
    else:
        return None, None, "⚠️ Formato inválido. Usá: YYYY-MM-DD o YYYY-MM-DD a YYYY-MM-DD"

    try:
        d_from = datetime.strptime(date_from, "%Y-%m-%d")
        d_to = datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        return None, None, "⚠️ Fecha inválida. Formato requerido: YYYY-MM-DD"

    if d_from > d_to:
        return None, None, "⚠️ Rango inválido: la fecha inicial no puede ser mayor a la final."

    return date_from, date_to, ""


async def _export_contacts_and_send(
    phone: str,
    *,
    title_hint: str,
    label_filter: str = "",
    date_from: str = "",
    date_to: str = "",
) -> None:
    """Genera y envía Excel de contactos con filtros opcionales.""" # type: ignore
    from datetime import datetime
    async def _worker() -> None:
        try:
            xlsx_bytes, count = export_all_contacts_to_xlsx_bytes(
                limit=5000,
                label_filter=label_filter or None,
                date_from=date_from or None,
                date_to=date_to or None,
            )
        except Exception as exc:
            logger.error("export_all_contacts_to_xlsx_bytes falló: %s", exc)
            await enviar_respuesta(phone, f"❌ Error generando el Excel:\n{str(exc)[:300]}")
            return

        if count == 0:
            await enviar_respuesta(phone, "⚠️ No hay contactos para ese filtro.")
            return

        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
        safe_hint = title_hint.replace(" ", "_").replace("/", "-")
        fname = f"contactos_{safe_hint}_{ts}.xlsx"
        mid = await upload_media_to_meta(
            xlsx_bytes,
            fname,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        if not mid:
            await enviar_respuesta(phone, "❌ No se pudo subir el archivo a Meta. Intentá de nuevo más tarde.")
            return

        enviado = await enviar_documento_whatsapp(phone, mid, fname, caption=f"📊 {count} contactos")
        if enviado:
            await enviar_respuesta(phone, f"✅ Excel listo: *{fname}*\n{count} contactos exportados.")
        else:
            await enviar_respuesta(phone, "❌ Error enviando el documento. Revisá los logs.")

    await _worker()


async def _download_and_send_template(phone: str) -> None:
    """Genera y envía plantilla Excel para que el admin la complete con contactos."""
    async def _worker() -> None: # type: ignore
        try:
            from bot.database import generate_contacts_template_excel
            template_bytes = generate_contacts_template_excel()
        except Exception as exc:
            logger.error("Error generando plantilla: %s", exc)
            await enviar_respuesta(phone, f"❌ Error generando plantilla:\n{str(exc)[:300]}")
            return

        fname = "plantilla_contactos.xlsx"
        mid = await upload_media_to_meta(
            template_bytes,
            fname,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        if not mid:
            await enviar_respuesta(phone, "❌ No se pudo subir la plantilla. Intentá de nuevo más tarde.")
            return

        enviado = await enviar_documento_whatsapp(
            phone,
            mid,
            fname,
            caption="📋 Plantilla de contactos. Completá y enviá el archivo para que se carguen los datos.",
        )
        if enviado:
            await enviar_respuesta(phone, "✅ Plantilla enviada. Completá los datos y enviá el archivo cuando esté lista.")
        else:
            await enviar_respuesta(phone, "❌ Error enviando la plantilla. Revisá los logs.")

    await _worker()



# ============================================================
# MOTOR DE FLUJO ADMINISTRATIVO
# ============================================================

async def manejar_admin(from_number: str, text_body: str):
    """Procesá mensajes del administrador; delega al flujo usuario cuando admin no está activo."""
    from bot.flow_user import manejar_usuario
    from bot.api_webhook import obtener_cursos_actualizados
    import asyncio
    session = get_admin_session(from_number)
    text = text_body.strip()
    text_lower = text.lower()

    if session["awaiting_admin_password"]:
        if text == ADMIN_KEY:
            session["active"] = True
            session["awaiting_admin_password"] = False
            session["pending_action"] = None
            session["in_response_menu"] = False
            await enviar_menu_admin_lista(from_number)
        else:
            session["awaiting_admin_password"] = False # type: ignore
            await enviar_respuesta(from_number, "❌ Contraseña incorrecta.")
            await enviar_menu_principal_lista(from_number)
        return

    if not session["active"]:
        await manejar_usuario(from_number, text_body)
        return

    if text_lower in ["hola", "menu", "inicio"]:
        session["active"] = False # type: ignore
        session["awaiting_admin_password"] = False
        reset_user_flow(session)
        await enviar_menu_principal_lista(from_number)
        return

    # ============================================================
    # FLUJOS DE CURSOS
    # ============================================================

    if session["pending_action"] == "awaiting_course_name":
        if text == "0":
            session["pending_action"] = "courses_edit_menu"
            session["temp_course_data"] = {}
            await enviar_menu_cursos_edit_lista(from_number)
            return

        session["temp_course_data"]["nombre"] = text_body
        await enviar_respuesta(from_number, "✅ Nombre ingresado.\n\n📝 Ahora ingresa el link del curso (sitio web):\n\n0. Volver al menú admin")
        session["pending_action"] = "awaiting_course_link"
        return

    if session["pending_action"] == "awaiting_course_link":
        if text == "0":
            session["pending_action"] = "courses_edit_menu"
            await enviar_respuesta(from_number, "📝 ¿Cuál es el nombre del curso?\n\n0. Volver al menú admin")
            return
        session["temp_course_data"]["link_web"] = text_body
        await enviar_respuesta(from_number, "✅ Link del curso ingresado.\n\n📄 Ahora ingresa el link del PDF del programa:\n\n0. Volver al menú admin")
        session["pending_action"] = "awaiting_course_pdf"
        return

    if session["pending_action"] == "awaiting_course_pdf":
        if text == "0":
            session["pending_action"] = "courses_edit_menu" # type: ignore
            await enviar_respuesta(from_number, "📝 Ingresa el link del curso (sitio web):\n\n0. Volver al menú admin")
            return
        session["temp_course_data"]["link_descarga"] = text_body
        resumen = (
            " RESUMEN DE DATOS INGRESADOS\n\n"
            f" Nombre: {session['temp_course_data']['nombre']}\n"
            f" Link Curso: {session['temp_course_data']['link_web']}\n"
            f" Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
            "¿Deseas continuar?\n1. ACEPTAR\n2. EDITAR\n\n0. Volver al menú admin\n\nEscribe tu opción:"
        )
        await enviar_respuesta(from_number, resumen)
        session["pending_action"] = "confirm_course_data"
        return

    if session["pending_action"] == "confirm_course_data":
        if text == "1":
            cursos = get_unified_courses()
            max_id = max([int(k) for k in cursos.keys()]) if cursos else 0
            nuevo_id = str(max_id + 1)
            menu_config["cursos"][nuevo_id] = {
                "nombre": session["temp_course_data"]["nombre"],
                "descripcion": session["temp_course_data"].get("descripcion", ""),
                "link_web": session["temp_course_data"]["link_web"],
                "link_descarga": session["temp_course_data"]["link_descarga"],
                "vendedor_id": "1",
            }
            save_menu_config(menu_config)
            await enviar_respuesta(
                from_number,
                f"✅ Curso '{session['temp_course_data']['nombre']}' agregado con ID {nuevo_id}."
            )
            session["pending_action"] = "courses_edit_menu"
            session["temp_course_data"] = {}
            await enviar_menu_cursos_edit_lista(from_number)
        elif text == "2":
            await enviar_respuesta(from_number, "✏️ ¿QUÉ DESEAS EDITAR?\n\n1. ✏️ Nombre\n2. ✏️ Link Curso\n3. ✏️ Link PDF\n\n0. Volver\n\nEscribe tu opción:")
            session["pending_action"] = "courses_edit_menu"
        elif text == "0":
            session["pending_action"] = None
            session["temp_course_data"] = {}
            await enviar_menu_cursos_edit_lista(from_number)
        else:
            await enviar_respuesta(from_number, "❌ Opción inválida. Usa 1 o 2.")
        return

    if session["pending_action"] == "edit_course_field_add":
        fields = {"1": ("nombre", "Nombre del curso"), "2": ("link_web", "Link del curso"), "3": ("link_descarga", "Link del PDF")}
        if text == "0":
            resumen = (
                "📋 RESUMEN DE DATOS INGRESADOS\n\n"
                f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
                f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
                f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
                "¿Deseas continuar?\n1. ✅ ACEPTAR\n2. ✏️ EDITAR\n\nEscribe tu opción:"
            )
            await enviar_respuesta(from_number, resumen)
            session["pending_action"] = "confirm_course_data"
        elif text in fields:
            field_key, field_name = fields[text]
            session["temp_field"] = field_key
            await enviar_respuesta(from_number, f"📝 Ingresa el nuevo valor para {field_name}:\n\n0. Volver al menú admin")
            session["pending_action"] = "awaiting_field_value_add"
        else:
            await enviar_respuesta(from_number, "❌ Opción inválida. Intenta de nuevo.")
        return

    if session["pending_action"] == "awaiting_field_value_add":
        if text == "0":
            session["pending_action"] = "edit_course_field_add"
            session["temp_field"] = None
            await enviar_respuesta(from_number, "✏️ ¿QUÉ DESEAS EDITAR?\n\n1. ✏️ Nombre\n2. ✏️ Link Curso\n3. ✏️ Link PDF\n\n0. Volver\n\nEscribe tu opción:")
            return
        field = session["temp_field"]
        session["temp_course_data"][field] = text_body
        resumen = ( # type: ignore
            "📋 RESUMEN DE DATOS INGRESADOS\n\n"
            f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
            f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
            f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
            "¿Deseas continuar?\n1. ✅ ACEPTAR\n2. ✏️ EDITAR\n\nEscribe tu opción:"
        )
        await enviar_respuesta(from_number, resumen)
        session["pending_action"] = "confirm_course_data"
        session["temp_field"] = None
        return

    if session["pending_action"] == "delete_course":
        if text == "0":
            session["pending_action"] = "courses_edit_menu"
            await enviar_menu_cursos_edit_lista(from_number)
            return
        cursos = get_unified_courses()
        if text in cursos:
            curso = cursos[text]
            session["temp_option"] = text
            await enviar_respuesta(
                from_number,
                f"⚠️ ¿Estás seguro de eliminar '{curso['nombre']}'?\n\n1. ✅ Sí\n0. ❌ No\n\nEscribe tu opción:"
            )
            session["pending_action"] = "confirm_delete_course"
            return
        await enviar_respuesta(from_number, "❌ Curso no encontrado.\n\n" + build_courses_menu())
        return

    if session["pending_action"] == "confirm_delete_course":
        if text == "1":
            curso_id = session["temp_option"]
            curso = get_unified_courses()[curso_id]
            del menu_config["cursos"][curso_id]
            reorganize_course_ids(menu_config)
            await enviar_respuesta(
                from_number,
                f"✅ Curso '{curso['nombre']}' eliminado.\n\nℹ️ Los IDs se han reorganizado automáticamente."
            )
        elif text == "0":
            await enviar_respuesta(from_number, "❌ Eliminación cancelada.")
        else:
            await enviar_respuesta(from_number, "Opción inválida. Usa 1 o 0.")
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "edit_course_select":
        if text == "0":
            session["pending_action"] = "courses_edit_menu"
            await enviar_menu_cursos_edit_lista(from_number)
            return
        cursos = get_unified_courses()
        if text in cursos:
            session["current_course"] = text
            curso = cursos[text]
            detalle = (
                f"📝 CONTENIDO ACTUAL DEL CURSO\n\n"
                f"ID: {text}\nNombre: {curso.get('nombre', '')}\n"
                f"Descripción: {curso.get('descripcion', '')}\n"
                f"Link web: {curso.get('link_web', '')}\nLink descarga: {curso.get('link_descarga', '')}\n\n"
                "1. Editar\n2. Volver"
            )
            await enviar_respuesta(from_number, detalle)
            session["pending_action"] = "edit_course_overview"
            return

        await enviar_respuesta(from_number, "❌ Curso no encontrado.\n\n" + build_courses_menu())
        return

    if session["pending_action"] == "edit_course_overview":
        if text == "1":
            curso_id = session.get("current_course")
            curso = get_unified_courses().get(curso_id, {})
            menu_edit = f"✏️ EDITAR CURSO: {curso.get('nombre', 'N/A')}\n\n1. Nombre\n2. Descripción\n3. Link web\n4. Link descarga\n\n0. Volver\n\nElegí qué campo querés editar:"
            await enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
        elif text == "2":
            session["pending_action"] = None
            session["current_course"] = None
            session["temp_field"] = None
            session["temp_course_data"].pop("edit_pending_value", None)
            await enviar_menu_cursos_edit_lista(from_number)
        else:
            await enviar_respuesta(from_number, "❌ Opción inválida. Escribí 1 para editar o 2 para volver.")
        return

    if session["pending_action"] == "edit_course_field":
        fields = {"1": "nombre", "2": "descripcion", "3": "link_web", "4": "link_descarga"}
        field_name = {"nombre": "Nombre", "descripcion": "Descripción", "link_web": "Link web", "link_descarga": "Link descarga"}
        if text == "0":
            curso_id = session.get("current_course")
            curso = get_unified_courses().get(curso_id, {})
            detalle = (
                f"📝 CONTENIDO ACTUAL DEL CURSO\n\nID: {curso_id}\nNombre: {curso.get('nombre', '')}\n"
                f"Descripción: {curso.get('descripcion', '')}\n"
                f"Link web: {curso.get('link_web', '')}\nLink descarga: {curso.get('link_descarga', '')}\n\n"
                "1. Editar\n2. Volver"
            )
            await enviar_respuesta(from_number, detalle)
            session["pending_action"] = "edit_course_overview"
        elif text in fields:
            curso_id = session.get("current_course")
            curso = get_unified_courses().get(curso_id, {})
            session["temp_field"] = fields[text] # type: ignore
            campo = session["temp_field"]
            valor_actual = curso.get(campo, "")
            await enviar_respuesta(
                from_number,
                f"Campo: {field_name.get(campo, campo)}\nValor actual: {valor_actual}\n\nIngresá el nuevo valor:"
            )
            session["pending_action"] = "awaiting_field_value"
        else:
            await enviar_respuesta(from_number, "❌ Opción inválida. Elegí 1, 2, 3, 4 o 0.")
        return

    if session["pending_action"] == "awaiting_field_value":
        session["temp_course_data"]["edit_pending_value"] = text_body
        curso_id = session.get("current_course")
        field = session.get("temp_field")
        field_name = {"nombre": "Nombre", "descripcion": "Descripción", "link_web": "Link web", "link_descarga": "Link descarga"}
        curso = get_unified_courses().get(curso_id, {})
        valor_actual = curso.get(field, "")
        await enviar_respuesta(
            from_number,
            f"✏️ Confirmar actualización\n\nCampo: {field_name.get(field, field)}\n"
            f"Valor actual: {valor_actual}\nNuevo valor: {text_body}\n\n1. Enviar\n2. Volver"
        )
        session["pending_action"] = "confirm_course_field_update"
        return

    if session["pending_action"] == "confirm_course_field_update":
        if text == "1":
            curso_id = session.get("current_course")
            field = session.get("temp_field")
            nuevo_valor = session["temp_course_data"].get("edit_pending_value", "")
            menu_config["cursos"][curso_id][field] = nuevo_valor
            save_menu_config(menu_config)
            await enviar_respuesta(from_number, "✅ Campo actualizado exitosamente.")
            session["pending_action"] = "courses_edit_menu"
            session["temp_field"] = None
            session["current_course"] = None
            session["temp_course_data"].pop("edit_pending_value", None)
            await enviar_menu_cursos_edit_lista(from_number)
        elif text == "2":
            curso_id = session.get("current_course") or ""
            curso = get_unified_courses().get(curso_id, {})
            menu_edit = f"✏️ EDITAR CURSO: {curso.get('nombre', 'N/A')}\n\n1. Nombre\n2. Descripción\n3. Link web\n4. Link descarga\n\n0. Volver\n\nElegí qué campo querés editar:"
            await enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
            session["temp_course_data"].pop("edit_pending_value", None)
        else:
            await enviar_respuesta(from_number, "❌ Opción inválida. Escribí 1 para enviar o 2 para volver.")
        return

    if session.get("pending_action") == "courses_edit_menu":
        if text == "0":
            session["pending_action"] = None
            await enviar_menu_admin_lista(from_number)
        elif text == "1":
            session["temp_course_data"] = {}
            await enviar_respuesta(from_number, "📝 AGREGAR NUEVO CURSO\n\n¿Cuál es el nombre del curso?\n\n0. Volver")
            session["pending_action"] = "awaiting_course_name"
        elif text == "2":
            await enviar_respuesta(from_number, "❌ Ingresa el número del curso a eliminar:\n\n" + build_courses_menu() + "\n0. Volver")
            session["pending_action"] = "delete_course"
        elif text == "3":
            await enviar_respuesta(from_number, "✏️ Ingresa el número del curso a editar:\n\n" + build_courses_menu() + "\n0. Volver")
            session["pending_action"] = "edit_course_select"
        elif text == "4":
            await enviar_respuesta(from_number, build_courses_menu())
        else:
            await enviar_menu_cursos_edit_lista(from_number)
        return

    # ============================================================
    # MENU PRINCIPAL ADMIN — DISPATCH
    # ============================================================

    if session["pending_action"] is None:
        if text == "0":
            session["active"] = False
            reset_user_flow(session)
            await enviar_menu_principal_lista(from_number, include_greeting=False)
            return

        if text == "1":
            await enviar_respuesta(from_number, "📋 Vista previa del menú principal:")
            await enviar_menu_principal_lista(from_number)
            return

        if text == "2":
            await enviar_respuesta(
                from_number,
                f"📝 MENSAJE ACTUAL:\n\n{menu_config['greeting']}\n\n✏️ Escribe el nuevo saludo:\n\n0. Volver al menú admin"
            )
            session["pending_action"] = "edit_greeting"
            return

        if text == "3":
            menu_str = "✏️ EDITAR OPCIÓN DEL MENÚ\n\n"
            for key in sorted(menu_config["options"].keys(), key=int):
                menu_str += f"{key}. {menu_config['options'][key]}\n"
            menu_str += f"\n¿Qué opción deseas editar? (1-{len(menu_config['options'])})\n0. Volver al menú admin"
            await enviar_respuesta(from_number, menu_str)
            session["pending_action"] = "edit_option_select"
            return

        if text == "4":
            await enviar_respuesta(from_number, "➕ AGREGAR NUEVA OPCIÓN\n\n¿Cuál es el título de la nueva opción?\n\n0. Volver al menú admin")
            session["pending_action"] = "add_option_title"
            return

        if text == "5":
            resp_str = "📝 EDITAR RESPUESTA\n\n"
            for key in sorted(menu_config["responses"].keys(), key=int):
                resp_str += f"{key}. {menu_config['responses'][key][:40]}...\n"
            resp_str += f"\n¿Qué respuesta deseas editar? (1-{len(menu_config['responses'])})\n0. Volver al menú admin"
            await enviar_respuesta(from_number, resp_str)
            session["pending_action"] = "edit_response_select"
            return

        if text == "6":
            await enviar_menu_cursos_edit_lista(from_number)
            session["pending_action"] = "courses_edit_menu"
            return

        if text == "7":
            await enviar_respuesta(from_number, build_vendor_menu())
            session["pending_action"] = "vendor_menu"
            return

        if text == "8":
            if session["change_history"]:
                ultimo_cambio = session["change_history"].pop()
                await enviar_respuesta(from_number, f"⏮️ Cambio deshecho:\n{ultimo_cambio}")
                await enviar_menu_admin_lista(from_number)
            else:
                await enviar_respuesta(from_number, "❌ No hay cambios para deshacer.")
                await enviar_menu_admin_lista(from_number)
            return

        if text == "9":
            session["active"] = False
            reset_user_flow(session)
            await enviar_respuesta(from_number, "✅ Admin desactivado.")
            await enviar_menu_principal_lista(from_number)
            return

        if text == "10":
            await enviar_respuesta(from_number, build_backup_menu(menu_config))
            session["pending_action"] = "backup_menu"
            return

        if text == "11":
            await enviar_respuesta(from_number, build_email_admin_menu(menu_config))
            session["pending_action"] = "email_admin_menu"
            return

        if text == "12":
            await enviar_respuesta(from_number, build_runtime_revision_message(menu_config))
            session["pending_action"] = "revision_info"
            return

        if text == "13":
            await enviar_menu_contacts_admin_lista(from_number)
            session["pending_action"] = "contacts_admin_menu"
            return

        if text == "14":
            await enviar_respuesta(from_number, build_prompt_rules_admin_menu(menu_config))
            session["pending_action"] = "prompt_rules_menu"
            return

        if text == "15":
            await enviar_respuesta(from_number, build_broadcast_menu())
            session["pending_action"] = "broadcast_menu"
            session["temp_broadcast"] = {}
            return
        
        if text == "16":
            await enviar_respuesta(from_number, "⏳ Refrescando catálogo desde la web...")
            async def _refresh_and_reply():
                try:
                    cursos_actualizados = await obtener_cursos_actualizados(force_refresh=True)
                    if cursos_actualizados:
                        await enviar_respuesta(from_number, "✅ Catálogo actualizado.\n\n" + build_courses_menu())
                    else:
                        # Esto ocurre si la API falla y no hay nada en el caché.
                        await enviar_respuesta(from_number, "❌ No se pudieron obtener los cursos. La API web podría no estar respondiendo.")
                except Exception as e:
                    await enviar_respuesta(from_number, f"❌ Error al refrescar cursos: {e}")
            asyncio.create_task(_refresh_and_reply())
            return

        await enviar_respuesta(from_number, "❌ Opción inválida.")
        await enviar_menu_admin_lista(from_number)
        return

    # ============================================================
    # SUB-FLUJOS
    # ============================================================

    if session["pending_action"] == "revision_info": # type: ignore
        session["pending_action"] = None
        await enviar_menu_admin_lista(from_number)
        return

    if session["pending_action"] == "contacts_admin_menu":
        if text == "0":
            session["pending_action"] = None
            await enviar_menu_admin_lista(from_number)
            return
        if text == "1":
            ejemplo = ( # type: ignore
                "*FORMATO JSON DE BACKUP*\n\n"
                "{\n  \"origen\": \"backup_whatsapp\",\n  \"evento_default\": \"importacion_backup\",\n"
                "  \"contactos\": [\n    {\"whatsapp_number\": \"5492615031839\"},\n"
                "    {\"phone\": \"+54 9 261 238 0499\", \"nombre\": \"Maria\", \"etiqueta_cliente\": \"interesado_empresa\"}\n"
                "  ]\n}\n\n"
                "Campo obligatorio por contacto: telefono (whatsapp_number / phone / telefono / numero)."
            )
            await enviar_respuesta(from_number, ejemplo)
            await enviar_menu_contacts_admin_lista(from_number)
            return
        if text == "2":
            instrucciones = ( # type: ignore
                "*IMPORTAR BACKUP A FIRESTORE*\n\n"
                "Endpoint: POST /admin/firestore/contacts/import\n"
                "Header requerido: x-admin-key\n"
                "Body: JSON con array 'contactos'\n\n"
                "PowerShell (ejemplo):\n"
                "$headers = @{ 'x-admin-key' = 'tu_clave_admin' }\n"
                "Invoke-RestMethod -Uri 'https://tuservidor.com/admin/firestore/contacts/import' -Headers $headers -Method Post"
            )
            await enviar_respuesta(from_number, instrucciones)
            await enviar_menu_contacts_admin_lista(from_number)
            return

        await enviar_respuesta(from_number, "⚠️ Opción no válida dentro de Contactos.")
        await enviar_menu_contacts_admin_lista(from_number)
        return

    if session["pending_action"] in ["backup_menu", "email_admin_menu", "prompt_rules_menu", "broadcast_menu", "vendor_menu"]:
        if session["pending_action"] == "backup_menu":
            if text == "1":
                filename = create_menu_backup(menu_config)
                await enviar_respuesta(from_number, f"✅ Backup creado exitosamente:\n`{filename}`")
                session["pending_action"] = None
                await enviar_menu_admin_lista(from_number)
                return
            if text == "2":
                await enviar_respuesta(from_number, "⚠️ Funcionalidad de restaurar en desarrollo.")
                session["pending_action"] = None
                await enviar_menu_admin_lista(from_number)
                return

        if text == "0": # Común a todos los submenús
            session["pending_action"] = None
            await enviar_menu_admin_lista(from_number)
        else:
            await enviar_respuesta(from_number, "⚠️ Opción no válida o en desarrollo.")
            await enviar_menu_admin_lista(from_number)
        return

    await enviar_respuesta(from_number, "❌ Opción no reconocida por el sistema de administración.")
    await enviar_menu_admin_lista(from_number)