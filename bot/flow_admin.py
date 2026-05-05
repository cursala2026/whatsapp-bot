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
    import_contacts_backup_to_firestore,
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
from bot.flow_user import manejar_usuario


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


def _is_accepted_contacts_file(mime_type: str, filename: str) -> bool:
    for mt in _ACCEPTED_MIME_TYPES:
        if mime_type.startswith(mt):
            return True
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in _ACCEPTED_EXTENSIONS


def process_admin_csv_document_message(from_number: str, msg: dict) -> bool:
    """Maneja un documento CSV o Excel enviado por el admin. Retorna True si fue procesado."""
    session = get_admin_session(from_number)
    if session.get("pending_action") != "contacts_admin_waiting_csv":
        return False

    doc_info = msg.get("document", {})
    mime_type = doc_info.get("mime_type", "")
    filename = doc_info.get("filename", "") or ""
    media_id = doc_info.get("id", "")

    if not _is_accepted_contacts_file(mime_type, filename):
        enviar_respuesta(
            from_number,
            "⚠️ El archivo enviado no es compatible.\n\n"
            "Formatos aceptados: *CSV* o *Excel (.xlsx)*\n\n"
            "0. Cancelar"
        )
        return True

    if not media_id:
        enviar_respuesta(from_number, "⚠️ No se pudo leer el archivo. Intentá enviarlo nuevamente.")
        return True

    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    is_xlsx = ext in (".xlsx", ".xls") or mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    enviar_respuesta(from_number, f"⏳ Descargando y procesando el archivo...")

    ok, content_bytes, err_msg = download_whatsapp_media_content(media_id)
    if not ok or not content_bytes:
        enviar_respuesta(
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
        enviar_respuesta(
            from_number,
            "⚠️ No se encontraron contactos válidos en el archivo.\n\n"
            "Revisá que el archivo tenga una columna de teléfono "
            "(Numero / phone / whatsapp_number / telefono)."
        )
        session["pending_action"] = "contacts_admin_menu"
        enviar_menu_contacts_admin_lista(from_number)
        return True

    total = len(parsed_contacts)
    enviar_respuesta(from_number, f"📊 {total} contacto(s) encontrado(s). Importando...")

    def on_progress(processed: int, total_c: int, percent: int) -> None:
        if percent in (25, 50, 75, 100):
            enviar_respuesta(from_number, f"⏳ Importando... {percent}% ({processed}/{total_c})")

    result = import_contacts_backup_to_firestore(
        {"contactos": parsed_contacts},
        progress_callback=on_progress,
    )

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

    enviar_respuesta(from_number, summary)
    session["pending_action"] = "contacts_admin_menu"
    enviar_menu_contacts_admin_lista(from_number)
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


def _export_contacts_and_send(
    phone: str,
    *,
    title_hint: str,
    label_filter: str = "",
    date_from: str = "",
    date_to: str = "",
) -> None:
    """Genera y envía Excel de contactos con filtros opcionales."""
    import threading
    from datetime import datetime

    def _worker() -> None:
        try:
            xlsx_bytes, count = export_all_contacts_to_xlsx_bytes(
                limit=5000,
                label_filter=label_filter or None,
                date_from=date_from or None,
                date_to=date_to or None,
            )
        except Exception as exc:
            logger.error("export_all_contacts_to_xlsx_bytes falló: %s", exc)
            enviar_respuesta(phone, f"❌ Error generando el Excel:\n{str(exc)[:300]}")
            return

        if count == 0:
            enviar_respuesta(phone, "⚠️ No hay contactos para ese filtro.")
            return

        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
        safe_hint = title_hint.replace(" ", "_").replace("/", "-")
        fname = f"contactos_{safe_hint}_{ts}.xlsx"
        mid = upload_media_to_meta(
            xlsx_bytes,
            fname,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        if not mid:
            enviar_respuesta(phone, "❌ No se pudo subir el archivo a Meta. Intentá de nuevo más tarde.")
            return

        enviado = enviar_documento_whatsapp(phone, mid, fname, caption=f"📊 {count} contactos")
        if enviado:
            enviar_respuesta(phone, f"✅ Excel listo: *{fname}*\n{count} contactos exportados.")
        else:
            enviar_respuesta(phone, "❌ Error enviando el documento. Revisá los logs.")

    threading.Thread(target=_worker, daemon=True).start()


def _download_and_send_template(phone: str) -> None:
    """Genera y envía plantilla Excel para que el admin la complete con contactos."""
    def _worker() -> None:
        try:
            from bot.database import generate_contacts_template_excel
            template_bytes = generate_contacts_template_excel()
        except Exception as exc:
            logger.error("Error generando plantilla: %s", exc)
            enviar_respuesta(phone, f"❌ Error generando plantilla:\n{str(exc)[:300]}")
            return

        fname = "plantilla_contactos.xlsx"
        mid = upload_media_to_meta(
            template_bytes,
            fname,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        if not mid:
            enviar_respuesta(phone, "❌ No se pudo subir la plantilla. Intentá de nuevo más tarde.")
            return

        enviado = enviar_documento_whatsapp(
            phone,
            mid,
            fname,
            caption="📋 Plantilla de contactos. Completá y enviá el archivo para que se carguen los datos.",
        )
        if enviado:
            enviar_respuesta(phone, "✅ Plantilla enviada. Completá los datos y enviá el archivo cuando esté lista.")
        else:
            enviar_respuesta(phone, "❌ Error enviando la plantilla. Revisá los logs.")

    import threading
    threading.Thread(target=_worker, daemon=True).start()



# ============================================================
# MOTOR DE FLUJO ADMINISTRATIVO
# ============================================================

def manejar_admin(from_number: str, text_body: str):
    """Procesa mensajes del administrador; delega al flujo usuario cuando admin no está activo."""
    session = get_admin_session(from_number)
    text = text_body.strip()
    text_lower = text.lower()

    if session["awaiting_admin_password"]:
        if text == ADMIN_KEY:
            session["active"] = True
            session["awaiting_admin_password"] = False
            session["pending_action"] = None
            session["in_courses_edit_menu"] = False
            session["in_response_menu"] = False
            enviar_menu_admin_lista(from_number)
        else:
            session["awaiting_admin_password"] = False
            enviar_respuesta(from_number, "❌ Contraseña incorrecta.")
            enviar_menu_principal_lista(from_number, menu_config)
        return

    if not session["active"]:
        manejar_usuario(from_number, text_body)
        return

    if text_lower in ["hola", "menu", "inicio"]:
        session["active"] = False
        session["awaiting_admin_password"] = False
        reset_user_flow(session)
        enviar_menu_principal_lista(from_number, menu_config)
        return

    # ============================================================
    # FLUJOS DE CURSOS
    # ============================================================

    if session["pending_action"] == "awaiting_course_name":
        if text == "0":
            session["pending_action"] = None
            session["temp_course_data"] = {}
            enviar_menu_cursos_edit_lista(from_number)
            return
        session["temp_course_data"]["nombre"] = text_body
        enviar_respuesta(from_number, "✅ Nombre ingresado.\n\n📝 Ahora ingresa el link del curso (sitio web):\n\n0. Volver al menú admin")
        session["pending_action"] = "awaiting_course_link"
        return

    if session["pending_action"] == "awaiting_course_link":
        if text == "0":
            session["pending_action"] = "awaiting_course_name"
            enviar_respuesta(from_number, "📝 ¿Cuál es el nombre del curso?\n\n0. Volver al menú admin")
            return
        session["temp_course_data"]["link_web"] = text_body
        enviar_respuesta(from_number, "✅ Link del curso ingresado.\n\n📄 Ahora ingresa el link del PDF del programa:\n\n0. Volver al menú admin")
        session["pending_action"] = "awaiting_course_pdf"
        return

    if session["pending_action"] == "awaiting_course_pdf":
        if text == "0":
            session["pending_action"] = "awaiting_course_link"
            enviar_respuesta(from_number, "📝 Ingresa el link del curso (sitio web):\n\n0. Volver al menú admin")
            return
        session["temp_course_data"]["link_descarga"] = text_body
        resumen = (
            " RESUMEN DE DATOS INGRESADOS\n\n"
            f" Nombre: {session['temp_course_data']['nombre']}\n"
            f" Link Curso: {session['temp_course_data']['link_web']}\n"
            f" Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
            "¿Deseas continuar?\n1. ACEPTAR\n2. EDITAR\n\n0. Volver al menú admin\n\nEscribe tu opción:"
        )
        enviar_respuesta(from_number, resumen)
        session["pending_action"] = "confirm_course_data"
        return

    if session["pending_action"] == "confirm_course_data":
        if text == "1":
            max_id = max([int(k) for k in menu_config["cursos"].keys()]) if menu_config["cursos"] else 0
            nuevo_id = str(max_id + 1)
            menu_config["cursos"][nuevo_id] = {
                "nombre": session["temp_course_data"]["nombre"],
                "descripcion": session["temp_course_data"].get("descripcion", ""),
                "link_web": session["temp_course_data"]["link_web"],
                "link_descarga": session["temp_course_data"]["link_descarga"],
                "vendedor_id": "1",
            }
            save_menu_config(menu_config)
            enviar_respuesta(
                from_number,
                f"✅ Curso '{session['temp_course_data']['nombre']}' agregado con ID {nuevo_id}."
            )
            enviar_menu_cursos_edit_lista(from_number)
            session["pending_action"] = None
            session["temp_course_data"] = {}
        elif text == "2":
            enviar_respuesta(from_number, "✏️ ¿QUÉ DESEAS EDITAR?\n\n1. ✏️ Nombre\n2. ✏️ Link Curso\n3. ✏️ Link PDF\n\n0. Volver\n\nEscribe tu opción:")
            session["pending_action"] = "edit_course_field_add"
        elif text == "0":
            session["pending_action"] = None
            session["temp_course_data"] = {}
            enviar_menu_cursos_edit_lista(from_number)
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Usa 1 o 2.")
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
            enviar_respuesta(from_number, resumen)
            session["pending_action"] = "confirm_course_data"
        elif text in fields:
            field_key, field_name = fields[text]
            session["temp_field"] = field_key
            enviar_respuesta(from_number, f"📝 Ingresa el nuevo valor para {field_name}:\n\n0. Volver al menú admin")
            session["pending_action"] = "awaiting_field_value_add"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Intenta de nuevo.")
        return

    if session["pending_action"] == "awaiting_field_value_add":
        if text == "0":
            session["pending_action"] = "edit_course_field_add"
            session["temp_field"] = None
            enviar_respuesta(from_number, "✏️ ¿QUÉ DESEAS EDITAR?\n\n1. ✏️ Nombre\n2. ✏️ Link Curso\n3. ✏️ Link PDF\n\n0. Volver\n\nEscribe tu opción:")
            return
        field = session["temp_field"]
        session["temp_course_data"][field] = text_body
        resumen = (
            "📋 RESUMEN DE DATOS INGRESADOS\n\n"
            f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
            f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
            f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
            "¿Deseas continuar?\n1. ✅ ACEPTAR\n2. ✏️ EDITAR\n\nEscribe tu opción:"
        )
        enviar_respuesta(from_number, resumen)
        session["pending_action"] = "confirm_course_data"
        session["temp_field"] = None
        return

    if session["pending_action"] == "delete_course":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_cursos_edit_lista(from_number)
            return
        if text in menu_config["cursos"]:
            curso = menu_config["cursos"][text]
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"⚠️ ¿Estás seguro de eliminar '{curso['nombre']}'?\n\n1. ✅ Sí\n0. ❌ No\n\nEscribe tu opción:"
            )
            session["pending_action"] = "confirm_delete_course"
        else:
            enviar_respuesta(from_number, "❌ Curso no encontrado.\n\n" + build_courses_menu(menu_config))
        return

    if session["pending_action"] == "confirm_delete_course":
        if text == "1":
            curso_id = session["temp_option"]
            curso = menu_config["cursos"][curso_id]
            del menu_config["cursos"][curso_id]
            reorganize_course_ids(menu_config)
            enviar_respuesta(
                from_number,
                f"✅ Curso '{curso['nombre']}' eliminado.\n\nℹ️ Los IDs se han reorganizado automáticamente."
            )
            enviar_menu_cursos_edit_lista(from_number)
        elif text == "0":
            enviar_respuesta(from_number, "❌ Eliminación cancelada.")
            enviar_menu_cursos_edit_lista(from_number)
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa 1 o 0.")
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "edit_course_select":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_cursos_edit_lista(from_number)
            return
        if text in menu_config["cursos"]:
            session["current_course"] = text
            curso = menu_config["cursos"][text]
            detalle = (
                f"📝 CONTENIDO ACTUAL DEL CURSO\n\n"
                f"ID: {text}\nNombre: {curso.get('nombre', '')}\n"
                f"Descripción: {curso.get('descripcion', '')}\n"
                f"Link web: {curso.get('link_web', '')}\nLink descarga: {curso.get('link_descarga', '')}\n\n"
                "1. Editar\n2. Volver"
            )
            enviar_respuesta(from_number, detalle)
            session["pending_action"] = "edit_course_overview"
        else:
            enviar_respuesta(from_number, "❌ Curso no encontrado.\n\n" + build_courses_menu(menu_config))
        return

    if session["pending_action"] == "edit_course_overview":
        if text == "1":
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            menu_edit = f"✏️ EDITAR CURSO: {curso.get('nombre', 'N/A')}\n\n1. Nombre\n2. Descripción\n3. Link web\n4. Link descarga\n\n0. Volver\n\nElegí qué campo querés editar:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
        elif text == "2":
            session["pending_action"] = None
            session["current_course"] = None
            session["temp_field"] = None
            session["temp_course_data"].pop("edit_pending_value", None)
            enviar_menu_cursos_edit_lista(from_number)
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Escribí 1 para editar o 2 para volver.")
        return

    if session["pending_action"] == "edit_course_field":
        fields = {"1": "nombre", "2": "descripcion", "3": "link_web", "4": "link_descarga"}
        field_name = {"nombre": "Nombre", "descripcion": "Descripción", "link_web": "Link web", "link_descarga": "Link descarga"}
        if text == "0":
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            detalle = (
                f"📝 CONTENIDO ACTUAL DEL CURSO\n\nID: {curso_id}\nNombre: {curso.get('nombre', '')}\n"
                f"Descripción: {curso.get('descripcion', '')}\n"
                f"Link web: {curso.get('link_web', '')}\nLink descarga: {curso.get('link_descarga', '')}\n\n"
                "1. Editar\n2. Volver"
            )
            enviar_respuesta(from_number, detalle)
            session["pending_action"] = "edit_course_overview"
        elif text in fields:
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            session["temp_field"] = fields[text]
            campo = session["temp_field"]
            valor_actual = curso.get(campo, "")
            enviar_respuesta(
                from_number,
                f"Campo: {field_name.get(campo, campo)}\nValor actual: {valor_actual}\n\nIngresá el nuevo valor:"
            )
            session["pending_action"] = "awaiting_field_value"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Elegí 1, 2, 3, 4 o 0.")
        return

    if session["pending_action"] == "awaiting_field_value":
        session["temp_course_data"]["edit_pending_value"] = text_body
        curso_id = session.get("current_course")
        field = session.get("temp_field")
        field_name = {"nombre": "Nombre", "descripcion": "Descripción", "link_web": "Link web", "link_descarga": "Link descarga"}
        curso = menu_config["cursos"].get(curso_id, {})
        valor_actual = curso.get(field, "")
        enviar_respuesta(
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
            enviar_respuesta(from_number, "✅ Campo actualizado exitosamente.")
            enviar_menu_cursos_edit_lista(from_number)
            session["pending_action"] = None
            session["temp_field"] = None
            session["current_course"] = None
            session["temp_course_data"].pop("edit_pending_value", None)
        elif text == "2":
            curso_id = session.get("current_course")
            curso = menu_config["cursos"].get(curso_id, {})
            menu_edit = f"✏️ EDITAR CURSO: {curso.get('nombre', 'N/A')}\n\n1. Nombre\n2. Descripción\n3. Link web\n4. Link descarga\n\n0. Volver\n\nElegí qué campo querés editar:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
            session["temp_course_data"].pop("edit_pending_value", None)
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Escribí 1 para enviar o 2 para volver.")
        return

    if session["in_courses_edit_menu"]:
        if text == "0":
            session["in_courses_edit_menu"] = False
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
        elif text == "1":
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, "📝 AGREGAR NUEVO CURSO\n\n¿Cuál es el nombre del curso?")
            session["pending_action"] = "awaiting_course_name"
        elif text == "2":
            enviar_respuesta(from_number, "❌ Ingresa el número del curso a eliminar:\n\n" + build_courses_menu(menu_config))
            session["pending_action"] = "delete_course"
        elif text == "3":
            enviar_respuesta(from_number, "✏️ Ingresa el número del curso a editar:\n\n" + build_courses_menu(menu_config))
            session["pending_action"] = "edit_course_select"
        elif text == "4":
            enviar_respuesta(from_number, build_courses_menu(menu_config))
        else:
            enviar_menu_cursos_edit_lista(from_number)
        return

    # ============================================================
    # MENU PRINCIPAL ADMIN — DISPATCH
    # ============================================================

    if session["pending_action"] is None:
        if text == "0":
            session["active"] = False
            reset_user_flow(session)
            enviar_menu_principal_lista(from_number, menu_config)
            return

        if text == "1":
            enviar_respuesta(from_number, "📋 Vista previa del menú principal:")
            enviar_menu_principal_lista(from_number, menu_config)
            return

        if text == "2":
            enviar_respuesta(
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
            enviar_respuesta(from_number, menu_str)
            session["pending_action"] = "edit_option_select"
            return

        if text == "4":
            enviar_respuesta(from_number, "➕ AGREGAR NUEVA OPCIÓN\n\n¿Cuál es el título de la nueva opción?\n\n0. Volver al menú admin")
            session["pending_action"] = "add_option_title"
            return

        if text == "5":
            resp_str = "📝 EDITAR RESPUESTA\n\n"
            for key in sorted(menu_config["responses"].keys(), key=int):
                resp_str += f"{key}. {menu_config['responses'][key][:40]}...\n"
            resp_str += f"\n¿Qué respuesta deseas editar? (1-{len(menu_config['responses'])})\n0. Volver al menú admin"
            enviar_respuesta(from_number, resp_str)
            session["pending_action"] = "edit_response_select"
            return

        if text == "6":
            session["in_courses_edit_menu"] = True
            enviar_menu_cursos_edit_lista(from_number)
            return

        if text == "7":
            enviar_respuesta(from_number, build_vendor_menu())
            session["pending_action"] = "vendor_menu"
            return

        if text == "8":
            if session["change_history"]:
                ultimo_cambio = session["change_history"].pop()
                enviar_respuesta(from_number, f"⏮️ Cambio deshecho:\n{ultimo_cambio}")
                enviar_menu_admin_lista(from_number)
            else:
                enviar_respuesta(from_number, "❌ No hay cambios para deshacer.")
                enviar_menu_admin_lista(from_number)
            return

        if text == "9":
            session["active"] = False
            reset_user_flow(session)
            enviar_respuesta(from_number, "✅ Admin desactivado.")
            enviar_menu_principal_lista(from_number, menu_config)
            return

        if text == "10":
            enviar_respuesta(from_number, build_backup_menu(menu_config))
            session["pending_action"] = "backup_menu"
            return

        if text == "11":
            enviar_respuesta(from_number, build_email_admin_menu(menu_config))
            session["pending_action"] = "email_admin_menu"
            return

        if text == "12":
            enviar_respuesta(from_number, build_runtime_revision_message(menu_config))
            session["pending_action"] = "revision_info"
            return

        if text == "13":
            enviar_menu_contacts_admin_lista(from_number)
            session["pending_action"] = "contacts_admin_menu"
            return

        if text == "14":
            enviar_respuesta(from_number, build_prompt_rules_admin_menu(menu_config))
            session["pending_action"] = "prompt_rules_menu"
            return

        if text == "15":
            enviar_respuesta(from_number, build_broadcast_menu())
            session["pending_action"] = "broadcast_menu"
            session["temp_broadcast"] = {}
            return

        enviar_respuesta(from_number, "❌ Opción inválida.")
        enviar_menu_admin_lista(from_number)
        return

    # ============================================================
    # SUB-FLUJOS
    # ============================================================

    if session["pending_action"] == "revision_info":
        session["pending_action"] = None
        enviar_menu_admin_lista(from_number)
        return

    if session["pending_action"] == "contacts_admin_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
            return
        if text == "1":
            ejemplo = (
                "*FORMATO JSON DE BACKUP*\n\n"
                "{\n  \"origen\": \"backup_whatsapp\",\n  \"evento_default\": \"importacion_backup\",\n"
                "  \"contactos\": [\n    {\"whatsapp_number\": \"5492615031839\"},\n"
                "    {\"phone\": \"+54 9 261 238 0499\", \"nombre\": \"Maria\", \"etiqueta_cliente\": \"interesado_empresa\"}\n"
                "  ]\n}\n\n"
                "Campo obligatorio por contacto: telefono (whatsapp_number / phone / telefono / numero)."
            )
            enviar_respuesta(from_number, ejemplo)
            enviar_menu_contacts_admin_lista(from_number)
            return
        if text == "2":
            instrucciones = (
                "*IMPORTAR BACKUP A FIRESTORE*\n\n"
                "Endpoint: POST /admin/firestore/contacts/import\n"
                "Header requerido: x-admin-key\n"
                "Body: JSON con array 'contactos'\n\n"
                "PowerShell (ejemplo):\n"
                "$headers = @{\"x-admin-key\"=\"TU_ADMIN_KEY\"}\n"
                "$body = Get-Content .\\contactos_backup.json -Raw\n"
                "Invoke-RestMethod -Uri \"https://TU-SERVICIO/admin/firestore/contacts/import\" -Method Post -Headers $headers -ContentType \"application/json\" -Body $body"
            )
            enviar_respuesta(from_number, instrucciones)
            enviar_menu_contacts_admin_lista(from_number)
            return
        if text == "3":
            reglas = (
                "*REGLAS DE IMPORTACION*\n\n"
                "1) Si no hay telefono valido, se omite el contacto.\n"
                "2) Si hay telefono, se guarda aunque falten otros datos.\n"
                "3) Se deduplica por telefono normalizado dentro del mismo JSON.\n"
                "4) Si el telefono ya existe en Firestore, se ignora.\n"
                "5) Campos opcionales: nombre, etiqueta_cliente, intereses, extra_fields, ultimo_evento."
            )
            enviar_respuesta(from_number, reglas)
            enviar_menu_contacts_admin_lista(from_number)
            return
        if text == "4":
            session["pending_action"] = "contacts_admin_waiting_csv"
            enviar_respuesta(
                from_number,
                "📎 Enviá el archivo como *documento* por este chat.\n\n"
                "Formatos aceptados: *CSV* o *Excel (.xlsx)*\n\n"
                "Columnas reconocidas: Numero / phone / whatsapp_number, Nombre, Etiqueta, Intereses.\n\n"
                "Para cancelar escribí 0."
            )
            return
        if text == "5":
            enviar_respuesta(from_number, build_contacts_saved_list_message(limit=20))
            enviar_menu_contacts_admin_lista(from_number)
            return
        if text == "6":
            enviar_respuesta(from_number, "⏳ Generando plantilla de contactos...")
            _download_and_send_template(from_number)
            enviar_menu_contacts_admin_lista(from_number)
            return
        if text == "7":
            session["pending_action"] = "recovery_contacts_menu"
            enviar_menu_recovery_contacts_lista(from_number)
            return
        enviar_respuesta(from_number, "❌ Opción inválida.")
        enviar_menu_contacts_admin_lista(from_number)
        return

    if session["pending_action"] == "recovery_contacts_menu":
        if text == "0":
            session["pending_action"] = "contacts_admin_menu"
            enviar_menu_contacts_admin_lista(from_number)
            return
        if text == "1":
            session["pending_action"] = "recovery_contacts_menu"
            enviar_respuesta(
                from_number,
                "⏳ Generando Excel con todos los contactos...\n"
                "Esto puede tardar 1-2 minutos. Te llegará el archivo cuando esté listo."
            )
            _export_contacts_and_send(from_number, title_hint="todos")
            return
        if text == "2":
            label_counts = get_contact_label_counts_from_firestore(limit=5000)
            if not label_counts:
                enviar_respuesta(from_number, "⚠️ No hay etiquetas disponibles para exportar.")
                enviar_menu_recovery_contacts_lista(from_number)
                return
            session["recovery_label_counts"] = label_counts
            session["pending_action"] = "recovery_export_label_select"
            enviar_respuesta(from_number, build_recovery_export_labels_menu(label_counts))
            return
        if text == "3":
            session["pending_action"] = "recovery_export_date_input"
            enviar_respuesta(
                from_number,
                "📅 Ingresá la fecha o rango para exportar.\n\n"
                "Formatos:\n"
                "- Un día: 2026-04-12\n"
                "- Rango: 2026-04-01 a 2026-04-12\n\n"
                "0. Volver"
            )
            return
        if text == "4":
            instrucciones = (
                "*HERRAMIENTA EXTERNA DE RECUPERACIÓN*\n\n"
                "Requisitos: Node.js ≥ 16 instalado localmente.\n\n"
                "*Pasos:*\n"
                "1. Abrí una terminal en la carpeta:\n"
                "   RECUPERACION DE CONTACTOS/\n\n"
                "2. Instalá dependencias (solo la primera vez):\n"
                "   npm install\n\n"
                "3. Ejecutá la herramienta:\n"
                "   npm start\n\n"
                "4. Escaneá el QR con tu teléfono:\n"
                "   WhatsApp → ⋮ → Dispositivos vinculados → Vincular\n\n"
                "5. El CSV se guarda en:\n"
                "   RECUPERACION DE CONTACTOS/exports/\n\n"
                "*Para importar el CSV al bot:*\n"
                "Volvé a Admin Contactos → Opción 4: Subir CSV por WhatsApp"
            )
            enviar_respuesta(from_number, instrucciones)
            enviar_menu_recovery_contacts_lista(from_number)
            return
        enviar_respuesta(from_number, "❌ Opción inválida.")
        enviar_menu_recovery_contacts_lista(from_number)
        return

    if session["pending_action"] == "recovery_export_label_select":
        if text == "0":
            session["pending_action"] = "recovery_contacts_menu"
            enviar_menu_recovery_contacts_lista(from_number)
            return
        options = session.get("recovery_label_counts") or []
        try:
            idx = int(text)
        except ValueError:
            enviar_respuesta(from_number, "⚠️ Opción inválida. Elegí un número de la lista o 0 para volver.")
            return
        if idx < 1 or idx > len(options):
            enviar_respuesta(from_number, "⚠️ Opción fuera de rango. Elegí un número válido.")
            return

        selected_label = options[idx - 1][0]
        session["pending_action"] = "recovery_contacts_menu"
        enviar_respuesta(
            from_number,
            f"⏳ Generando Excel para etiqueta: *{selected_label}*...\n"
            "Esto puede tardar 1-2 minutos."
        )
        _export_contacts_and_send(
            from_number,
            title_hint=f"etiqueta_{selected_label}",
            label_filter=selected_label,
        )
        return

    if session["pending_action"] == "recovery_export_date_input":
        if text == "0":
            session["pending_action"] = "recovery_contacts_menu"
            enviar_menu_recovery_contacts_lista(from_number)
            return

        date_from, date_to, err = _parse_date_range_input(text)
        if err:
            enviar_respuesta(from_number, err + "\n\n0. Volver")
            return

        session["pending_action"] = "recovery_contacts_menu"
        if date_from == date_to:
            hint = f"{date_from}"
            msg = f"⏳ Generando Excel para la fecha *{date_from}*..."
        else:
            hint = f"{date_from}_a_{date_to}"
            msg = f"⏳ Generando Excel para el rango *{date_from}* a *{date_to}*..."

        enviar_respuesta(from_number, msg + "\nEsto puede tardar 1-2 minutos.")
        _export_contacts_and_send(
            from_number,
            title_hint=f"fecha_{hint}",
            date_from=date_from,
            date_to=date_to,
        )
        return

    if session["pending_action"] == "contacts_admin_waiting_csv":
        if text == "0":
            session["pending_action"] = "contacts_admin_menu"
            enviar_menu_contacts_admin_lista(from_number)
            return
        enviar_respuesta(from_number, "📎 Esperando archivo CSV como documento. Si querés cancelar, escribí 0.")
        return

    # --- PROMPT RULES ---

    if session["pending_action"] == "prompt_rules_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
            return
        if text == "1":
            enviar_respuesta(from_number, build_prompt_rules_list_message(menu_config) + "\n\n" + build_prompt_rules_admin_menu(menu_config))
            return
        if text == "2":
            enviar_respuesta(
                from_number,
                "Escribí la nueva regla para Gemini.\nEjemplo: Si consultan por precio, informar que hay 3 cuotas sin interes.\n\n0. Volver"
            )
            session["pending_action"] = "prompt_rules_add"
            return
        if text == "3":
            if not get_gemini_prompt_rules(menu_config):
                enviar_respuesta(from_number, "No hay reglas para editar.\n\n" + build_prompt_rules_admin_menu(menu_config))
                return
            enviar_respuesta(from_number, build_prompt_rules_select_message("Editar", menu_config))
            session["pending_action"] = "prompt_rules_edit_select"
            return
        if text == "4":
            if not get_gemini_prompt_rules(menu_config):
                enviar_respuesta(from_number, "No hay reglas para eliminar.\n\n" + build_prompt_rules_admin_menu(menu_config))
                return
            enviar_respuesta(from_number, build_prompt_rules_select_message("Eliminar", menu_config))
            session["pending_action"] = "prompt_rules_delete_select"
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_prompt_rules_admin_menu(menu_config))
        return

    if session["pending_action"] == "prompt_rules_add":
        if text == "0":
            session["pending_action"] = "prompt_rules_menu"
            enviar_respuesta(from_number, build_prompt_rules_admin_menu(menu_config))
            return
        new_rule = " ".join(text_body.split()).strip()
        if not new_rule:
            enviar_respuesta(from_number, "⚠️ La regla no puede estar vacía. Ingresala nuevamente:\n\n0. Volver")
            return
        rules = get_gemini_prompt_rules(menu_config)
        rules.append(new_rule)
        menu_config["gemini_prompt_rules"] = rules
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(f"Regla Gemini agregada: {new_rule[:80]}")
        session["pending_action"] = "prompt_rules_menu"
        enviar_respuesta(from_number, "✅ Regla agregada correctamente.\n\n" + build_prompt_rules_admin_menu(menu_config))
        return

    if session["pending_action"] == "prompt_rules_edit_select":
        if text == "0":
            session["pending_action"] = "prompt_rules_menu"
            session["temp_option"] = None
            enviar_respuesta(from_number, build_prompt_rules_admin_menu(menu_config))
            return
        rules = get_gemini_prompt_rules(menu_config)
        if not text.isdigit() or int(text) < 1 or int(text) > len(rules):
            enviar_respuesta(from_number, "❌ Número inválido.\n\n" + build_prompt_rules_select_message("Editar", menu_config))
            return
        index = int(text) - 1
        session["temp_option"] = str(index)
        enviar_respuesta(
            from_number,
            f"Regla actual:\n{rules[index]}\n\nEscribí la nueva versión de la regla:\n\n0. Volver"
        )
        session["pending_action"] = "prompt_rules_edit_value"
        return

    if session["pending_action"] == "prompt_rules_edit_value":
        if text == "0":
            session["pending_action"] = "prompt_rules_edit_select"
            session["temp_option"] = None
            enviar_respuesta(from_number, build_prompt_rules_select_message("Editar", menu_config))
            return
        index_raw = session.get("temp_option")
        if index_raw is None or not str(index_raw).isdigit():
            session["pending_action"] = "prompt_rules_menu"
            enviar_respuesta(from_number, "⚠️ No pude identificar la regla a editar.\n\n" + build_prompt_rules_admin_menu(menu_config))
            return
        rules = get_gemini_prompt_rules(menu_config)
        index = int(str(index_raw))
        if index < 0 or index >= len(rules):
            session["pending_action"] = "prompt_rules_menu"
            session["temp_option"] = None
            enviar_respuesta(from_number, "⚠️ La regla seleccionada ya no existe.\n\n" + build_prompt_rules_admin_menu(menu_config))
            return
        updated_rule = " ".join(text_body.split()).strip()
        if not updated_rule:
            enviar_respuesta(from_number, "⚠️ La regla no puede estar vacía. Ingresala nuevamente:\n\n0. Volver")
            return
        previous_rule = rules[index]
        rules[index] = updated_rule
        menu_config["gemini_prompt_rules"] = rules
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(
            f"Regla Gemini editada: '{previous_rule[:60]}' -> '{updated_rule[:60]}'"
        )
        session["pending_action"] = "prompt_rules_menu"
        session["temp_option"] = None
        enviar_respuesta(from_number, "✅ Regla actualizada.\n\n" + build_prompt_rules_admin_menu(menu_config))
        return

    if session["pending_action"] == "prompt_rules_delete_select":
        if text == "0":
            session["pending_action"] = "prompt_rules_menu"
            enviar_respuesta(from_number, build_prompt_rules_admin_menu(menu_config))
            return
        rules = get_gemini_prompt_rules(menu_config)
        if not text.isdigit() or int(text) < 1 or int(text) > len(rules):
            enviar_respuesta(from_number, "❌ Número inválido.\n\n" + build_prompt_rules_select_message("Eliminar", menu_config))
            return
        index = int(text) - 1
        removed_rule = rules.pop(index)
        menu_config["gemini_prompt_rules"] = rules
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(f"Regla Gemini eliminada: {removed_rule[:80]}")
        session["pending_action"] = "prompt_rules_menu"
        enviar_respuesta(from_number, "✅ Regla eliminada.\n\n" + build_prompt_rules_admin_menu(menu_config))
        return

    # --- GREETING / OPTIONS / RESPONSES ---

    if session["pending_action"] == "edit_greeting":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
            return
        session["change_history"].append(f"Saludo anterior: {menu_config['greeting'][:50]}...")
        menu_config["greeting"] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Saludo actualizado.")
        enviar_menu_admin_lista(from_number)
        session["pending_action"] = None
        return

    if session["pending_action"] == "edit_option_select":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
        elif text in menu_config["options"]:
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"✏️ OPCIÓN ACTUAL: {menu_config['options'][text]}\n\nEscribe el nuevo texto:\n\n0. Volver al menú admin"
            )
            session["pending_action"] = "edit_option_text"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.")
        return

    if session["pending_action"] == "edit_option_text":
        if text == "0":
            session["pending_action"] = None
            session["temp_option"] = None
            enviar_menu_admin_lista(from_number)
            return
        option_id = session["temp_option"]
        session["change_history"].append(f"Opción {option_id}: '{menu_config['options'][option_id]}' → '{text_body}'")
        menu_config["options"][option_id] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Opción actualizada.")
        enviar_menu_admin_lista(from_number)
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "add_option_title":
        if text == "0":
            session["pending_action"] = None
            session["temp_option_text"] = None
            enviar_menu_admin_lista(from_number)
            return
        session["temp_option_text"] = text_body
        enviar_respuesta(
            from_number,
            f"💬 Título: '{text_body}'\n\n¿Cuál será la respuesta a esta opción?\n\n0. Volver al menú admin"
        )
        session["pending_action"] = "add_option_response"
        return

    if session["pending_action"] == "add_option_response":
        if text == "0":
            session["pending_action"] = None
            session["temp_option_text"] = None
            enviar_menu_admin_lista(from_number)
            return
        max_id = max([int(k) for k in menu_config["options"].keys()]) if menu_config["options"] else 0
        nuevo_id = str(max_id + 1)
        menu_config["options"][nuevo_id] = session["temp_option_text"]
        menu_config["responses"][nuevo_id] = text_body
        save_menu_config(menu_config)
        session["change_history"].append(f"Opción agregada: {nuevo_id}. {session['temp_option_text']}")
        enviar_respuesta(from_number, f"✅ Opción [{nuevo_id}] agregada con éxito.")
        enviar_menu_admin_lista(from_number)
        session["pending_action"] = None
        session["temp_option_text"] = None
        return

    if session["pending_action"] == "edit_response_select":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
        elif text in menu_config["responses"]:
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"📝 RESPUESTA ACTUAL ({text}):\n\n{menu_config['responses'][text]}\n\n✏️ Escribe la nueva respuesta:\n\n0. Volver al menú admin"
            )
            session["pending_action"] = "edit_response_text"
        else:
            enviar_respuesta(from_number, "❌ Respuesta no encontrada.")
        return

    if session["pending_action"] == "edit_response_text":
        if text == "0":
            session["pending_action"] = None
            session["temp_option"] = None
            enviar_menu_admin_lista(from_number)
            return
        response_id = session["temp_option"]
        session["change_history"].append(
            f"Respuesta {response_id}: '{menu_config['responses'][response_id][:40]}...' → '{text_body[:40]}...'"
        )
        menu_config["responses"][response_id] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Respuesta actualizada.")
        enviar_menu_admin_lista(from_number)
        session["pending_action"] = None
        session["temp_option"] = None
        return

    # --- VENDORS ---

    if session["pending_action"] == "vendor_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
            return
        if text == "1":
            enviar_respuesta(from_number, build_vendor_list_message(menu_config) + "\n\n0. Volver")
            session["pending_action"] = "vendor_view_list"
            return
        if text == "2":
            enviar_respuesta(from_number, "¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            session["pending_action"] = "vendor_add_remove_menu"
            return
        if text == "3":
            vendedores = menu_config.get("vendedores", {})
            if not vendedores:
                enviar_respuesta(from_number, "⚠️ No hay vendedores cargados.\n\n" + build_vendor_menu())
                return
            enviar_respuesta(
                from_number,
                "Seleccioná el vendedor al que querés asignar cursos:\n\n"
                + build_vendor_list_message(menu_config) + "\n\n0. Volver"
            )
            session["pending_action"] = "vendor_assign_select_vendor"
            return
        if text == "4":
            enviar_respuesta(from_number, build_vendor_courses_assignment_message(menu_config))
            session["pending_action"] = "vendor_view_courses"
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_menu())
        return

    if session["pending_action"] == "vendor_view_list":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_list_message(menu_config) + "\n\n0. Volver")
        return

    if session["pending_action"] == "vendor_add_remove_menu":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            session.pop("temp_edit_vendor_id", None)
            enviar_respuesta(from_number, build_vendor_menu())
            return
        if text == "1":
            session.setdefault("temp_course_data", {})["vendor_draft"] = {}
            enviar_respuesta(from_number, "Ingresá *nombre completo* del vendedor:\n\n0. Volver")
            session["pending_action"] = "vendor_add_full_name"
            return
        if text == "2":
            vendedores = menu_config.get("vendedores", {})
            if not vendedores:
                enviar_respuesta(from_number, "⚠️ No hay vendedores para eliminar.\n\n" + build_vendor_menu())
                session["pending_action"] = "vendor_menu"
                return
            enviar_respuesta(from_number, "Seleccioná el número del vendedor a eliminar:\n\n" + build_vendor_list_message(menu_config) + "\n\n0. Volver")
            session["pending_action"] = "vendor_delete_select"
            return
        if text == "3":
            vendedores = menu_config.get("vendedores", {})
            if not vendedores:
                enviar_respuesta(from_number, "⚠️ No hay vendedores para editar.\n\n" + build_vendor_menu())
                session["pending_action"] = "vendor_menu"
                return
            enviar_respuesta(from_number, "Seleccioná el número del vendedor a editar:\n\n" + build_vendor_list_message(menu_config) + "\n\n0. Volver")
            session["pending_action"] = "vendor_edit_select"
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
        return

    if session["pending_action"] == "vendor_edit_select":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            session.pop("temp_edit_vendor_id", None)
            enviar_respuesta(from_number, "¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return
        vendedores = menu_config.get("vendedores", {})
        if text not in vendedores:
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.\n\n" + build_vendor_list_message(menu_config) + "\n\n0. Volver")
            return
        session["temp_edit_vendor_id"] = text
        session["pending_action"] = "vendor_edit_field"
        enviar_respuesta(from_number, build_vendor_edit_fields_menu(text, menu_config))
        return

    if session["pending_action"] == "vendor_edit_field":
        if text == "0":
            session["pending_action"] = "vendor_edit_select"
            session.pop("temp_field", None)
            enviar_respuesta(from_number, "Seleccioná el número del vendedor a editar:\n\n" + build_vendor_list_message(menu_config) + "\n\n0. Volver")
            return
        fields = {"1": "nombre_completo", "2": "correo", "3": "telefono"}
        if text not in fields:
            vendor_id = session.get("temp_edit_vendor_id", "")
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_edit_fields_menu(vendor_id, menu_config))
            return
        session["temp_field"] = fields[text]
        prompts = {
            "nombre_completo": "Ingresá el nuevo *nombre completo*:\n\n0. Volver",
            "correo": "Ingresá el nuevo *correo*:\n\n0. Volver",
            "telefono": "Ingresá el nuevo *telefono*:\n\n0. Volver",
        }
        session["pending_action"] = "vendor_edit_value"
        enviar_respuesta(from_number, prompts[fields[text]])
        return

    if session["pending_action"] == "vendor_edit_value":
        if text == "0":
            session["pending_action"] = "vendor_edit_field"
            vendor_id = session.get("temp_edit_vendor_id", "")
            session.pop("temp_field", None)
            enviar_respuesta(from_number, build_vendor_edit_fields_menu(vendor_id, menu_config))
            return
        vendor_id = session.get("temp_edit_vendor_id", "")
        vendedores = menu_config.get("vendedores", {})
        vendedor = vendedores.get(vendor_id)
        if not vendedor:
            session["pending_action"] = "vendor_add_remove_menu"
            session.pop("temp_edit_vendor_id", None)
            session.pop("temp_field", None)
            enviar_respuesta(from_number, "⚠️ El vendedor ya no existe.\n\n¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return
        field = session.get("temp_field")
        value = text_body.strip()
        if field == "correo" and not validar_correo(value):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver")
            return
        if field == "telefono" and not validar_telefono(value):
            enviar_respuesta(from_number, "⚠️ El teléfono no es válido.\n\n0. Volver")
            return
        if field == "nombre_completo":
            nombre, apellido = parse_full_name(value)
            if not nombre:
                enviar_respuesta(from_number, "⚠️ Nombre inválido.\n\n0. Volver")
                return
            before = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()
            vendedor["nombre"] = nombre
            vendedor["apellido"] = apellido
            after = f"{nombre} {apellido}".strip()
        elif field == "correo":
            before = vendedor.get("correo", "")
            vendedor["correo"] = value
            after = value
        else:
            before = vendedor.get("telefono", "")
            vendedor["telefono"] = value
            after = value
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(f"Vendedor {vendor_id} editado ({field}): '{before}' → '{after}'")
        session["pending_action"] = "vendor_edit_field"
        session.pop("temp_field", None)
        enviar_respuesta(from_number, "✅ Dato actualizado.\n\n" + build_vendor_edit_fields_menu(vendor_id, menu_config))
        return

    if session["pending_action"] == "vendor_add_full_name":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            session.setdefault("temp_course_data", {}).pop("vendor_draft", None)
            enviar_respuesta(from_number, "¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return
        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        draft["full_name"] = text_body.strip()
        enviar_respuesta(from_number, "Ingresá *correo* del vendedor:\n\n0. Volver")
        session["pending_action"] = "vendor_add_correo"
        return

    if session["pending_action"] == "vendor_add_correo":
        if text == "0":
            session["pending_action"] = "vendor_add_full_name"
            enviar_respuesta(from_number, "Ingresá *nombre completo* del vendedor:\n\n0. Volver")
            return
        if not validar_correo(text_body.strip()):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver")
            return
        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        draft["correo"] = text_body.strip()
        enviar_respuesta(from_number, "Ingresá *telefono* del vendedor:\n\n0. Volver")
        session["pending_action"] = "vendor_add_telefono"
        return

    if session["pending_action"] == "vendor_add_telefono":
        if text == "0":
            session["pending_action"] = "vendor_add_correo"
            enviar_respuesta(from_number, "Ingresá *correo* del vendedor:\n\n0. Volver")
            return
        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        draft["telefono"] = text_body.strip()
        enviar_respuesta(from_number, build_vendor_add_confirmation(draft))
        session["pending_action"] = "vendor_add_confirm"
        return

    if session["pending_action"] == "vendor_add_confirm":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            session.setdefault("temp_course_data", {}).pop("vendor_draft", None)
            enviar_respuesta(from_number, "Carga cancelada.\n\n¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return
        if text == "2":
            enviar_respuesta(from_number, "¿Qué campo querés editar?\n\n1. Nombre completo\n2. Correo\n3. Telefono\n\n0. Volver")
            session["pending_action"] = "vendor_add_edit_field"
            return
        if text == "1":
            draft = session.setdefault("temp_course_data", {}).get("vendor_draft", {})
            full_name = draft.get("full_name", "")
            nombre, apellido = parse_full_name(full_name)
            max_id = max([int(k) for k in menu_config["vendedores"].keys()]) if menu_config["vendedores"] else 0
            nuevo_id = str(max_id + 1)
            menu_config["vendedores"][nuevo_id] = {
                "nombre": nombre,
                "apellido": apellido,
                "telefono": draft.get("telefono", ""),
                "correo": draft.get("correo", ""),
            }
            save_menu_config(menu_config)
            session.setdefault("change_history", []).append(f"Vendedor agregado: {full_name}")
            session.setdefault("temp_course_data", {}).pop("vendor_draft", None)
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, "✅ Vendedor guardado.\n\n" + build_vendor_menu())
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_add_confirmation(session.setdefault("temp_course_data", {}).get("vendor_draft", {})))
        return

    if session["pending_action"] == "vendor_add_edit_field":
        if text == "0":
            draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
            session["pending_action"] = "vendor_add_confirm"
            enviar_respuesta(from_number, build_vendor_add_confirmation(draft))
            return
        fields = {"1": "full_name", "2": "correo", "3": "telefono"}
        if text not in fields:
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n1. Nombre completo\n2. Correo\n3. Telefono\n\n0. Volver")
            return
        session["temp_field"] = fields[text]
        field_names = {"full_name": "nombre completo", "correo": "correo", "telefono": "telefono"}
        enviar_respuesta(from_number, f"Ingresá nuevo {field_names[fields[text]]}:\n\n0. Volver")
        session["pending_action"] = "vendor_add_edit_value"
        return

    if session["pending_action"] == "vendor_add_edit_value":
        if text == "0":
            session["pending_action"] = "vendor_add_edit_field"
            enviar_respuesta(from_number, "¿Qué campo querés editar?\n\n1. Nombre completo\n2. Correo\n3. Telefono\n\n0. Volver")
            return
        draft = session.setdefault("temp_course_data", {}).setdefault("vendor_draft", {})
        field = session.get("temp_field")
        if field == "correo" and not validar_correo(text_body.strip()):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver")
            return
        draft[field] = text_body.strip()
        session["temp_field"] = None
        session["pending_action"] = "vendor_add_confirm"
        enviar_respuesta(from_number, build_vendor_add_confirmation(draft))
        return

    if session["pending_action"] == "vendor_delete_select":
        if text == "0":
            session["pending_action"] = "vendor_add_remove_menu"
            enviar_respuesta(from_number, "¿Qué deseas hacer?\n\n1. Agregar vendedor\n2. Eliminar vendedor\n3. Editar vendedor\n\n0. Volver")
            return
        if text not in menu_config.get("vendedores", {}):
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.\n\n" + build_vendor_list_message(menu_config) + "\n\n0. Volver")
            return
        if len(menu_config.get("vendedores", {})) <= 1:
            enviar_respuesta(from_number, "⚠️ No podés eliminar el único vendedor disponible.")
            return
        deleted_vendor = menu_config["vendedores"].pop(text)
        remaining_ids = sorted(menu_config["vendedores"].keys(), key=int)
        fallback_id = remaining_ids[0] if remaining_ids else ""
        for curso in menu_config.get("cursos", {}).values():
            current_ids = [vid for vid in get_course_vendor_ids(curso, menu_config) if vid != text]
            if current_ids:
                curso["vendedor_ids"] = current_ids
                curso["vendedor_id"] = current_ids[0]
            else:
                curso["vendedor_ids"] = [fallback_id] if fallback_id else []
                curso["vendedor_id"] = fallback_id
        save_menu_config(menu_config)
        session.setdefault("change_history", []).append(
            f"Vendedor eliminado: {deleted_vendor.get('nombre', '')} {deleted_vendor.get('apellido', '')}".strip()
        )
        session["pending_action"] = "vendor_menu"
        enviar_respuesta(from_number, "✅ Vendedor eliminado de todo el bot.\n\n" + build_vendor_menu())
        return

    if session["pending_action"] == "vendor_view_courses":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_vendor_courses_assignment_message(menu_config))
        return

    if session["pending_action"] == "vendor_assign_select_vendor":
        if text == "0":
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        vendedores = menu_config.get("vendedores", {})
        if text not in vendedores:
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.\n\n" + build_vendor_list_message(menu_config) + "\n\n0. Volver")
            return
        session["temp_assign_vendor_id"] = text
        enviar_respuesta(from_number, build_vendor_courses_toggle_message(text, menu_config))
        session["pending_action"] = "vendor_assign_courses_toggle"
        return

    if session["pending_action"] == "vendor_assign_courses_toggle":
        vendor_id = session.get("temp_assign_vendor_id", "")
        if text == "0":
            session.pop("temp_assign_vendor_id", None)
            session["pending_action"] = "vendor_menu"
            enviar_respuesta(from_number, build_vendor_menu())
            return
        cursos = menu_config.get("cursos", {})
        if text not in cursos:
            enviar_respuesta(from_number, "❌ Curso no válido.\n\n" + build_vendor_courses_toggle_message(vendor_id, menu_config))
            return
        curso = cursos[text]
        current_ids = get_course_vendor_ids(curso, menu_config)
        if vendor_id in current_ids:
            new_ids = [vid for vid in current_ids if vid != vendor_id]
            if not new_ids:
                remaining = [vid for vid in menu_config.get("vendedores", {}).keys() if vid != vendor_id]
                new_ids = [remaining[0]] if remaining else []
        else:
            new_ids = current_ids + [vendor_id]
        curso["vendedor_ids"] = new_ids
        curso["vendedor_id"] = new_ids[0] if new_ids else ""
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Guardado.\n\n" + build_vendor_courses_toggle_message(vendor_id, menu_config))
        return

    # --- BACKUPS ---

    if session["pending_action"] == "backup_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
        elif text == "1":
            filename = create_menu_backup(menu_config)
            enviar_respuesta(from_number, f"✅ Backup creado.\n\n📁 Archivo: {filename}\n\n" + build_backup_menu(menu_config))
        elif text == "2":
            backups = list_backups()
            if not backups:
                enviar_respuesta(from_number, "⚠️ No hay backups disponibles.\n\n" + build_backup_menu(menu_config))
            else:
                lista = "🔄 RESTAURAR BACKUP\n\nSeleccioná el número del backup a restaurar:\n\n"
                for i, fname in enumerate(backups, start=1):
                    lista += f"{i}. {fname}\n"
                lista += "\n0. Volver"
                session["temp_course_data"]["backup_list"] = backups
                enviar_respuesta(from_number, lista)
                session["pending_action"] = "backup_restore_select"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_backup_menu(menu_config))
        return

    if session["pending_action"] == "backup_restore_select":
        backups = session["temp_course_data"].get("backup_list", [])
        if text == "0":
            session["pending_action"] = "backup_menu"
            session["temp_course_data"].pop("backup_list", None)
            enviar_respuesta(from_number, build_backup_menu(menu_config))
        elif text.isdigit() and 1 <= int(text) <= len(backups):
            selected = backups[int(text) - 1]
            session["temp_option"] = selected
            enviar_respuesta(
                from_number,
                f"⚠️ ¿Restaurar el backup?\n\n📁 {selected}\n\n⚠️ Esta acción reemplazará la configuración actual.\n\n1. ✅ Confirmar\n0. ❌ Cancelar"
            )
            session["pending_action"] = "backup_restore_confirm"
        else:
            enviar_respuesta(from_number, "❌ Número inválido. Intenta de nuevo.")
        return

    if session["pending_action"] == "backup_restore_confirm":
        if text == "1":
            filename = session["temp_option"]
            backup_ref = [menu_config]
            if restore_menu_backup(filename, backup_ref):
                # Update the module-level menu_config with restored content
                import bot.menus as _menus_mod
                _menus_mod.menu_config.clear()
                _menus_mod.menu_config.update(backup_ref[0])
                enviar_respuesta(from_number, f"✅ Configuración restaurada desde:\n📁 {filename}\n\n" + build_backup_menu(menu_config))
            else:
                enviar_respuesta(from_number, "❌ Error al restaurar. El archivo no fue encontrado.\n\n" + build_backup_menu(menu_config))
            session["pending_action"] = "backup_menu"
            session["temp_option"] = None
            session["temp_course_data"].pop("backup_list", None)
        elif text == "0":
            enviar_respuesta(from_number, "❌ Restauración cancelada.\n\n" + build_backup_menu(menu_config))
            session["pending_action"] = "backup_menu"
            session["temp_option"] = None
            session["temp_course_data"].pop("backup_list", None)
        else:
            enviar_respuesta(from_number, "Opción inválida. Usá 1 para confirmar o 0 para cancelar.")
        return

    # --- EMAIL ADMIN ---

    if session["pending_action"] == "email_admin_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_menu_admin_lista(from_number)
        elif text == "1":
            current = menu_config.get("email_notificacion_admin", {}).get("activo", True)
            menu_config.setdefault("email_notificacion_admin", {})["activo"] = not current
            save_menu_config(menu_config)
            estado = "✅ Activado" if not current else "❌ Desactivado"
            enviar_respuesta(from_number, f"{estado}.\n\n" + build_email_admin_menu(menu_config))
        elif text == "2":
            dest = menu_config.get("email_notificacion_admin", {}).get("destinatario", "")
            enviar_respuesta(from_number, f"📧 Destinatario actual: *{dest}*\n\nIngresá el nuevo email destinatario:\n\n0. Volver")
            session["pending_action"] = "email_edit_destinatario"
        elif text == "3":
            asunto = menu_config.get("email_notificacion_admin", {}).get("asunto", "")
            enviar_respuesta(from_number, f"📝 Asunto actual:\n{asunto}\n\nIngresá el nuevo asunto:\n\n0. Volver")
            session["pending_action"] = "email_edit_asunto"
        elif text == "4":
            cuerpo = menu_config.get("email_notificacion_admin", {}).get("cuerpo_intro", "")
            enviar_respuesta(from_number, f"📝 Texto de introducción actual:\n{cuerpo}\n\nIngresá el nuevo texto:\n\n0. Volver")
            session["pending_action"] = "email_edit_cuerpo"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_email_admin_menu(menu_config))
        return

    if session["pending_action"] == "email_edit_destinatario":
        if text == "0":
            session["pending_action"] = "email_admin_menu"
            enviar_respuesta(from_number, build_email_admin_menu(menu_config))
            return
        if not validar_correo(text_body.strip()):
            enviar_respuesta(from_number, "⚠️ El email no es válido.\n\n0. Volver")
            return
        menu_config.setdefault("email_notificacion_admin", {})["destinatario"] = text_body.strip()
        save_menu_config(menu_config)
        session["pending_action"] = "email_admin_menu"
        enviar_respuesta(from_number, "✅ Destinatario actualizado.\n\n" + build_email_admin_menu(menu_config))
        return

    if session["pending_action"] == "email_edit_asunto":
        if text == "0":
            session["pending_action"] = "email_admin_menu"
            enviar_respuesta(from_number, build_email_admin_menu(menu_config))
            return
        menu_config.setdefault("email_notificacion_admin", {})["asunto"] = text_body.strip()
        save_menu_config(menu_config)
        session["pending_action"] = "email_admin_menu"
        enviar_respuesta(from_number, "✅ Asunto actualizado.\n\n" + build_email_admin_menu(menu_config))
        return

    if session["pending_action"] == "email_edit_cuerpo":
        if text == "0":
            session["pending_action"] = "email_admin_menu"
            enviar_respuesta(from_number, build_email_admin_menu(menu_config))
            return
        menu_config.setdefault("email_notificacion_admin", {})["cuerpo_intro"] = text_body.strip()
        save_menu_config(menu_config)
        session["pending_action"] = "email_admin_menu"
        enviar_respuesta(from_number, "✅ Texto de introducción actualizado.\n\n" + build_email_admin_menu(menu_config))
        return

    # --- BROADCAST ---

    if session["pending_action"] == "broadcast_menu":
        if text == "0":
            session["pending_action"] = None
            session["temp_broadcast"] = {}
            enviar_menu_admin_lista(from_number)
            return
        if text == "1":
            enviar_respuesta(from_number, "⏳ Consultando contactos...")
            contacts = get_all_contacts_from_firestore()
            if not contacts:
                enviar_respuesta(from_number, "⚠️ No hay contactos en Firestore.\n\n" + build_broadcast_menu())
                return
            session["temp_broadcast"] = {"contacts": contacts, "filter": "todos"}
            enviar_respuesta(from_number, f"📊 *Destinatarios:* {len(contacts)} contactos (todos)\n\n" + build_broadcast_msg_type_menu())
            session["pending_action"] = "broadcast_msg_type"
            return
        if text == "2":
            enviar_respuesta(from_number, "⏳ Buscando etiquetas...")
            tags = get_all_distinct_tags_from_firestore()
            if not tags:
                enviar_respuesta(from_number, "⚠️ No se encontraron etiquetas guardadas.\n\n" + build_broadcast_menu())
                return
            session["temp_broadcast"] = {"tags": tags}
            enviar_respuesta(from_number, build_broadcast_tag_list_message(tags))
            session["pending_action"] = "broadcast_tag_select"
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_broadcast_menu())
        return

    if session["pending_action"] == "broadcast_tag_select":
        if text == "0":
            session["pending_action"] = "broadcast_menu"
            enviar_respuesta(from_number, build_broadcast_menu())
            return
        tags = (session.get("temp_broadcast") or {}).get("tags", [])
        if not text.isdigit() or int(text) < 1 or int(text) > len(tags):
            enviar_respuesta(from_number, "❌ Número inválido.\n\n" + build_broadcast_tag_list_message(tags))
            return
        chosen_tag = tags[int(text) - 1]
        enviar_respuesta(from_number, f"⏳ Buscando contactos con etiqueta *{chosen_tag}*...")
        contacts = get_contacts_by_label(chosen_tag)
        if not contacts:
            enviar_respuesta(from_number, f"⚠️ No hay contactos con etiqueta *{chosen_tag}*.\n\n" + build_broadcast_tag_list_message(tags))
            return
        session["temp_broadcast"] = {"contacts": contacts, "filter": chosen_tag, "tags": tags}
        enviar_respuesta(from_number, f"📊 *Destinatarios:* {len(contacts)} contactos (etiqueta: *{chosen_tag}*)\n\n" + build_broadcast_msg_type_menu())
        session["pending_action"] = "broadcast_msg_type"
        return

    if session["pending_action"] == "broadcast_msg_type":
        if text == "0":
            session["pending_action"] = "broadcast_menu"
            session["temp_broadcast"] = {}
            enviar_respuesta(from_number, build_broadcast_menu())
            return
        if text == "1":
            enviar_respuesta(
                from_number,
                "✏️ *MENSAJE PERSONALIZADO*\n\nEscribí el mensaje que querés enviar.\nTip: usá {nombre} para personalizar.\n\n0. Volver"
            )
            session["pending_action"] = "broadcast_write_message"
            return
        if text == "2":
            enviar_respuesta(
                from_number,
                "📋 *PLANTILLA META*\n\nEscribí el nombre exacto de la plantilla aprobada en Meta.\nEjemplo: mensaje_inicial\n\n0. Volver"
            )
            session["pending_action"] = "broadcast_write_template"
            return
        enviar_respuesta(from_number, "❌ Opción inválida.\n\n" + build_broadcast_msg_type_menu())
        return

    if session["pending_action"] == "broadcast_write_message":
        if text == "0":
            session["pending_action"] = "broadcast_msg_type"
            enviar_respuesta(from_number, build_broadcast_msg_type_menu())
            return
        tb = session.get("temp_broadcast") or {}
        tb["msg_type"] = "text"
        tb["message"] = text_body
        session["temp_broadcast"] = tb
        n = len(tb.get("contacts", []))
        filtro = tb.get("filter", "")
        filtro_str = f" (etiqueta: {filtro})" if filtro and filtro != "todos" else " (todos)"
        preview = text_body[:300] + ("..." if len(text_body) > 300 else "")
        enviar_respuesta(
            from_number,
            f"📋 *RESUMEN DEL ENVÍO*\n\nDestinatarios: {n} contactos{filtro_str}\nTipo: Mensaje personalizado\n\n*Mensaje:*\n{preview}\n\n¿Confirmar envío?\n1. Sí, enviar\n0. Cancelar"
        )
        session["pending_action"] = "broadcast_confirm"
        return

    if session["pending_action"] == "broadcast_write_template":
        if text == "0":
            session["pending_action"] = "broadcast_msg_type"
            enviar_respuesta(from_number, build_broadcast_msg_type_menu())
            return
        tb = session.get("temp_broadcast") or {}
        tb["msg_type"] = "template"
        tb["template_name"] = text.strip()
        session["temp_broadcast"] = tb
        enviar_respuesta(
            from_number,
            f"🌐 *Código de idioma*\n\nPlantilla: *{text.strip()}*\n\nEscribí el código de idioma (ej: es, es_AR, en_US)\nO escribí *0* para usar el default (es)"
        )
        session["pending_action"] = "broadcast_write_lang"
        return

    if session["pending_action"] == "broadcast_write_lang":
        tb = session.get("temp_broadcast") or {}
        lang = "es" if text == "0" else text.strip()
        tb["template_lang"] = lang
        session["temp_broadcast"] = tb
        n = len(tb.get("contacts", []))
        filtro = tb.get("filter", "")
        filtro_str = f" (etiqueta: {filtro})" if filtro and filtro != "todos" else " (todos)"
        template_name = tb.get("template_name", "")
        enviar_respuesta(
            from_number,
            f"📋 *RESUMEN DEL ENVÍO*\n\nDestinatarios: {n} contactos{filtro_str}\nTipo: Plantilla Meta\nPlantilla: *{template_name}*\nIdioma: {lang}\n\n¿Confirmar envío?\n1. Sí, enviar\n0. Cancelar"
        )
        session["pending_action"] = "broadcast_confirm"
        return

    if session["pending_action"] == "broadcast_confirm":
        tb = session.get("temp_broadcast") or {}
        if text != "1":
            session["pending_action"] = None
            session["temp_broadcast"] = {}
            enviar_respuesta(from_number, "❌ Envío cancelado.")
            enviar_menu_admin_lista(from_number)
            return
        contacts = tb.get("contacts", [])
        if not contacts:
            session["pending_action"] = None
            session["temp_broadcast"] = {}
            enviar_respuesta(from_number, "⚠️ No hay contactos para enviar.")
            enviar_menu_admin_lista(from_number)
            return
        n = len(contacts)
        enviar_respuesta(from_number, f"⏳ Enviando mensajes a {n} contactos... por favor esperá.")
        result = execute_broadcast_send(
            contacts=contacts,
            msg_type=tb.get("msg_type", "text"),
            message=tb.get("message", ""),
            template_name=tb.get("template_name", ""),
            template_lang=tb.get("template_lang", "es"),
        )
        session["pending_action"] = None
        session["temp_broadcast"] = {}
        resumen = (
            f"📣 *ENVÍO COMPLETADO*\n\n"
            f"✅ Enviados: {result['enviados']}\n"
            f"❌ Fallidos: {result['fallidos']}"
        )
        if result["errores"]:
            primeros = "\n".join(result["errores"][:3])
            resumen += f"\n\n⚠️ Primeros errores:\n{primeros}"
        enviar_respuesta(from_number, resumen + "\n\n" + build_admin_menu())
        return

    # Catch-all
    session["pending_action"] = None
    enviar_respuesta(from_number, "❌ Estado no reconocido. Volviendo al menú admin.")
    enviar_menu_admin_lista(from_number)
