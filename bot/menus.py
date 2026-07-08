"""bot/menus.py — Configuración de menú, constructores de texto e interactivos.

Importa de bot.config, bot.utils, bot.database y bot.whatsapp_api.
"""

import json
import os
import re
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Optional, Tuple
from urllib.parse import quote

from bot.config import (
    logger,
    CONFIG_PATH,
    BACKUPS_DIR,
    INTERESADOS_PATH,
    ASESOR_CONSULTAS_PATH,
    APP_VERSION,
    K_SERVICE,
    K_REVISION,
    K_CONFIGURATION,
)
from bot.api_webhook import get_cached_courses
from bot.utils import (
    normalize_number,
    normalize_text_for_filter,
    normalize_interest_tag,
    normalize_legacy_greeting,
    normalize_menu_command,
    build_labeled_data_block,
    parse_full_name,
    get_session_key,
)
from bot.database import (
    get_all_distinct_tags_from_firestore,
    get_contacts_by_label,
    get_all_contacts_from_firestore,
)
from bot.whatsapp_api import (
    enviar_respuesta,
    enviar_lista_interactiva,
    enviar_payload_whatsapp,
    enviar_curso_cta_url_boton,
    enviar_detalle_curso_template_url,
    course_url_template_enabled,
)


# ============================================================
# CARGAR / GUARDAR CONFIGURACION
# ============================================================

def load_menu_config() -> dict:
    default_config = {
        "greeting": "Gracias por comunicarte. Soy NINA 👩‍💼, la asistente virtual de Cursala, elegi una opcion o consultame lo que quieras.\n\n¿Cómo puedo ayudarte hoy?",
        "options": {
            "1": "Cursos disponibles",
            "2": "Capacitación empresarial",
            "3": "Quiero capacitar",
            "4": "Hablar con un asesor",
        },
        "responses": {
            "1": "¡Claro! En Cursala contamos con distintas propuestas de formación técnica y profesional.",
            "2": "Excelente. Vamos a recopilar algunos datos para poder asesorarte mejor.",
            "3": "¡Gracias por tu interés en capacitar con Cursala!\n\nEnvia un correo a recursos.humanos@cursala.com.ar adjuntando tu cv y tu propuesta de capacitación.",
            "4": "Perfecto, te pondremos en contacto con un asesor de Cursala a la brevedad.\n\nPor favor, indicános tu nombre y en qué temática o curso estás interesado/a."
        },
        "cursos": {
            "1": {
                "nombre": "Minería",
                "descripcion": "Formación en técnicas de extracción, seguridad minera.",
                "link_web": "https://www.cursala.com/cursos/mineria",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
        },
        "vendedores": {
            "1": {
                "nombre": "Carlos",
                "apellido": "García",
                "telefono": "+5492615031839",
                "correo": "carlos@cursala.com.ar"
            }
        },
        "email_notificacion_admin": {
            "activo": True,
            "destinatario": "info@cursala.com.ar",
            "asunto": "Nuevo contacto en WhatsApp Bot - Cursala",
            "cuerpo_intro": "Se ha registrado un nuevo usuario en el bot de Cursala.",
        },
        "gemini_prompt_rules": [],
    }

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        changed = False
        for key in ["greeting", "options", "responses", "cursos", "vendedores", "email_notificacion_admin", "gemini_prompt_rules"]:
            if key not in config:
                config[key] = default_config[key]
                changed = True

        normalized_greeting = normalize_legacy_greeting(config.get("greeting", ""))
        if normalized_greeting != config.get("greeting", ""):
            config["greeting"] = normalized_greeting
            changed = True

        for key, value in default_config["options"].items():
            if key not in config["options"]:
                config["options"][key] = value
                changed = True

        for key, value in default_config["responses"].items():
            if key not in config["responses"]:
                config["responses"][key] = value
                changed = True

        if changed:
            logger.warning("menu_config.json fue completado con claves faltantes.")
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

        return config

    except FileNotFoundError:
        logger.info("Creando menu_config.json con valores por defecto...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config

    except json.JSONDecodeError as e:
        logger.error("menu_config.json corrupto: %s", e)
        logger.info("Regenerando menu_config.json con valores por defecto...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config


def save_menu_config(config: dict) -> None:
    now = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
    config.setdefault("revision", {"version": "1.0.0"})
    current_version = str(config["revision"].get("version", "1.0.0")).strip()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current_version)
    if match:
        major, minor, patch = map(int, match.groups())
        patch += 1
        if patch >= 100:
            patch = 0
            minor += 1
        if minor >= 100:
            minor = 0
            major += 1
        config["revision"]["version"] = f"{major}.{minor}.{patch}"
    else:
        config["revision"]["version"] = "1.0.1"
    config["revision"]["fecha"] = now.strftime("%d/%m/%Y")
    config["revision"]["hora"] = now.strftime("%H:%M:%S")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_unified_courses() -> dict:
    """
    Unifica los cursos de la API web con la configuración local.
    La API de la web tiene prioridad.
    """
    api_courses_raw = get_cached_courses() # Viene de la API de la web
    
    if not api_courses_raw:
        # Si la API falla, usamos los cursos del JSON como fallback
        return menu_config.get("cursos", {})

    unified_courses = {}
    for i, api_course in enumerate(api_courses_raw, 1):
        course_id = str(i)
        # El link de descarga ahora se obtendrá dinámicamente,
        # por lo que lo dejamos vacío aquí.
        unified_courses[course_id] = {
            "nombre": api_course.get("name", "Curso sin nombre"),
            "descripcion": api_course.get("short_description", ""),
            "link_web": f"https://cursala.com.ar/detalle-curso/{api_course.get('slug', '')}",
            "link_descarga": "", # Se obtendrá dinámicamente
            "vendedor_id": "1", # Se puede mantener o hacer más dinámico
        }
    
    return unified_courses

# ============================================================
# BACKUPS
# ============================================================

def list_backups() -> list:
    if not os.path.exists(BACKUPS_DIR):
        return []
    files = [f for f in os.listdir(BACKUPS_DIR) if f.endswith(".json")]
    return sorted(files, reverse=True)


def create_menu_backup(menu_config: dict) -> str:
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    timestamp = datetime.now(ZoneInfo("America/Argentina/Mendoza")).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.json"
    filepath = os.path.join(BACKUPS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(menu_config, f, ensure_ascii=False, indent=2)
    return filename


def restore_menu_backup(filename: str, menu_config_ref: list) -> bool:
    """Restaura backup. Modifica menu_config_ref[0] para actualizar el global."""
    filepath = os.path.join(BACKUPS_DIR, filename)
    if not os.path.exists(filepath):
        return False
    with open(filepath, "r", encoding="utf-8") as f:
        restored = json.load(f)
    menu_config_ref[0] = restored
    save_menu_config(restored)
    return True


# ============================================================
# PERSISTENCIA DE FORMULARIOS
# ============================================================

def save_profesional_interesado(registro: dict) -> None:
    try:
        if os.path.exists(INTERESADOS_PATH):
            with open(INTERESADOS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []
        data.append(registro)
        with open(INTERESADOS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Error guardando profesional interesado: %s", e)


def save_asesor_consulta(registro: dict) -> None:
    try:
        if os.path.exists(ASESOR_CONSULTAS_PATH):
            with open(ASESOR_CONSULTAS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []
        data.append(registro)
        with open(ASESOR_CONSULTAS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Error guardando consulta para asesor: %s", e)


def reorganize_course_ids(menu_config: dict) -> None:
    if not menu_config.get("cursos"):
        return
    cursos_ordenados = [
        menu_config["cursos"][key] for key in sorted(menu_config["cursos"].keys(), key=int)
    ]
    menu_config["cursos"] = {}
    for index, curso in enumerate(cursos_ordenados, 1):
        menu_config["cursos"][str(index)] = curso
    save_menu_config(menu_config)


# ============================================================
# HELPERS DE TRAZA Y CURSO
# ============================================================

def menu_trace(event: str, from_number: str, **details) -> None:
    safe_details = {key: value for key, value in details.items() if value is not None}
    logger.debug("MENU_TRACE event=%s from=%s details=%s", event, get_session_key(from_number), safe_details)


def course_session_snapshot(session: dict) -> dict:
    return {
        "active": session.get("active"),
        "pending_action": session.get("pending_action"),
        "in_course_menu": session.get("in_course_menu"),
        "in_course_detail": session.get("in_course_detail"),
        "current_course": session.get("current_course"),
    }


def parse_course_selection(text: str, menu_config: dict) -> Optional[str]:
    normalized_text = normalize_menu_command(text).lower()
    match = re.fullmatch(r"c\s*(\d+)", normalized_text)
    if not match:
        return None
    curso_id = match.group(1)
    if curso_id not in menu_config.get("cursos", {}):
        return None
    return curso_id


def parse_course_action_identifier(text: str, menu_config: dict) -> Optional[Tuple[str, str]]:
    normalized_text = normalize_menu_command(text).lower()
    match = re.fullmatch(r"course:(\d+):(view|syllabus|buy)", normalized_text)
    if not match:
        return None
    curso_id, action_name = match.groups()
    if curso_id not in menu_config.get("cursos", {}):
        return None
    action_mapping = {"view": "1", "syllabus": "2", "buy": "3"}
    return curso_id, action_mapping[action_name]


def resolve_course_detail_action(text: str, curso_id: str) -> str:
    normalized_text = normalize_menu_command(text)
    lowered_text = normalized_text.lower()
    button_mapping = {
        f"course:{curso_id}:view": "1",
        f"course:{curso_id}:syllabus": "2",
        f"course:{curso_id}:buy": "3",
        "ver curso": "1",
        "temario": "2",
        "comprar": "3",
    }
    return button_mapping.get(normalized_text, button_mapping.get(lowered_text, normalized_text))


def extract_message_text(msg: dict) -> Optional[str]:
    msg_type = msg.get("type")
    if msg_type == "text":
        return msg.get("text", {}).get("body", "").strip()
    if msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            return (reply.get("id") or reply.get("title") or "").strip()
        if interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            return (reply.get("id") or reply.get("title") or "").strip()
    return None


# ============================================================
# BUILDERS DE TEXTO (FALLBACK)
# ============================================================

def build_main_menu(menu_config: dict, include_greeting: bool = True, user_name: Optional[str] = None) -> str:
    lines = []
    if include_greeting:
        greeting_text = menu_config["greeting"]
        if user_name:
            greeting_text = f"{user_name},\n{greeting_text}"
        lines.extend([greeting_text, ""])
    lines.append("*MENU PRINCIPAL*")
    for key in sorted(menu_config["options"].keys(), key=int):
        lines.append(f"{key}. {menu_config['options'][key]}")
    lines.append("")
    lines.append("Espero tu respuesta...")
    return "\n".join(lines)


def build_courses_menu(menu_config: dict) -> str:
    cursos = get_unified_courses()
    if not cursos:
        return "No hay cursos disponibles en este momento."
    menu = "📚 CATALOGO DE CURSOS\n\nElegi el programa que queres explorar:\n\n"
    for key in sorted(cursos.keys(), key=int):
        menu += f"{key}. {cursos[key]['nombre']}\n"
    menu += "\n0. Volver al menu principal"
    return menu


def build_course_detail_menu(curso_id: str, menu_config: dict) -> str:
    if curso_id not in menu_config["cursos"]:
        return "Curso no encontrado."
    curso = menu_config["cursos"][curso_id]
    descripcion = curso.get("descripcion", "") or "Accede al contenido, al temario y a la orientacion comercial del programa."
    return (
        f"📘 *{curso['nombre'].upper()}*\n\n{descripcion}\n\n"
        "*Accesos disponibles*\n"
        "1. Ver curso\n2. Ver temario\n3. Hablar con asesor de inscripcion\n0. Volver al menu principal"
    )


def build_courses_edit_menu() -> str:
    return (
        "*GESTION DE CATALOGO*\n\n"
        "1. Agregar curso\n2. Eliminar curso\n3. Editar curso\n4. Ver cursos disponibles\n\n"
        "0. Volver al menu admin"
    )


def build_admin_menu() -> str:
    return (
        "*PANEL DE ADMINISTRACION*\n\n"
        "1. Ver menu actual\n2. Modificar saludo\n3. Editar opcion\n"
        "4. Agregar opcion\n5. Modificar respuesta\n6. Gestionar catalogo de cursos\n"
        "7. Gestionar asesores y vendedores\n8. Deshacer cambio\n9. Desactivar admin\n"
        "10. Gestionar backups\n11. Notificaciones por email\n12. Revisión\n"
        "13. Administracion de contactos\n14. Prompts de respuesta (Gemini)\n"
        "15. Mensajería masiva\n\n0. Volver al menu principal"
    )


def build_contacts_admin_menu() -> str:
    return (
        "*ADMINISTRACION DE CONTACTOS*\n\n"
        "1. Ver formato JSON esperado\n2. Ver instrucciones para importar backup\n"
        "3. Ver reglas de importacion (datos incompletos)\n\n"
        "4. Subir CSV o Excel (.xlsx) por WhatsApp\n\n5. Ver contactos guardados\n\n"
        "6. 📥 Descargar plantilla de contactos\n"
        "   Plantilla Excel para completar y subir\n\n"
        "7. \U0001f504 Recuperar contactos\n\n"
        "0. Volver al menu admin"
    )


def build_recovery_contacts_menu() -> str:
    return (
        "*\U0001f504 RECUPERACI\u00d3N DE CONTACTOS*\n\n"
        "1. Exportar TODO (Excel)\n"
        "   Descarga completa de contactos exportables.\n\n"
        "2. Exportar por ETIQUETA (Excel)\n"
        "   Eleg\u00eds etiqueta y exporta solo ese segmento.\n\n"
        "3. Exportar por FECHA (Excel)\n"
        "   Filtra por rango (desde/hasta).\n\n"
        "4. Instrucciones herramienta externa (Node.js)\n"
        "   C\u00f3mo recuperar contactos directamente de WhatsApp\n"
        "   Business con la herramienta local.\n\n"
        "0. Volver a Admin Contactos"
    )


def build_recovery_export_labels_menu(label_counts: list) -> str:
    if not label_counts:
        return (
            "⚠️ No hay etiquetas disponibles para exportación.\n\n"
            "0. Volver"
        )
    lines = ["*EXPORTAR POR ETIQUETA*", "", "Elegí una etiqueta:"]
    for idx, (label, count) in enumerate(label_counts, start=1):
        lines.append(f"{idx}. {label} ({count})")
    lines.extend(["", "0. Volver"])
    return "\n".join(lines)


def build_broadcast_menu() -> str:
    return (
        "*📣 MENSAJERÍA MASIVA*\n\n"
        "1. Enviar a TODOS los contactos\n2. Filtrar por etiqueta\n\n"
        "0. Volver al menú admin"
    )


def build_broadcast_msg_type_menu() -> str:
    return (
        "*TIPO DE MENSAJE*\n\n"
        "1. Mensaje personalizado (texto libre)\n2. Plantilla Meta (template aprobado)\n\n"
        "0. Volver"
    )


def build_broadcast_tag_list_message(tags: list) -> str:
    if not tags:
        return "⚠️ No se encontraron etiquetas en los contactos guardados."
    lines = ["*ETIQUETAS DISPONIBLES*\n"]
    for i, tag in enumerate(tags, start=1):
        lines.append(f"{i}. {tag}")
    lines.append("\nEscribí el número de la etiqueta que querés usar.")
    lines.append("0. Volver")
    return "\n".join(lines)


def build_empresa_confirmacion(data: dict) -> str:
    return (
        "*REVISIÓN DE SOLICITUD*\n\n*Acciones disponibles*\n"
        "1. Confirmar\n2. Ver datos\n0. Volver al menu principal"
    )


def build_empresa_datos_menu(data: dict) -> str:
    return (
        "*DATOS CARGADOS*\n\n"
        + build_labeled_data_block([
            ("Empresa", data.get("empresa", "")),
            ("CUIT", data.get("cuit", "")),
            ("Provincia", data.get("provincia", "")),
            ("Correo", data.get("correo", "")),
            ("Necesidades", data.get("necesidades", "")),
        ])
        + "\n\n*Acciones disponibles*\n"
        "1. Editar\n2. Enviar\n3. Volver a revisión\n0. Volver al menu principal"
    )


def build_empresa_editar_campos_menu() -> str:
    return (
        "*EDITAR DATOS DE SOLICITUD*\n\n"
        "1. Nombre de la empresa\n2. CUIT\n3. Provincia\n4. Correo\n5. Necesidades de formación\n\n"
        "0. Volver al menu principal"
    )


def build_profesional_confirmacion(data: dict) -> str:
    return (
        "*REVISION DE PERFIL DOCENTE*\n\n"
        + build_labeled_data_block([
            ("Nombre y apellido", data.get("nombre_apellido", "")),
            ("Nacionalidad", data.get("nacionalidad", "")),
            ("DNI", data.get("dni", "")),
            ("Curso a dictar", data.get("descripcion_curso", "")),
        ])
        + "\n\n*Acciones disponibles*\n"
        "C. Continuar con carga de CV\n1. Editar nombre y apellido\n"
        "2. Editar nacionalidad\n3. Editar DNI\n4. Editar descripcion del curso\n"
        "0. Volver al menu principal"
    )


def build_asesor_empresa_confirmacion(data: dict) -> str:
    return (
        "*REVISION DE CONTACTO EMPRESA*\n\n"
        + build_labeled_data_block([
            ("Empresa", data.get("empresa_nombre", "")),
            ("Correo", data.get("empresa_correo", "")),
            ("Email", data.get("empresa_email", "")),
            ("Motivo", data.get("motivo", "")),
        ])
        + "\n\n*Acciones disponibles*\n"
        "C. Confirmar y enviar\n1. Editar nombre de empresa\n2. Editar correo\n"
        "3. Editar email\n4. Editar motivo\n0. Volver al menu principal"
    )


def build_asesor_persona_confirmacion(data: dict) -> str:
    return (
        "*REVISIÓN DE CONTACTO PERSONAL*\n\n"
        + build_labeled_data_block([
            ("Nombre completo", data.get("nombre_completo", "")),
            ("DNI", data.get("dni", "")),
            ("Teléfono", data.get("telefono", "")),
            ("Correo", data.get("correo", "")),
            ("Motivo", data.get("motivo", "")),
        ])
        + "\n\n*Acciones disponibles*\n"
        "1. Confirmar y enviar\n2. Editar datos\n0. Volver al menu principal"
    )


def build_asesor_persona_edit_menu() -> str:
    return (
        "*¿Qué dato querés editar?*\n\n"
        "1. Nombre completo\n2. DNI\n3. Teléfono\n4. Correo\n5. Motivo\n\n"
        "0. Volver al menu principal"
    )


def build_vendor_menu() -> str:
    return (
        "*GESTIÓN DE VENDEDORES*\n\n"
        "1. Ver vendedores\n2. Agregar / Editar / Eliminar vendedor\n"
        "3. Asignar cursos a vendedor\n4. Ver asignaciones actuales\n\n"
        "0. Volver al menú admin"
    )


def build_vendor_list_message(menu_config: dict) -> str:
    vendedores = menu_config.get("vendedores", {})
    if not vendedores:
        return "No hay vendedores cargados."
    lines = ["*VENDEDORES CARGADOS*", ""]
    for vid in sorted(vendedores.keys(), key=int):
        v = vendedores[vid]
        nombre = f"{v.get('nombre', '')} {v.get('apellido', '')}".strip()
        correo = " ".join(str(v.get("correo", "")).strip().split())
        telefono_raw = " ".join(str(v.get("telefono", "")).strip().split())
        telefono = telefono_raw.lower() if telefono_raw else "n/a"
        lines.append(f"{vid}. *{nombre}*")
        lines.append("CORREO")
        lines.append(correo or "n/a")
        lines.append("TELÉFONO")
        lines.append(telefono)
        lines.append("")
    return "\n".join(lines)


def build_vendor_edit_fields_menu(vendor_id: str, menu_config: dict) -> str:
    vendedor = menu_config.get("vendedores", {}).get(vendor_id, {})
    nombre = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()
    return (
        f"*EDITAR VENDEDOR*\n\n"
        + build_labeled_data_block([
            ("Vendedor", f"{vendor_id}. {nombre}"),
            ("Correo actual", vendedor.get("correo", "")),
            ("Teléfono actual", vendedor.get("telefono", "")),
        ])
        + "\n\n¿Qué campo querés editar?\n"
        "1. Nombre completo\n2. Correo\n3. Telefono\n\n0. Volver"
    )


def build_vendor_courses_assignment_message(menu_config: dict) -> str:
    vendedores = menu_config.get("vendedores", {})
    cursos = menu_config.get("cursos", {})
    if not vendedores:
        return "No hay vendedores cargados."
    lines = ["*CURSOS ASIGNADOS POR VENDEDOR*", ""]
    for vid in sorted(vendedores.keys(), key=int):
        vendedor = vendedores[vid]
        nombre_vendedor = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()
        lines.append(f"{vid}. {nombre_vendedor}")
        cursos_asignados = []
        for cid in sorted(cursos.keys(), key=int):
            curso = cursos[cid]
            if vid in get_course_vendor_ids(curso, menu_config):
                cursos_asignados.append(f"- {curso.get('nombre', f'Curso {cid}')}")
        lines.extend(cursos_asignados if cursos_asignados else ["- (sin cursos asignados)"])
        lines.append("")
    lines.append("0. Volver")
    return "\n".join(lines)


def build_vendor_courses_toggle_message(vendor_id: str, menu_config: dict) -> str:
    vendedores = menu_config.get("vendedores", {})
    cursos = menu_config.get("cursos", {})
    vendedor = vendedores.get(vendor_id, {})
    nombre_v = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip()
    lines = [f"*ASIGNAR CURSOS — {nombre_v}*", ""]
    for cid in sorted(cursos.keys(), key=int):
        curso = cursos[cid]
        assigned = vendor_id in get_course_vendor_ids(curso, menu_config)
        mark = "✓" if assigned else "◦"
        lines.append(f"{cid}. [{mark}] {curso.get('nombre', f'Curso {cid}')}")
    lines.append("")
    lines.append("Ingresá el número del curso para asignar/quitar")
    lines.append("0. Volver")
    return "\n".join(lines)


def build_vendor_add_confirmation(vendor_draft: dict) -> str:
    return (
        "*REVISION DE VENDEDOR*\n\n"
        + build_labeled_data_block([
            ("Nombre completo", vendor_draft.get("full_name", "")),
            ("Correo", vendor_draft.get("correo", "")),
            ("Teléfono", vendor_draft.get("telefono", "")),
        ])
        + "\n\n1. Guardar\n2. Editar\n0. Cancelar"
    )


def build_backup_menu() -> str:
    backups = list_backups()
    count = len(backups)
    count_str = f"({count} backup{'s' if count != 1 else ''} guardado{'s' if count != 1 else ''})"
    return (
        f"*RESPALDOS Y RECUPERACION {count_str}*\n\n"
        "1. Crear backup de configuracion actual\n"
        "2. Ver o restaurar backup\n\n"
        "0. Volver al menu admin"
    )


def build_email_admin_menu(menu_config: dict) -> str:
    cfg = menu_config.get("email_notificacion_admin", {})
    estado = "✅ Activo" if cfg.get("activo", True) else "❌ Inactivo"
    destinatario = cfg.get("destinatario", "info@cursala.com.ar")
    asunto = cfg.get("asunto", "")
    cuerpo = cfg.get("cuerpo_intro", "")
    return (
        f"*NOTIFICACIONES POR EMAIL*\n\n"
        + build_labeled_data_block([
            ("Estado", estado),
            ("Destinatario", destinatario),
            ("Asunto", asunto),
            ("Intro", f"{cuerpo[:60]}{'...' if len(cuerpo) > 60 else ''}"),
        ])
        + "\n\n1. Activar/Desactivar\n2. Cambiar destinatario\n3. Editar asunto\n"
        "4. Editar texto de introducción\n\n0. Volver al menú admin"
    )


def get_gemini_prompt_rules(menu_config: dict) -> List[str]:
    rules = menu_config.get("gemini_prompt_rules", [])
    if not isinstance(rules, list):
        return []
    cleaned: List[str] = []
    for rule in rules:
        normalized_rule = " ".join(str(rule).split()).strip()
        if normalized_rule:
            cleaned.append(normalized_rule)
    return cleaned


def build_prompt_rules_admin_menu(menu_config: dict) -> str:
    total = len(get_gemini_prompt_rules(menu_config))
    return (
        "*PROMPTS DE RESPUESTA (GEMINI)*\n\n"
        f"Reglas activas: {total}\n\n"
        "1. Ver reglas activas\n2. Agregar regla\n3. Editar regla\n4. Eliminar regla\n\n"
        "0. Volver al menú admin"
    )


def build_prompt_rules_list_message(menu_config: dict) -> str:
    rules = get_gemini_prompt_rules(menu_config)
    if not rules:
        return "No hay reglas personalizadas cargadas todavía."
    lines = ["*REGLAS ACTIVAS PARA GEMINI*", ""]
    for idx, rule in enumerate(rules, start=1):
        lines.append(f"{idx}. {rule}")
    return "\n".join(lines)


def build_prompt_rules_select_message(action_label: str, menu_config: dict) -> str:
    rules = get_gemini_prompt_rules(menu_config)
    if not rules:
        return "No hay reglas cargadas para seleccionar."
    lines = [f"*{action_label.upper()} REGLA DE GEMINI*", ""]
    for idx, rule in enumerate(rules, start=1):
        snippet = rule if len(rule) <= 110 else rule[:107] + "..."
        lines.append(f"{idx}. {snippet}")
    lines.append("")
    lines.append("0. Volver")
    return "\n".join(lines)


def build_gemini_prompt_rules_block(menu_config: dict) -> str:
    rules = get_gemini_prompt_rules(menu_config)
    if not rules:
        return ""
    lines = [
        "REGLAS PERSONALIZADAS DEL NEGOCIO (ALTA PRIORIDAD):",
        "- Cumplí estas reglas de forma estricta antes de responder.",
    ]
    for rule in rules:
        lines.append(f"- {rule}")
    return "\n".join(lines) + "\n\n"


def build_runtime_revision_message(menu_config: dict) -> str:
    runtime_service = K_SERVICE or "local"
    runtime_revision = K_REVISION or "local-dev"
    runtime_configuration = K_CONFIGURATION or "local"
    menu_revision = menu_config.get("revision", {}) if isinstance(menu_config, dict) else {}
    menu_version = menu_revision.get("version", "1.0.0")
    menu_fecha = menu_revision.get("fecha", "—")
    menu_hora = menu_revision.get("hora", "—")
    return (
        "*REVISIÓN DEL SISTEMA*\n\n"
        + build_labeled_data_block([
            ("App version", APP_VERSION),
            ("Servicio runtime", runtime_service),
            ("Revisión deploy", runtime_revision),
            ("Configuración deploy", runtime_configuration),
        ])
        + "\n\n*REVISIÓN DE MENÚ / CONFIG*\n\n"
        + build_labeled_data_block([
            ("Versión menú", menu_version),
            ("Fecha último cambio menú", menu_fecha),
            ("Hora último cambio menú", menu_hora),
        ])
        + "\n\n0. Volver al menú admin"
    )


# ============================================================
# HELPERS DE VENDEDOR
# ============================================================

def get_course_vendor_ids(curso: dict, menu_config: dict) -> List[str]:
    vendor_ids: List[str] = []
    listed = curso.get("vendedor_ids")
    if isinstance(listed, list):
        for vid in listed:
            if isinstance(vid, str) and vid and vid not in vendor_ids:
                vendor_ids.append(vid)
    primary = curso.get("vendedor_id")
    if isinstance(primary, str) and primary and primary not in vendor_ids:
        vendor_ids.append(primary)
    valid_vendors = menu_config.get("vendedores", {})
    return [vid for vid in vendor_ids if vid in valid_vendors]


def choose_vendor_for_course(curso: dict, menu_config: dict) -> dict:
    vendor_ids = get_course_vendor_ids(curso, menu_config)
    vendedores = menu_config.get("vendedores", {})
    if not vendor_ids and vendedores:
        vendor_ids = [sorted(vendedores.keys(), key=int)[0]]
    candidates = [vendedores.get(vid, {}) for vid in vendor_ids if vid in vendedores]
    if not candidates:
        return {}
    with_phone = [v for v in candidates if normalize_number(v.get("telefono", ""))]
    pool = with_phone or candidates
    return random.choice(pool)


def build_vendor_whatsapp_url(vendedor: dict, curso_nombre: str) -> str:
    phone_digits = normalize_number(vendedor.get("telefono", ""))
    if not phone_digits:
        return ""
    prefilled = quote(f"Hola, quiero informacion para inscribirme al curso {curso_nombre}.")
    return f"https://wa.me/{phone_digits}?text={prefilled}"


def build_asesores_contacto_message(menu_config: dict, prefilled_text: str = "Hola, quiero hablar con un asesor de Cursala.") -> str:
    vendedores = menu_config.get("vendedores", {})
    if not vendedores:
        return (
            "*COMUNICATE CON NUESTROS ASESORES*\n\n"
            "No hay asesores cargados en este momento."
        )
    lines = ["*COMUNICATE CON NUESTROS ASESORES*"]
    valid_count = 0
    prefilled = quote(prefilled_text)
    for vid in sorted(vendedores.keys(), key=int):
        vendedor = vendedores.get(vid, {})
        nombre = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip() or f"Asesor {vid}"
        phone_digits = normalize_number(vendedor.get("telefono", ""))
        asesor_data = [("Nombre", nombre)]
        if phone_digits:
            valid_count += 1
            whatsapp_link = f"https://wa.me/{phone_digits}?text={prefilled}"
            asesor_data.append(("Telefonico", whatsapp_link))
        else:
            asesor_data.append(("Telefonico", "no disponible"))
        lines.append("\n" + build_labeled_data_block(asesor_data))
    if valid_count == 0:
        lines.append("\nNo hay telefonos disponibles para contacto inmediato.")
    else:
        lines.append("\nComunicate directamente con nuestros asesores o escribinos para mas informacion.")
    return "".join(lines).strip()


# ============================================================
# BROADCAST
# ============================================================

def execute_broadcast_send(
    contacts: list,
    msg_type: str,
    message: str,
    template_name: str,
    template_lang: str,
) -> dict:
    enviados = 0
    fallidos = 0
    errores = []

    for contact in contacts:
        telefono = contact.get("telefono", "")
        nombre = contact.get("nombre", "") or ""
        bsuid = contact.get("bsuid", "") or ""

        if telefono:
            destino = f"+{telefono}" if not str(telefono).startswith("+") else str(telefono)
        elif bsuid:
            destino = bsuid
        else:
            fallidos += 1
            errores.append(f"Sin destino para contacto {contact}")
            continue

        try:
            if msg_type == "text":
                body = message.replace("{nombre}", nombre or "estimado/a")
                payload = {"type": "text", "text": {"body": body}}
            else:
                components = []
                if nombre:
                    components.append({
                        "type": "body",
                        "parameters": [{"type": "text", "text": nombre}],
                    })
                payload = {
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": template_lang},
                        "components": components,
                    },
                }
            ok = enviar_payload_whatsapp(destino, payload, f"Broadcast a {destino}")
            if ok:
                enviados += 1
            else:
                fallidos += 1
                errores.append(f"Error API: {destino}")
        except Exception as e:
            fallidos += 1
            errores.append(f"Excepción {destino}: {str(e)[:40]}")

        time.sleep(0.35)

    return {"enviados": enviados, "fallidos": fallidos, "errores": errores[:5]}


# ============================================================
# DETALLE DE CURSOS (CTA)
# ============================================================

def enviar_detalle_curso_cta_url(to_number: str, curso_id: str, menu_config: dict) -> bool:
    curso = menu_config["cursos"].get(curso_id)
    if not curso:
        return False
    descripcion = curso.get("descripcion", "") or "Encontrá toda la información del curso en los accesos rápidos."
    nombre = curso.get("nombre", "Curso")

    sent_view = enviar_curso_cta_url_boton(
        to_number, curso_id, "VER CURSO", curso.get("link_web", ""),
        f"📘 *{nombre}*\n\n{descripcion}", "Acceso directo al curso",
    )
    if not sent_view:
        return False

    sent_syllabus = enviar_curso_cta_url_boton(
        to_number, curso_id, "TEMARIO", curso.get("link_descarga", ""),
        f"📘 *{nombre}*\n\nAbri el programa completo desde este boton.", "Acceso directo al temario",
    )
    if not sent_syllabus:
        return False

    enviar_respuesta(
        to_number,
        "Si querés hablar con un asesor para comprar este curso, escribí 3. Para volver al inicio, escribí 0."
    )
    return True


def enviar_detalle_curso(to_number: str, curso_id: str, menu_config: dict) -> None:
    menu_trace("course_detail_send_enter", to_number, curso_id=curso_id)
    curso = menu_config["cursos"].get(curso_id)
    if not curso:
        enviar_respuesta(to_number, "Curso no encontrado.")
        return
    menu_trace("course_detail_send_list_menu", to_number, curso_id=curso_id)
    sent = enviar_menu_detalle_curso_lista(to_number, curso_id, menu_config)
    if not sent:
        enviar_respuesta(to_number, build_course_detail_menu(curso_id, menu_config))


def send_course_option_single_card(
    from_number: str,
    curso_id: str,
    button_label: str,
    button_url: str,
    trace_label: str,
    menu_config: dict,
) -> None:
    curso = menu_config["cursos"].get(curso_id, {})
    sent_cta = enviar_curso_cta_url_boton(
        from_number, curso_id, button_label, button_url,
        f"📘 *{curso.get('nombre', 'Curso')}*",
    )
    if sent_cta:
        menu_trace("course_action_cta_sent", from_number, curso_id=curso_id, label=trace_label)
        return
    logger.warning("CTA URL fallo para %s. curso_id=%s", trace_label, curso_id)
    sent_template = course_url_template_enabled() and enviar_detalle_curso_template_url(from_number, curso_id, menu_config)
    if sent_template:
        menu_trace("course_action_template_sent", from_number, curso_id=curso_id, label=trace_label)
        return
    logger.warning("Template fallback fallo para %s. curso_id=%s", trace_label, curso_id)
    enviar_respuesta(from_number, "No pude generar el botón del curso en este momento. Te vuelvo a mostrar las opciones.")
    enviar_detalle_curso(from_number, curso_id, menu_config)


def handle_course_detail_action(
    from_number: str,
    curso_id: str,
    action: str,
    menu_config: dict,
    session: dict,
) -> None:
    from bot.state_manager import reset_user_flow
    menu_trace(
        "course_action_enter", from_number, curso_id=curso_id, action=action,
        session=course_session_snapshot(session),
    )

    if action == "0":
        reset_user_flow(session)
        menu_trace("course_action_home", from_number, curso_id=curso_id, action=action)
        enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        return

    curso = menu_config["cursos"].get(curso_id, {})

    if action == "1":
        send_course_option_single_card(
            from_number, curso_id, "VER CURSO", curso.get("link_web", ""), "VER CURSO", menu_config,
        )
        enviar_respuesta(
            from_number,
            "Si querés volver al menú principal, escribí 0.\n"
            "Si querés seguir en este curso, elegí 1, 2 o 3.",
        )
        return

    if action == "2":
        send_course_option_single_card(
            from_number, curso_id, "VER PROGRAMA", curso.get("link_descarga", ""), "VER PROGRAMA", menu_config,
        )
        enviar_respuesta(
            from_number,
            "Si querés volver al menú principal, escribí 0.\n"
            "Si querés seguir en este curso, elegí 1, 2 o 3.",
        )
        return

    if action == "3":
        vendedor = choose_vendor_for_course(curso, menu_config)
        asesor_url = build_vendor_whatsapp_url(vendedor, curso.get("nombre", "Curso"))
        if asesor_url:
            send_course_option_single_card(
                from_number, curso_id, "HABLAR CON ASESOR", asesor_url, "HABLAR CON ASESOR", menu_config,
            )
        else:
            enviar_respuesta(
                from_number,
                "No pude generar el boton del asesor para este curso.\n\n"
                + build_asesores_contacto_message(
                    menu_config,
                    f"Hola, quiero informacion para inscribirme al curso {curso.get('nombre', 'Curso')}.",
                )
            )
            enviar_respuesta(
                from_number,
                "Si queres volver al menu principal, escribi 0.\n"
                "Si queres seguir en este curso, elegi 1, 2 o 3.",
            )
        return

    enviar_respuesta(from_number, "Opción inválida. Elegí VER CURSO, TEMARIO, COMPRAR o 0.")
    enviar_detalle_curso(from_number, curso_id, menu_config)


# ============================================================
# SECCION 9B — MENUS INTERACTIVOS TIPO LISTA
# ============================================================

def _truncar_titulo_lista(text: str, max_len: int = 24) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def enviar_menu_principal_lista(
    to_number: str,
    menu_config: dict,
    include_greeting: bool = True,
    user_name: Optional[str] = None,
) -> bool:
    options = menu_config.get("options", {})
    rows = []
    for key in sorted(options.keys(), key=int):
        rows.append({"id": key, "title": _truncar_titulo_lista(options[key])})
    if not rows:
        enviar_respuesta(to_number, build_main_menu(menu_config, include_greeting=include_greeting, user_name=user_name))
        return False
    sections = [{"title": "Opciones", "rows": rows}]
    greeting = (menu_config.get("greeting") or "¿Cómo podemos ayudarte hoy?").strip()
    if user_name and include_greeting:
        body = f"{user_name}, {greeting}"
    elif include_greeting:
        body = greeting
    else:
        body = "¿Cómo podemos ayudarte?"
    sent = enviar_lista_interactiva(to_number, body, sections, "Ver opciones", "MENÚ PRINCIPAL")
    if not sent:
        enviar_respuesta(to_number, build_main_menu(menu_config, include_greeting=include_greeting, user_name=user_name))
    return sent


def enviar_menu_cursos_lista(to_number: str, menu_config: dict, page: int = 0) -> bool:
    PAGE_SIZE = 5
    cursos = get_unified_courses()
    if not cursos:
        enviar_respuesta(to_number, build_courses_menu(menu_config))
        return False
    keys_sorted = sorted(cursos.keys(), key=int)
    start = page * PAGE_SIZE
    page_keys = keys_sorted[start: start + PAGE_SIZE]
    has_more = (start + PAGE_SIZE) < len(keys_sorted)
    rows = []
    for key in page_keys:
        nombre = cursos[key].get("nombre", f"Curso {key}")
        descripcion = (cursos[key].get("descripcion") or "")[:72]
        row: dict = {"id": key, "title": _truncar_titulo_lista(nombre)}
        if descripcion:
            row["description"] = descripcion
        rows.append(row)
    if has_more:
        rows.append({"id": "ver_mas_cursos", "title": "Ver más cursos ▶"})
    rows.append({"id": "0", "title": "Volver al menú"})
    section_title = "Más programas" if page > 0 else "Programas disponibles"
    sections = [{"title": section_title, "rows": rows}]
    sent = enviar_lista_interactiva(to_number, "Elegí el programa que querés explorar:", sections, "Ver cursos", "CATÁLOGO DE CURSOS")
    if not sent:
        enviar_respuesta(to_number, build_courses_menu(menu_config))
    return sent


def enviar_menu_detalle_curso_lista(to_number: str, curso_id: str, menu_config: dict) -> bool:
    curso = menu_config.get("cursos", {}).get(curso_id)
    if not curso:
        enviar_respuesta(to_number, "Curso no encontrado.")
        return False
    nombre = curso.get("nombre", "Curso")
    descripcion = curso.get("descripcion") or "Accedé al contenido, temario y orientación comercial."
    body_text = f"*{nombre.upper()}*\n\n{descripcion}"
    rows = [
        {"id": "1", "title": "Ver curso"},
        {"id": "2", "title": "Ver programa/temario"},
        {"id": "3", "title": "Hablar con asesor"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Opciones del curso", "rows": rows}]
    sent = enviar_lista_interactiva(
        to_number, body_text[:1024], sections, "Elegí una opción",
        _truncar_titulo_lista(nombre.upper(), 60),
    )
    if not sent:
        enviar_respuesta(to_number, build_course_detail_menu(curso_id, menu_config))
    return sent


def enviar_menu_tipo_asesor_lista(
    to_number: str,
    body_text: Optional[str] = None,
    header_text: str = "CONTACTO CON ASESOR",
    fallback_text: Optional[str] = None,
) -> bool:
    rows = [
        {"id": "1", "title": "Empresa"},
        {"id": "2", "title": "Persona física"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Tipo de consulta", "rows": rows}]
    body = body_text or "Para hablar con un asesor, elegí el tipo de consulta:"
    fallback = fallback_text or "Para hablar con un asesor:\n\n1. EMPRESA\n2. PERSONA FÍSICA\n\n0. Volver"
    sent = enviar_lista_interactiva(
        to_number,
        body,
        sections, "Elegí una opción", header_text,
    )
    if not sent:
        enviar_respuesta(to_number, fallback)
    return sent


def enviar_menu_empresa_confirmacion_lista(to_number: str, data: dict) -> bool:
    rows = [
        {"id": "1", "title": "Confirmar solicitud"},
        {"id": "2", "title": "Ver datos cargados"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Acciones", "rows": rows}]
    sent = enviar_lista_interactiva(
        to_number, "Revisá tu solicitud y elegí una acción:", sections, "Elegí una opción", "REVISIÓN DE SOLICITUD",
    )
    if not sent:
        enviar_respuesta(to_number, build_empresa_confirmacion(data))
    return sent


def enviar_menu_empresa_datos_lista(to_number: str, data: dict) -> bool:
    empresa = (data.get("empresa") or "").strip()
    cuit = (data.get("cuit") or "").strip()
    body = f"Empresa: {empresa}\nCUIT: {cuit}\n\n¿Qué querés hacer?"
    rows = [
        {"id": "1", "title": "Editar datos"},
        {"id": "2", "title": "Enviar solicitud"},
        {"id": "3", "title": "Volver a revisión"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Acciones", "rows": rows}]
    sent = enviar_lista_interactiva(to_number, body[:1024], sections, "Elegí una opción", "DATOS CARGADOS")
    if not sent:
        enviar_respuesta(to_number, build_empresa_datos_menu(data))
    return sent


def enviar_menu_empresa_editar_lista(to_number: str) -> bool:
    rows = [
        {"id": "1", "title": "Nombre de empresa"},
        {"id": "2", "title": "CUIT"},
        {"id": "3", "title": "Provincia"},
        {"id": "4", "title": "Correo"},
        {"id": "5", "title": "Necesidades"},
        {"id": "0", "title": "Volver"},
    ]
    sections = [{"title": "Campos disponibles", "rows": rows}]
    sent = enviar_lista_interactiva(to_number, "¿Qué campo querés editar?", sections, "Elegí un campo", "EDITAR SOLICITUD")
    if not sent:
        enviar_respuesta(to_number, build_empresa_editar_campos_menu())
    return sent


def enviar_menu_profesional_confirmacion_lista(to_number: str, data: dict) -> bool:
    nombre = (data.get("nombre_apellido") or "").strip()
    body = f"Perfil: {nombre}\n¿Qué querés hacer?" if nombre else "Revisá tu perfil docente."
    rows = [
        {"id": "c", "title": "Continuar con CV"},
        {"id": "1", "title": "Editar nombre/apellido"},
        {"id": "2", "title": "Editar nacionalidad"},
        {"id": "3", "title": "Editar DNI"},
        {"id": "4", "title": "Editar desc. del curso"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Opciones", "rows": rows}]
    sent = enviar_lista_interactiva(to_number, body[:1024], sections, "Elegí una opción", "PERFIL DOCENTE")
    if not sent:
        enviar_respuesta(to_number, build_profesional_confirmacion(data))
    return sent


def enviar_menu_asesor_empresa_confirmacion_lista(to_number: str, data: dict) -> bool:
    empresa = (data.get("empresa_nombre") or "").strip()
    body = f"Empresa: {empresa}\n¿Qué querés hacer?" if empresa else "Revisá los datos antes de enviar."
    rows = [
        {"id": "c", "title": "Confirmar y enviar"},
        {"id": "1", "title": "Editar nombre empresa"},
        {"id": "2", "title": "Editar correo"},
        {"id": "3", "title": "Editar email"},
        {"id": "4", "title": "Editar motivo"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Acciones", "rows": rows}]
    sent = enviar_lista_interactiva(to_number, body[:1024], sections, "Elegí una opción", "REVISIÓN EMPRESA")
    if not sent:
        enviar_respuesta(to_number, build_asesor_empresa_confirmacion(data))
    return sent


def enviar_menu_asesor_persona_confirmacion_lista(to_number: str, data: dict) -> bool:
    nombre = (data.get("nombre_completo") or "").strip()
    body = f"Contacto: {nombre}\n¿Qué querés hacer?" if nombre else "Revisá los datos antes de enviar."
    rows = [
        {"id": "1", "title": "Confirmar y enviar"},
        {"id": "2", "title": "Editar datos"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Acciones", "rows": rows}]
    sent = enviar_lista_interactiva(to_number, body[:1024], sections, "Elegí una opción", "CONFIRMACIÓN CONTACTO")
    if not sent:
        enviar_respuesta(to_number, build_asesor_persona_confirmacion(data))
    return sent


def enviar_menu_asesor_persona_editar_lista(to_number: str) -> bool:
    rows = [
        {"id": "1", "title": "Nombre completo"},
        {"id": "2", "title": "DNI"},
        {"id": "3", "title": "Teléfono"},
        {"id": "4", "title": "Correo"},
        {"id": "5", "title": "Motivo"},
        {"id": "0", "title": "Volver al menú"},
    ]
    sections = [{"title": "Campos disponibles", "rows": rows}]
    sent = enviar_lista_interactiva(to_number, "¿Qué dato querés editar?", sections, "Elegí un campo", "EDITAR DATOS")
    if not sent:
        enviar_respuesta(to_number, build_asesor_persona_edit_menu())
    return sent


def enviar_menu_admin_lista(to_number: str) -> bool:
    # Meta limita a 10 rows totales. Opciones 3,4,5,8,10,11 siguen disponibles
    # escribiendo el número directamente (el fallback de texto las muestra todas).
    sections = [
        {
            "title": "Principal",
            "rows": [
                {"id": "1", "title": "Ver menú actual"},
                {"id": "2", "title": "Modificar saludo"},
                {"id": "13", "title": "Admin de contactos"},
                {"id": "14", "title": "Prompts Gemini"},
                {"id": "15", "title": "Mensajería masiva"},
            ],
        },
        {
            "title": "Gestión",
            "rows": [
                {"id": "6", "title": "Catálogo de cursos"},
                {"id": "7", "title": "Asesores y vendedores"},
                {"id": "9", "title": "Desactivar admin"},
                {"id": "10", "title": "Gestionar backups"},
                {"id": "12", "title": "Revisión del deploy"},
                {"id": "0", "title": "Volver al menú usuario"},
            ],
        },
    ]
    sent = enviar_lista_interactiva(to_number, "¿Qué querés hacer?", sections, "Elegí una opción", "PANEL ADMIN")
    if not sent:
        enviar_respuesta(to_number, build_admin_menu())
    return sent


def enviar_menu_cursos_edit_lista(to_number: str) -> bool:
    rows = [
        {"id": "1", "title": "Agregar curso"},
        {"id": "2", "title": "Eliminar curso"},
        {"id": "3", "title": "Editar curso"},
        {"id": "4", "title": "Ver cursos disponibles"},
        {"id": "0", "title": "Volver al menú admin"},
    ]
    sections = [{"title": "Acciones", "rows": rows}]
    sent = enviar_lista_interactiva(
        to_number, "¿Qué querés hacer con el catálogo?", sections, "Elegí una opción", "CATÁLOGO DE CURSOS",
    )
    if not sent:
        enviar_respuesta(to_number, build_courses_edit_menu())
    return sent


def enviar_menu_contacts_admin_lista(to_number: str) -> bool:
    rows = [
        {"id": "1", "title": "Ver formato JSON"},
        {"id": "2", "title": "Instrucciones importar"},
        {"id": "3", "title": "Reglas de importación"},
        {"id": "4", "title": "Subir archivo CSV/Excel"},
        {"id": "5", "title": "Ver contactos guardados"},
        {"id": "6", "title": "Recuperar contactos"},
        {"id": "0", "title": "Volver al menú admin"},
    ]
    sections = [{"title": "Opciones", "rows": rows}]
    sent = enviar_lista_interactiva(to_number, "¿Qué querés hacer?", sections, "Elegí una opción", "ADMIN CONTACTOS")
    if not sent:
        enviar_respuesta(to_number, build_contacts_admin_menu())
    return sent


def enviar_menu_recovery_contacts_lista(to_number: str) -> bool:
    rows = [
        {"id": "1", "title": "Exportar Excel contactos"},
        {"id": "2", "title": "Instrucciones externas"},
        {"id": "0", "title": "Volver a Admin Contactos"},
    ]
    sections = [{"title": "Opciones", "rows": rows}]
    sent = enviar_lista_interactiva(
        to_number, "¿Qué querés hacer?", sections, "Elegí una opción", "RECUPERAR CONTACTOS"
    )
    if not sent:
        enviar_respuesta(to_number, build_recovery_contacts_menu())
    return sent


# ---------------------------------------------------------------------------
# Module-level global — loaded at import time, mutated by flow_admin.py
# ---------------------------------------------------------------------------
menu_config: dict = {}
try:
    menu_config = load_menu_config()
except Exception as _e:
    logger.error("Error loading menu_config at startup: %s", _e)
    menu_config = {
        "greeting": "Hola, soy el asistente de Cursala.",
        "options": {}, "responses": {}, "cursos": {},
        "vendedores": {}, "email_notificacion_admin": {}, "gemini_prompt_rules": [],
    }
