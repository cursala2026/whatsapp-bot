"""bot/state_manager.py — Estado en memoria: sesiones, onboarding, reset de flujo.

Importa de bot.config y bot.utils. No importa otros módulos de bot/ para
evitar imports circulares. Las funciones que necesitan enviar mensajes o
acceder a menus viven en flow_user.py.
"""

import time
from typing import Dict

from bot.utils import get_session_key, sanitize_contact_name


# ============================================================
# ESTADO GLOBAL EN MEMORIA
# ============================================================

admin_sessions: Dict[str, dict] = {}


def get_admin_session(number: str) -> dict:
    key = get_session_key(number)
    if key not in admin_sessions:
        admin_sessions[key] = {
            "active": False,
            "awaiting_admin_password": False,
            "in_course_menu": False,
            "in_course_detail": False,
            "in_courses_edit_menu": False,
            "in_response_menu": False,
            "current_course": None,
            "awaiting_confirmation": False,
            "pending_action": None,
            "pending_change": None,
            "change_history": [],
            "temp_option": None,
            "temp_option_text": None,
            "temp_field": None,
            "temp_course_data": {},
            "temp_prof_data": {},
            "temp_asesor_data": {},
            "temp_course_field_index": 0,
            "last_response_option": None,
            "gemini_history": [],
            "notificacion_admin_enviada": False,
            "user_name": "",
            "post_onboarding_command": None,
            "last_interaction_at": time.time(),
            "bsuid": None,
        }
    return admin_sessions[key]


def reset_user_flow(session: dict) -> None:
    session["in_course_menu"] = False
    session["in_course_detail"] = False
    session["in_courses_edit_menu"] = False
    session["in_response_menu"] = False
    session["current_course"] = None
    session["pending_action"] = None
    session["temp_option"] = None
    session["temp_option_text"] = None
    session["temp_field"] = None
    session["temp_course_data"] = {}
    session["temp_prof_data"] = {}
    session["temp_asesor_data"] = {}
    session["last_response_option"] = None
    session["post_onboarding_command"] = None


def get_saved_contact_name(_from_number: str, session: dict) -> str:
    return sanitize_contact_name(session.get("user_name", ""))


def apply_contact_name_to_message(to_number: str, message: str) -> str:
    session = get_admin_session(to_number)
    user_name = sanitize_contact_name(session.get("user_name", ""))
    if not user_name:
        return message
    first_line = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    if user_name.lower() in first_line.lower():
        return message
    return f"{user_name},\n{message}"
