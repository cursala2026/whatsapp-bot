"""bot/flow_user.py — Maquina de estados del usuario final.

Responsabilidades:
- Orquestar onboarding, menu principal y subflujos (empresa/profesional/asesor).
- Responder texto libre via Gemini cuando el fallback esta habilitado.
- Disparar persistencia y notificaciones en background para reducir latencia.

Este modulo es el nucleo conversacional del usuario final.
"""

import time
import threading
import random
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from bot.config import (
    logger,
    ENABLE_GEMINI_FALLBACK,
    GEMINI_MODEL,
    CV_UPLOAD_URL,
    FIRESTORE_COLLECTION,
    USER_INACTIVITY_TIMEOUT_SECONDS,
    gemini_client,
)
from bot.utils import (
    normalize_number,
    normalize_menu_command,
    normalize_text_for_filter,
    sanitize_contact_name,
    saludo_por_horario,
    is_admin,
)
from bot.utils import (
    validar_correo,
    validar_nombre_empresa,
    validar_solo_numeros,
    validar_provincia,
    validar_texto_sin_numeros,
    validar_dni,
    validar_telefono,
)
from bot.database import (
    firestore_db,
    upsert_user_profile_firestore as _upsert_sync,
    track_user_interest as _track_sync,
)
from bot.state_manager import (
    admin_sessions,
    get_admin_session,
    reset_user_flow,
    get_saved_contact_name,
)
from bot.menus import (
    menu_config,
    menu_trace,
    course_session_snapshot,
    parse_course_selection,
    parse_course_action_identifier,
    resolve_course_detail_action,
    handle_course_detail_action,
    enviar_detalle_curso,
    save_profesional_interesado,
    save_asesor_consulta,
    build_asesores_contacto_message,
    build_gemini_prompt_rules_block,
    build_labeled_data_block,
    get_unified_courses,
    enviar_menu_principal_lista,
    enviar_menu_cursos_lista,
    enviar_menu_tipo_asesor_lista,
    enviar_menu_empresa_confirmacion_lista,
    enviar_menu_empresa_datos_lista,
    enviar_menu_empresa_editar_lista,
    enviar_menu_profesional_confirmacion_lista,
    enviar_menu_asesor_empresa_confirmacion_lista,
    enviar_menu_asesor_persona_confirmacion_lista,
    enviar_menu_asesor_persona_editar_lista,
)
from bot.whatsapp_api import enviar_respuesta, enviar_payload_whatsapp

from email_service import (
    enviar_correo_brevo,
    procesar_notificacion_registro,
    enviar_notificacion_evento,
)


# Evita asignar dos alertas seguidas al mismo vendedor (estado en memoria de proceso).
_last_vendor_alert_id: Optional[str] = None

# ============================================================
# HELPERS DE BACKGROUND — todas las escrituras analíticas son fire-and-forget
# ============================================================

def _bg(fn, *args, **kwargs) -> None:
    """Ejecuta fn en un hilo daemon sin bloquear la respuesta al usuario."""
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def upsert_user_profile_firestore(*args, **kwargs) -> None:
    """Versión background: no bloquea el flujo principal."""
    _bg(_upsert_sync, *args, **kwargs)


def track_user_interest(*args, **kwargs) -> None:
    """Versión background: no bloquea el flujo principal."""
    _bg(_track_sync, *args, **kwargs)


# ============================================================
# GEMINI — DETECCION Y RESPUESTA
# ============================================================

def _detectar_intereses_gemini(user_message: str, from_number: str) -> None:
    """Detecta menciones de cursos en el mensaje libre y los registra en Firestore."""
    msg_normalized = normalize_text_for_filter(user_message)
    detectados = []
    cursos = get_unified_courses()
    for c in cursos.values():
        nombre = c.get("nombre", "")
        if nombre and normalize_text_for_filter(nombre) in msg_normalized:
            detectados.append(nombre)
    if detectados:
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            telefono=from_number,
            intereses=detectados,
            evento="gemini_interes_detectado",
        )


def detect_course_interest_labels(user_message: str) -> List[str]:
    """Detecta cursos mencionados en texto libre para etiquetar el contacto."""
    normalized_msg = normalize_text_for_filter(user_message)
    labels: List[str] = []
    cursos = get_unified_courses()
    for curso in cursos.values():
        nombre = " ".join(str(curso.get("nombre", "")).strip().split())
        if not nombre:
            continue
        if normalize_text_for_filter(nombre) in normalized_msg:
            labels.append(nombre)
    return labels


def audio_requests_advisor(user_message: str) -> bool:
    """Detecta pedidos de contacto humano/asesor en texto o audio transcripto."""
    normalized_msg = normalize_text_for_filter(user_message)
    advisor_phrases = [
        "hablar con un asesor",
        "hablar con asesor",
        "hablr con un asesor",
        "hablr con asesor",
        "quiero hablar con un asesor",
        "quiero hablar con asesor",
        "quiero hablr con un asesor",
        "quiero hablr con asesor",
        "comunicarme con un asesor",
        "necesito comunicarme con un asesor",
        "necesito comunicarme con alguien",
        "pasame con un asesor",
        "pasame con alguien",
        "derivame con un asesor",
        "quiero que me contacte un asesor",
        "quiero que alguien se contacte conmigo",
        "quiero que alguien me contacte",
        "necesito que alguien me contacte",
        "necesito hablar con una persona",
        "quiero hablar con una persona",
        "quiero hablar con alguien",
        "quiero comunicarme con una persona",
        "hablar con ventas",
        "comunicarme con ventas",
        "hablar con un vendedor",
        "comunicarme con un vendedor",
        "contacto con un asesor",
        "asesor comercial",
    ]
    if any(phrase in normalized_msg for phrase in advisor_phrases):
        return True

    # Heurística flexible: verbo de contacto + objetivo humano/comercial.
    contact_verbs = (
        "hablar", "hablr", "comunicar", "contact", "llamar", "derivar", "pasame",
        "pasar", "atender", "atencion", "asesor",
    )
    human_targets = (
        "asesor", "asesora", "vendedor", "ventas", "persona", "humano", "alguien",
        "agente", "representante", "equipo comercial",
    )

    has_contact_verb = any(token in normalized_msg for token in contact_verbs)
    has_human_target = any(token in normalized_msg for token in human_targets)
    return has_contact_verb and has_human_target


def iniciar_flujo_asesor(from_number: str, session: dict, via_audio: bool = False) -> None:
    session["temp_asesor_data"] = {}
    session["pending_action"] = "asesor_tipo"
    session["in_response_menu"] = False
    session["last_response_option"] = None
    session["advisor_flow_from_audio"] = bool(via_audio)
    track_user_interest(from_number, "hablar_con_asesor", "menu_opcion_4", etiqueta_cliente="interesado_asesoria")

    if via_audio:
        enviar_menu_tipo_asesor_lista(
            from_number,
            body_text=(
                "Perfecto. Te voy a derivar con el equipo de asesoramiento de Cursala.\n\n"
                "Para orientarte mejor desde el inicio, indicame si tu consulta corresponde a una empresa o a una persona."
            ),
            header_text="ASESORAMIENTO PERSONALIZADO",
            fallback_text=(
                "Perfecto. Te voy a derivar con el equipo de asesoramiento de Cursala.\n\n"
                "Indicame el tipo de consulta:\n\n"
                "1. EMPRESA\n"
                "2. PERSONA FÍSICA\n\n"
                "0. Volver al menú"
            ),
        )
        return

    enviar_menu_tipo_asesor_lista(from_number)


def _build_contacto_inmediato_text(vendedor_contacto: Optional[dict]) -> str:
    if not vendedor_contacto:
        return (
            "Perfecto. Ya te comuniqué con un asesor de Cursala para atención personalizada. "
            "Te va a contactar a la brevedad."
        )

    nombre = vendedor_contacto.get("nombre") or "Asesor"
    telefono = vendedor_contacto.get("telefono") or ""
    return (
        "Perfecto. Ya te comuniqué con un asesor de Cursala para atención personalizada.\n\n"
        f"Tu contacto asignado: {nombre}\n"
        f"WhatsApp: {telefono}\n\n"
        "También te van a escribir a la brevedad."
    )


def derivar_asesor_desde_audio_inmediato(from_number: str, session: dict) -> None:
    """Deriva de inmediato a un vendedor cuando el usuario lo solicita explícitamente por audio."""
    session["recent_audio_interaction"] = False
    session["advisor_flow_from_audio"] = False
    session["pending_action"] = None
    session["in_response_menu"] = False
    session["last_response_option"] = None

    track_user_interest(
        from_number,
        "hablar_con_asesor",
        "audio_solicita_asesor_inmediato",
        etiqueta_cliente="interesado_asesoria",
    )
    vendedor_contacto = notificar_vendedor_atencion_personalizada(from_number, session, origen="audio")
    enviar_respuesta(from_number, _build_contacto_inmediato_text(vendedor_contacto))


def derivar_asesor_desde_texto_inmediato(from_number: str, session: dict) -> None:
    """Deriva de inmediato a un vendedor cuando el usuario lo solicita por texto."""
    session["recent_audio_interaction"] = False
    session["advisor_flow_from_audio"] = False
    session["pending_action"] = None
    session["in_response_menu"] = False
    session["last_response_option"] = None

    track_user_interest(
        from_number,
        "hablar_con_asesor",
        "texto_solicita_asesor_inmediato",
        etiqueta_cliente="interesado_asesoria",
    )
    vendedor_contacto = notificar_vendedor_atencion_personalizada(from_number, session, origen="texto")
    enviar_respuesta(from_number, _build_contacto_inmediato_text(vendedor_contacto))


def notificar_vendedor_atencion_personalizada(
    from_number: str,
    session: dict,
    origen: str = "audio",
) -> Optional[dict]:
    """Envía aviso interno a un vendedor y devuelve contacto para compartir al cliente."""
    global _last_vendor_alert_id

    vendedores = menu_config.get("vendedores", {})
    candidatos = []
    for vendor_id, vendedor in vendedores.items():
        telefono = " ".join(str(vendedor.get("telefono", "")).strip().split())
        if telefono:
            candidatos.append((str(vendor_id), vendedor))

    if not candidatos:
        logger.warning("No hay vendedores con telefono para notificar atención personalizada.")
        return None

    # Selección pseudoaleatoria sin repetir consecutivamente el mismo vendedor.
    if len(candidatos) > 1 and _last_vendor_alert_id:
        elegibles = [item for item in candidatos if item[0] != _last_vendor_alert_id]
        if elegibles:
            candidatos = elegibles

    vendor_id, vendedor = random.choice(candidatos)
    _last_vendor_alert_id = vendor_id

    telefono_vendedor = " ".join(str(vendedor.get("telefono", "")).strip().split())
    nombre_vendedor = f"{vendedor.get('nombre', '')} {vendedor.get('apellido', '')}".strip() or "Vendedor"
    nombre_cliente = get_saved_contact_name(from_number, session) or "Cliente sin nombre"

    origen_texto = "desde audio" if origen == "audio" else "por mensaje"
    alerta = (
        "ALERTA BOT CURSALA\n\n"
        f"Nuevo cliente solicitó hablar con un asesor ({origen_texto}).\n\n"
        f"Cliente: {nombre_cliente}\n"
        f"Teléfono: +{normalize_number(from_number)}\n\n"
        "Contactalo a la brevedad."
    )

    destino = telefono_vendedor if telefono_vendedor.startswith("+") else f"+{telefono_vendedor}"
    ok = enviar_payload_whatsapp(
        destino,
        {"type": "text", "text": {"body": alerta}},
        "alerta_atencion_personalizada",
    )
    if ok:
        logger.info("Alerta de atención personalizada enviada a %s", nombre_vendedor)
    else:
        logger.warning("No se pudo enviar alerta de atención personalizada a %s", nombre_vendedor)

    return {
        "vendor_id": vendor_id,
        "nombre": nombre_vendedor,
        "telefono": destino,
        "notificado": ok,
    }


def responder_con_gemini(user_text: str, from_number: str, session: dict) -> Optional[str]:
    """Genera una respuesta conversacional con Gemini para mensajes fuera del flujo."""
    if not ENABLE_GEMINI_FALLBACK or not gemini_client:
        return None

    user_message = (user_text or "").strip()
    if not user_message:
        return None

    _detectar_intereses_gemini(user_message, from_number)

    catalog_lines = []
    cursos = get_unified_courses()
    for cid, c in cursos.items():
        desc = (c.get("descripcion") or "").strip()
        catalog_lines.append(f"  {cid}. {c['nombre']}: {desc}")
    catalog_text = "\n".join(catalog_lines) if catalog_lines else "  (sin cursos configurados)"

    curso_context = ""
    if session.get("in_course_detail") and session.get("current_course"):
        cur = cursos.get(session["current_course"], {})
        if cur:
            curso_context = (
                f"\nContexto: el usuario esta explorando el curso '{cur.get('nombre', '')}'. "
                f"Descripcion: {cur.get('descripcion', '')}. "
                "Podes dar informacion tecnica detallada sobre este programa y sus contenidos.\n"
            )

    history = session.get("gemini_history", [])
    history_text = ""
    if history:
        lines = []
        for msg in history[-6:]:
            role_label = "Usuario" if msg["role"] == "user" else "Asistente"
            lines.append(f"{role_label}: {msg['text']}")
        history_text = "\nHistorial reciente de la conversacion:\n" + "\n".join(lines) + "\n"

    custom_rules_block = build_gemini_prompt_rules_block(menu_config)
    brief_style_block = ""
    if session.pop("prefer_brief_style", False):
        brief_style_block = (
            "ESTILO PARA ESTE MENSAJE:\n"
            "- Respondé sin demasiadas formalidades.\n"
            "- Andá directo a resolver lo que el usuario quiere.\n"
            "- No pidas nombre ni hagas saludo ceremonial.\n\n"
        )
    audio_handoff_block = ""
    if session.get("recent_audio_interaction"):
        audio_handoff_block = (
            "SI ESTE MENSAJE VIENE DE UN AUDIO:\n"
            "- Si el usuario quiere hablar con un asesor o necesita precio, fechas o inscripción, no le digas que escriba números ni opciones.\n"
            "- Respondé de forma natural y profesional, indicando que lo vas a derivar con un asesor.\n"
            "- Si necesitás segmentar la consulta, pedí solamente si corresponde a empresa o persona.\n\n"
        )

    prompt = (
        "Sos el asistente conversacional de Cursala, empresa argentina de formacion tecnica y profesional.\n\n"
        "TU ROL:\n"
        "- Responder con confianza y profundidad tecnica sobre los cursos y sus areas tematicas.\n"
        "- Entablar conversacion para descubrir el perfil del usuario: sector, experiencia, objetivos laborales.\n"
        "- Hacer una pregunta de seguimiento cuando necesites mas contexto para orientarlo bien.\n"
        "- Recomendar el curso mas adecuado cuando tengas suficiente informacion sobre sus necesidades.\n"
        "- Responder en espanol rioplatense, tono profesional y cercano.\n"
        "- Respuestas de hasta 5 lineas salvo que la pregunta tecnica requiera mas detalle.\n\n"
        "LIMITES:\n"
        "- Derivar a asesor para consultas sobre PRECIOS, FECHAS o INSCRIPCION concreta.\n"
        "- No inventar datos especificos que no estes seguro. Si no sabes algo, decilo con honestidad.\n"
        "- No redirigir al menu estatico si podes responder directamente.\n\n"
        f"{brief_style_block}"
        f"{audio_handoff_block}"
        f"{custom_rules_block}"
        f"Catalogo de cursos disponibles en Cursala:\n{catalog_text}\n"
        f"{curso_context}"
        f"{history_text}"
        f"\nMensaje del usuario: {user_message}"
    )

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        answer = (getattr(response, "text", None) or "").strip()
        if not answer:
            return None

        history.append({"role": "user", "text": user_message[:400]})
        history.append({"role": "model", "text": answer[:400]})
        session["gemini_history"] = history[-12:]

        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            telefono=from_number,
            evento="gemini_fallback_respuesta",
            extra_fields={
                "gemini_model": GEMINI_MODEL,
                "pending_action": session.get("pending_action"),
            },
        )
        return answer
    except Exception as exc:
        logger.warning("Gemini fallback error: %s", exc)
        return None


# ============================================================
# ENVIO DE CORREOS
# ============================================================

def _enviar_correos_formulario(
    nombre: str,
    correo_usuario: str,
    telefono: str,
    menu_origen: str,
    datos_adicionales: dict,
) -> None:
    """Envía correos de confirmación. Se ejecuta en background para no bloquear la respuesta WhatsApp."""
    def _worker():
        datos_lineas = "\n".join([f"- {k}: {v}" for k, v in datos_adicionales.items()])
        datos_html = "".join([f"<li><b>{k}:</b> {v}</li>" for k, v in datos_adicionales.items()])

        if validar_correo(correo_usuario):
            ok_usuario, detalle_usuario = enviar_correo_brevo(
                to_email=correo_usuario.strip(),
                to_name=nombre or "Usuario",
                subject="Confirmación de solicitud - Cursala",
                html_content=(
                    f"<p>Hola {nombre or 'Usuario'},</p>"
                    f"<p>Recibimos correctamente tu solicitud de <b>{menu_origen}</b>.</p>"
                    f"<p>Datos registrados:</p><ul>{datos_html}</ul>"
                    "<p>Gracias por contactarte con Cursala.</p>"
                ),
                text_content=(
                    f"Hola {nombre or 'Usuario'},\n\n"
                    f"Recibimos correctamente tu solicitud de {menu_origen}.\n"
                    f"Datos registrados:\n{datos_lineas}\n\n"
                    "Gracias por contactarte con Cursala."
                ),
            )
            if ok_usuario:
                logger.info("Correo de confirmacion enviado a %s: %s", correo_usuario, detalle_usuario)
            else:
                logger.warning("Error enviando correo al usuario %s: %s", correo_usuario, detalle_usuario)

        internos = {"info@cursala.com.ar", "info@mail.cursala.com.ar"}
        cfg_dest = menu_config.get("email_notificacion_admin", {}).get("destinatario", "").strip()
        if cfg_dest:
            internos.add(cfg_dest)

        for destinatario in sorted(internos):
            ok_admin, detalle_admin = enviar_notificacion_evento(
                tipo_evento="formulario_completado",
                telefono=normalize_number(telefono),
                nombre=nombre,
                menu_origen=menu_origen,
                destinatario=destinatario,
                asunto=f"Nuevo formulario completado: {menu_origen}",
                cuerpo_intro=f"Se completó un formulario de {menu_origen}.",
                datos_adicionales=datos_adicionales,
            )
            if ok_admin:
                logger.info("Correo interno enviado a %s: %s", destinatario, detalle_admin)
            else:
                logger.warning("Error enviando correo interno a %s: %s", destinatario, detalle_admin)

    _bg(_worker)


def _disparar_notificacion_primer_contacto(
    from_number: str,
    session: dict,
    nombre: str = "",
    menu_origen: str = "registro",
    datos_adicionales: dict = None,
) -> None:
    """Envía notificación admin de primer contacto. La parte lenta (Firestore + email) corre en background."""
    if datos_adicionales is None:
        datos_adicionales = {}

    # Marcar en sesión ANTES de iniciar el hilo para evitar doble disparo
    session["notificacion_admin_enviada"] = True

    if firestore_db is None:
        return

    email_cfg = menu_config.get("email_notificacion_admin", {})
    if not email_cfg.get("activo", True):
        return

    # Capturar valores inmutables antes de ceder el control al hilo
    _nombre = nombre
    _menu_origen = menu_origen
    _datos = dict(datos_adicionales)
    _from = from_number

    def _worker():
        try:
            normalized = normalize_number(_from)
            doc_ref = firestore_db.collection(FIRESTORE_COLLECTION).document(normalized)
            doc = doc_ref.get()

            if doc.exists and doc.to_dict().get("notificacion_admin_enviada"):
                return

            destinatario = email_cfg.get("destinatario", "info@cursala.com.ar")
            asunto = email_cfg.get("asunto", "Nuevo contacto en WhatsApp Bot - Cursala")
            cuerpo_intro = email_cfg.get("cuerpo_intro", "Se ha registrado un nuevo usuario en el bot de Cursala.")

            ok, detalle = procesar_notificacion_registro(
                telefono=normalized,
                nombre=_nombre,
                menu_origen=_menu_origen,
                destinatario=destinatario,
                asunto=asunto,
                cuerpo_intro=cuerpo_intro,
                datos_adicionales=_datos,
            )

            if ok:
                logger.info("Notificacion admin enviada a %s: %s", destinatario, detalle)
                doc_ref.set(
                    {
                        "notificacion_admin_enviada": True,
                        "notificacion_admin_message_id": detalle,
                    },
                    merge=True,
                )
            else:
                logger.warning("Error enviando notificacion admin a %s: %s", destinatario, detalle)

        except Exception as e:
            logger.error("Error en _disparar_notificacion_primer_contacto: %s", e)

    _bg(_worker)


# ============================================================
# POST-ONBOARDING: retomar flujo diferido tras captura de nombre
# ============================================================

def resume_post_onboarding_flow(from_number: str, command_text: str, session: dict) -> bool:
    deferred_command = (command_text or "").strip()
    if not deferred_command:
        return False

    saved_name = get_saved_contact_name(from_number, session)

    direct_course_action = parse_course_action_identifier(deferred_command, menu_config)
    if direct_course_action is not None:
        curso_id, action = direct_course_action
        menu_trace("route_post_onboarding_course_action", from_number, command=deferred_command, curso_id=curso_id, action=action)
        handle_course_detail_action(from_number, curso_id, action, menu_config, session)
        return True

    direct_course_selection = parse_course_selection(deferred_command, menu_config)
    if direct_course_selection is not None:
        menu_trace("route_post_onboarding_course_selection", from_number, command=deferred_command, curso_id=direct_course_selection)
        session["in_course_menu"] = True
        session["in_course_detail"] = True
        session["current_course"] = direct_course_selection
        cursos = get_unified_courses()
        track_user_interest(from_number, cursos[direct_course_selection]["nombre"], "curso_seleccionado")
        enviar_detalle_curso(from_number, direct_course_selection, menu_config)
        return True

    if deferred_command == "1":
        menu_trace("route_post_onboarding_main_option_courses", from_number, command=deferred_command)
        session["in_course_menu"] = True
        track_user_interest(from_number, "cursos_disponibles", "menu_opcion_1", etiqueta_cliente="interesado_cursos")
        enviar_menu_cursos_lista(from_number, menu_config)
        return True

    if deferred_command == "2":
        session["temp_course_data"] = {}
        session["pending_action"] = "empresa_nombre"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "capacitaciones_empresas", "menu_opcion_2", etiqueta_cliente="interesado_empresa")
        enviar_respuesta(
            from_number,
            "Excelente. Para poder asesorarte mejor, indicános el nombre de la empresa:\n\n0. Volver al menú principal"
        )
        return True

    if deferred_command == "3":
        session["temp_prof_data"] = {}
        if saved_name:
            session["temp_prof_data"]["nombre_apellido"] = saved_name
            session["pending_action"] = "pro_nacionalidad"
            prompt_profesional = (
                f"¡Excelente, {saved_name}! Ahora indicános tu *nacionalidad*:\n\n"
                "0. Volver al menú principal"
            )
        else:
            session["pending_action"] = "pro_nombre_apellido"
            prompt_profesional = (
                "¡Excelente! Vamos a registrar tu perfil para dictar capacitaciones.\n\n"
                "Indicános tu *Nombre y apellido*:\n\n"
                "0. Volver al menú principal"
            )
        session["in_response_menu"] = False
        session["last_response_option"] = None
        track_user_interest(from_number, "quiero_capacitar", "menu_opcion_3", etiqueta_cliente="interesado_profesional")
        enviar_respuesta(from_number, prompt_profesional)
        return True

    if deferred_command == "4":
        session["recent_audio_interaction"] = False
        iniciar_flujo_asesor(from_number, session, via_audio=False)
        return True

    return False


# ============================================================
# INICIADORES DE FLUJO REUTILIZABLES
# ============================================================

def iniciar_flujo_empresa(from_number: str, session: dict) -> None:
    """
    Inicia el flujo de 'Capacitación empresarial'.
    Esta función centraliza la lógica para evitar duplicación de código.
    """
    session["temp_course_data"] = {}
    session["pending_action"] = "empresa_nombre"
    session["in_response_menu"] = False
    session["last_response_option"] = None
    track_user_interest(from_number, "capacitaciones_empresas", "menu_opcion_2", etiqueta_cliente="interesado_empresa")
    enviar_respuesta(
        from_number,
        "Excelente. Para poder asesorarte mejor, indicános el nombre de la empresa:\n\n0. Volver al menú principal"
    )


def iniciar_flujo_profesional(from_number: str, session: dict, saved_name: str) -> None:
    """
    Inicia el flujo de 'Quiero capacitar'.
    Esta función centraliza la lógica para evitar duplicación de código.
    """
    session["temp_prof_data"] = {}
    if saved_name:
        session["temp_prof_data"]["nombre_apellido"] = saved_name
        session["pending_action"] = "pro_nacionalidad"
        prompt_profesional = (
            f"¡Excelente, {saved_name}! Ahora indicános tu *nacionalidad*:\n\n"
            "0. Volver al menú principal"
        )
    else:
        session["pending_action"] = "pro_nombre_apellido"
        prompt_profesional = (
            "¡Excelente! Vamos a registrar tu perfil para dictar capacitaciones.\n\n"
            "Indicános tu *Nombre y apellido*:\n\n"
            "0. Volver al menú principal"
        )
    session["in_response_menu"] = False
    session["last_response_option"] = None
    track_user_interest(from_number, "quiero_capacitar", "menu_opcion_3", etiqueta_cliente="interesado_profesional")
    enviar_respuesta(from_number, prompt_profesional)

# ============================================================
# MOTOR DE FLUJO DEL USUARIO FINAL
# ============================================================

def manejar_usuario(from_number: str, text_body: str):
    """Procesa cada mensaje entrante del usuario no-admin."""
    session = get_admin_session(from_number)
    now_ts = time.time()
    last_interaction_at = float(session.get("last_interaction_at", 0) or 0)
    if last_interaction_at and (now_ts - last_interaction_at) > USER_INACTIVITY_TIMEOUT_SECONDS:
        reset_user_flow(session)
        session["user_name"] = ""
        session["gemini_history"] = []
    session["last_interaction_at"] = now_ts

    text = text_body.strip()
    text_lower = text.lower()
    command_text = normalize_menu_command(text_body)
    command_lower = command_text.lower()
    menu_trace(
        "user_input",
        from_number,
        raw=text_body,
        command=command_text,
        session=course_session_snapshot(session),
    )
    upsert_user_profile_firestore(
        whatsapp_number=from_number,
        telefono=from_number,
        evento="mensaje_entrante",
        extra_fields={},
    )

    detected_interests = detect_course_interest_labels(text_body)
    if detected_interests:
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            telefono=from_number,
            intereses=detected_interests,
            evento="interes_detectado_texto_libre",
        )

    empresa_actions = {
        "onboarding_nombre", "empresa_nombre", "empresa_cuit", "empresa_provincia",
        "empresa_correo", "empresa_necesidades", "empresa_confirmacion", "empresa_ver_datos",
        "empresa_edit_select", "empresa_edit_valor", "empresa_edit_confirm", "empresa_post_confirmacion",
    }
    profesional_actions = {
        "pro_nombre_apellido", "pro_profesion", "pro_nacionalidad", "pro_dni",
        "pro_descripcion", "pro_confirmacion", "pro_edit_nombre_apellido",
        "pro_edit_profesion", "pro_edit_nacionalidad", "pro_edit_dni",
        "pro_edit_descripcion", "pro_cv_confirmacion",
    }
    asesor_actions = {
        "asesor_tipo", "asesor_empresa_nombre", "asesor_empresa_correo",
        "asesor_empresa_email", "asesor_empresa_motivo", "asesor_empresa_confirmacion",
        "asesor_empresa_edit_nombre", "asesor_empresa_edit_correo",
        "asesor_empresa_edit_email", "asesor_empresa_edit_motivo",
        "asesor_persona_nombre", "asesor_persona_dni", "asesor_persona_telefono",
        "asesor_persona_correo", "asesor_persona_motivo", "asesor_persona_confirmacion",
        "asesor_persona_edit_menu", "asesor_persona_edit_nombre", "asesor_persona_edit_dni",
        "asesor_persona_edit_telefono", "asesor_persona_edit_correo", "asesor_persona_edit_motivo",
    }

    if command_lower in ["salir", "exit"]:
        reset_user_flow(session)
        session["user_name"] = ""
        session["gemini_history"] = []
        enviar_respuesta(
            from_number,
            "✅ Sesión finalizada.\n\n"
            "Cuando quieras volver, escribí *Hola* y te pediré tu nombre nuevamente."
        )
        return

    if session.get("pending_action") is None and audio_requests_advisor(text_body):
        if session.get("recent_audio_interaction"):
            menu_trace("route_audio_direct_advisor_handoff", from_number, text=text_body[:200])
            derivar_asesor_desde_audio_inmediato(from_number, session)
        else:
            menu_trace("route_text_direct_advisor_handoff", from_number, text=text_body[:200])
            derivar_asesor_desde_texto_inmediato(from_number, session)
        return

    if command_lower in ["hola", "menu", "inicio"]:
        saved_name = get_saved_contact_name(from_number, session)
        if not saved_name:
            session["post_onboarding_command"] = None
            session["pending_action"] = "onboarding_nombre"
            enviar_respuesta(
                from_number,
                "¡Hola! Antes de comenzar, ¿me compartís tu nombre?\n\n"
                "0. Volver al menú principal"
            )
            return
        reset_user_flow(session)
        menu_trace("route_main_menu", from_number, command=command_text)
        track_user_interest(from_number, "menu_principal", "navegacion_menu")
        enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        return

    if command_lower == "admin":
        if not is_admin(from_number):
            enviar_respuesta(from_number, "❌ No autorizado.")
            return
        session["awaiting_admin_password"] = True
        enviar_respuesta(from_number, "Por favor, ingresá la contraseña:")
        return

    saved_name = get_saved_contact_name(from_number, session)

    if session.get("pending_action") == "onboarding_nombre":
        if command_text == "0":
            session["pending_action"] = None
            session["post_onboarding_command"] = None
            enviar_menu_principal_lista(from_number, menu_config)
            return

        if not validar_texto_sin_numeros(text_body, min_len=2):
            enviar_respuesta(
                from_number,
                "⚠️ Ingresá un nombre válido (sin números).\n"
                "Ejemplo: *Juan* o *Juan Pérez*\n\n"
                "0. Volver al menú principal"
            )
            return

        user_name = sanitize_contact_name(text_body)
        session["user_name"] = user_name
        session["pending_action"] = None
        deferred_command = str(session.pop("post_onboarding_command", "") or "").strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=user_name,
            telefono=from_number,
            evento="onboarding_nombre_capturado",
            extra_fields={"nombre_contacto": user_name},
        )
        if resume_post_onboarding_flow(from_number, deferred_command, session):
            return
        enviar_respuesta(from_number, f"¡Bienvenido {user_name}! 👋\nGracias por comunicarte con Cursala.")
        enviar_menu_principal_lista(from_number, menu_config, include_greeting=False, user_name=user_name)
        return

    saved_name = get_saved_contact_name(from_number, session)

    if not saved_name and session.get("pending_action") is None:
        if session.get("skip_name_request_once"):
            session["skip_name_request_once"] = False
        else:
            session["post_onboarding_command"] = command_text
            session["pending_action"] = "onboarding_nombre"
            saludo = saludo_por_horario()
            enviar_respuesta(
                from_number,
                f"*{saludo}* Antes de comenzar, ¿me compartís tu nombre?\n\n"
                "0. Volver al menú principal"
            )
            return

    if session.get("pending_action") in (empresa_actions | profesional_actions | asesor_actions) and command_text == "0":
        reset_user_flow(session)
        enviar_respuesta(from_number, "↩️ Volviste al menú principal.")
        enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        return

    if (
        session.pop("force_conversational_audio_once", False)
        and session.get("pending_action") is None
        and not session.get("in_course_menu")
        and not session.get("in_course_detail")
        and not session.get("in_response_menu")
    ):
        respuesta_ia = responder_con_gemini(text_body, from_number, session)
        if respuesta_ia:
            menu_trace("route_audio_conversational_reply", from_number, text=text_body[:200])
            enviar_respuesta(from_number, respuesta_ia)
            return

    # ============================================================
    # FLUJOS DE FORMULARIOS
    # ============================================================

    if session["pending_action"] == "empresa_nombre":
        if not validar_nombre_empresa(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El nombre de la empresa no es válido. No debe contener números.\n"
                "Ejemplo: *Cursala SA*, *Servicios Andinos SRL*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["empresa"] = text_body.strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=text_body.strip(),
            telefono=from_number,
            intereses=["capacitaciones_empresas"],
            evento="captura_empresa_nombre",
        )
        enviar_respuesta(from_number, "Perfecto. Ahora indicános el CUIT de la empresa:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_cuit"
        return

    if session["pending_action"] == "empresa_cuit":
        if not validar_solo_numeros(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El CUIT ingresado no es válido. Debe contener solo números.\n"
                "Ejemplo: *30-12345678-9*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["cuit"] = "".join(ch for ch in text_body if ch.isdigit())
        enviar_respuesta(from_number, "Gracias. ¿En qué provincia se encuentra la empresa?\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_provincia"
        return

    if session["pending_action"] == "empresa_provincia":
        if not validar_provincia(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ La provincia ingresada no es válida.\n"
                "Ejemplo: *Mendoza*, *Buenos Aires*, *CABA*, *Santa Fe*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["provincia"] = text_body.strip().title()
        enviar_respuesta(from_number, "Indicános un correo de contacto:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_correo"
        return

    if session["pending_action"] == "empresa_correo":
        if not validar_correo(text_body):
            enviar_respuesta(
                from_number,
                "⚠️ El correo ingresado no parece válido.\n"
                "Ejemplo: *contacto@empresa.com*\n\n"
                "0. Volver al menú principal"
            )
            return
        session["temp_course_data"]["correo"] = text_body.strip()
        enviar_respuesta(from_number, "Por favor, describí las necesidades de formación de tu empresa:\n\n0. Volver al menú principal")
        session["pending_action"] = "empresa_necesidades"
        return

    if session["pending_action"] == "empresa_necesidades":
        session["temp_course_data"]["necesidades"] = text_body
        session["pending_action"] = "empresa_confirmacion"
        enviar_menu_empresa_confirmacion_lista(from_number, session["temp_course_data"])
        return

    if session["pending_action"] == "empresa_confirmacion":
        if text == "1":
            data = session["temp_course_data"]
            upsert_user_profile_firestore(
                whatsapp_number=from_number,
                nombre=data.get("empresa", ""),
                telefono=from_number,
                intereses=["capacitaciones_empresas"],
                evento="empresa_confirmada",
                extra_fields={
                    "empresa": {
                        "nombre": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia_declarada": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                    }
                },
                etiqueta_cliente="lead_empresa",
            )
            resumen = (
                "✅ Gracias por la información.\n\n"
                "Hemos registrado los siguientes datos:\n\n"
                + build_labeled_data_block([
                    ("Empresa", data.get("empresa", "")),
                    ("CUIT", data.get("cuit", "")),
                    ("Provincia", data.get("provincia", "")),
                    ("Correo", data.get("correo", "")),
                    ("Necesidades de formación", data.get("necesidades", "")),
                ])
                + "\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad."
            )
            enviar_respuesta(from_number, resumen)
            _enviar_correos_formulario(
                nombre=data.get("empresa", ""),
                correo_usuario=data.get("correo", ""),
                telefono=from_number,
                menu_origen="Capacitaciones para empresas",
                datos_adicionales={
                    "Empresa": data.get("empresa", ""),
                    "CUIT": data.get("cuit", ""),
                    "Provincia": data.get("provincia", ""),
                    "Correo": data.get("correo", ""),
                    "Necesidades": data.get("necesidades", ""),
                },
            )
            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session,
                    nombre=data.get("empresa", ""),
                    menu_origen="Capacitación empresarial",
                    datos_adicionales={
                        "empresa": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                        "necesidades_formacion": data.get("necesidades", ""),
                    },
                )
            session["pending_action"] = "empresa_post_confirmacion"
            enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        elif text == "2":
            session["pending_action"] = "empresa_ver_datos"
            enviar_menu_empresa_datos_lista(from_number, session["temp_course_data"])
        else:
            enviar_respuesta(from_number, "Opción inválida.")
            enviar_menu_empresa_confirmacion_lista(from_number, session["temp_course_data"])
        return

    if session["pending_action"] == "empresa_ver_datos":
        if text == "1":
            session["pending_action"] = "empresa_edit_select"
            enviar_menu_empresa_editar_lista(from_number)
        elif text == "2":
            data = session["temp_course_data"]
            upsert_user_profile_firestore(
                whatsapp_number=from_number,
                nombre=data.get("empresa", ""),
                telefono=from_number,
                intereses=["capacitaciones_empresas"],
                evento="empresa_confirmada",
                extra_fields={
                    "empresa": {
                        "nombre": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia_declarada": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                    }
                },
                etiqueta_cliente="lead_empresa",
            )
            resumen = (
                "✅ Gracias por la información.\n\nHemos registrado los siguientes datos:\n\n"
                + build_labeled_data_block([
                    ("Empresa", data.get("empresa", "")),
                    ("CUIT", data.get("cuit", "")),
                    ("Provincia", data.get("provincia", "")),
                    ("Correo", data.get("correo", "")),
                    ("Necesidades de formación", data.get("necesidades", "")),
                ])
                + "\n\nUn asesor de Cursala se pondrá en contacto a la brevedad."
            )
            enviar_respuesta(from_number, resumen)
            _enviar_correos_formulario(
                nombre=data.get("empresa", ""),
                correo_usuario=data.get("correo", ""),
                telefono=from_number,
                menu_origen="Capacitaciones para empresas",
                datos_adicionales={
                    "Empresa": data.get("empresa", ""),
                    "CUIT": data.get("cuit", ""),
                    "Provincia": data.get("provincia", ""),
                    "Correo": data.get("correo", ""),
                    "Necesidades": data.get("necesidades", ""),
                },
            )
            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session,
                    nombre=data.get("empresa", ""),
                    menu_origen="Capacitación empresarial",
                    datos_adicionales={
                        "empresa": data.get("empresa", ""),
                        "cuit": data.get("cuit", ""),
                        "provincia": data.get("provincia", ""),
                        "correo": data.get("correo", ""),
                        "necesidades_formacion": data.get("necesidades", ""),
                    },
                )
            session["pending_action"] = "empresa_post_confirmacion"
            enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        elif text == "3":
            session["pending_action"] = "empresa_confirmacion"
            enviar_menu_empresa_confirmacion_lista(from_number, session["temp_course_data"])
        else:
            enviar_respuesta(from_number, "Opción inválida.")
            enviar_menu_empresa_datos_lista(from_number, session["temp_course_data"])
        return

    if session["pending_action"] == "empresa_post_confirmacion":
        if text == "1":
            reset_user_flow(session)
            enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        else:
            enviar_respuesta(from_number, "Seleccioná una opción válida:\n\n1. Ir al menú principal")
        return

    if session["pending_action"] == "empresa_edit_select":
        fields = {"1": "empresa", "2": "cuit", "3": "provincia", "4": "correo", "5": "necesidades"}
        labels = {
            "empresa": "Nombre de la empresa", "cuit": "CUIT", "provincia": "Provincia",
            "correo": "Correo", "necesidades": "Necesidades de formación",
        }
        if text == "0":
            session["pending_action"] = "empresa_ver_datos"
            enviar_menu_empresa_datos_lista(from_number, session["temp_course_data"])
            return
        if text not in fields:
            enviar_respuesta(from_number, "Opción inválida.")
            enviar_menu_empresa_editar_lista(from_number)
            return
        field = fields[text]
        session["temp_field"] = field
        valor_actual = session["temp_course_data"].get(field, "")
        enviar_respuesta(
            from_number,
            f"Campo: {labels[field]}\nValor actual: {valor_actual}\n\nIngresá el nuevo valor:\n2. Volver"
        )
        session["pending_action"] = "empresa_edit_valor"
        return

    if session["pending_action"] == "empresa_edit_valor":
        field = session.get("temp_field")
        if text == "2":
            session["pending_action"] = "empresa_edit_select"
            enviar_menu_empresa_editar_lista(from_number)
            return
        nuevo_valor = text_body.strip()
        if field == "empresa" and not validar_nombre_empresa(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ El nombre de la empresa no es válido.\n\n2. Volver")
            return
        if field == "cuit" and not validar_solo_numeros(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ El CUIT debe contener solo números.\n\n2. Volver")
            return
        if field == "provincia" and not validar_provincia(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ Provincia inválida.\n\n2. Volver")
            return
        if field == "correo" and not validar_correo(nuevo_valor):
            enviar_respuesta(from_number, "⚠️ Correo inválido.\n\n2. Volver")
            return
        if field == "necesidades" and len(nuevo_valor) < 5:
            enviar_respuesta(from_number, "⚠️ Ingresá una necesidad más detallada.\n\n2. Volver")
            return
        if field == "cuit":
            nuevo_valor = "".join(ch for ch in nuevo_valor if ch.isdigit())
        if field == "provincia":
            nuevo_valor = nuevo_valor.title()
        session["temp_course_data"]["edit_pending_value"] = nuevo_valor
        valor_actual = session["temp_course_data"].get(field, "")
        enviar_respuesta(
            from_number,
            f"Valor actual: {valor_actual}\nNuevo valor: {nuevo_valor}\n\n1. Aceptar cambio\n2. Volver"
        )
        session["pending_action"] = "empresa_edit_confirm"
        return

    if session["pending_action"] == "empresa_edit_confirm":
        if text == "1":
            field = session.get("temp_field")
            nuevo_valor = session["temp_course_data"].get("edit_pending_value", "")
            session["temp_course_data"][field] = nuevo_valor
            session["temp_course_data"].pop("edit_pending_value", None)
            session["pending_action"] = "empresa_ver_datos"
            enviar_respuesta(from_number, "✅ Cambio aplicado.")
            enviar_menu_empresa_datos_lista(from_number, session["temp_course_data"])
        elif text == "2":
            session["temp_course_data"].pop("edit_pending_value", None)
            session["pending_action"] = "empresa_edit_select"
            enviar_menu_empresa_editar_lista(from_number)
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n1. Aceptar cambio\n2. Volver")
        return

    # --- PROFESIONAL ---

    if session["pending_action"] == "pro_nombre_apellido":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(
                from_number, "⚠️ Ingresá un nombre y apellido válidos (sin números).\n"
                "Ejemplo: *Juan Pérez*\n\n0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["nombre_apellido"] = text_body.strip()
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number, nombre=text_body.strip(), telefono=from_number,
            intereses=["quiero_capacitar"], evento="captura_profesional_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
        session["pending_action"] = "pro_nacionalidad"
        enviar_respuesta(from_number, "Gracias. ¿Cuál es tu *nacionalidad*?\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "pro_nacionalidad":
        if not validar_texto_sin_numeros(text_body, min_len=3):
            enviar_respuesta(
                from_number, "⚠️ La nacionalidad ingresada no es válida (sin números).\n"
                "Ejemplo: *Argentina*, *Chilena*\n\n0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["nacionalidad"] = text_body.strip()
        session["pending_action"] = "pro_dni"
        enviar_respuesta(from_number, "Ahora indicános tu *DNI* (solo números):\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "pro_dni":
        if not validar_dni(text_body):
            enviar_respuesta(
                from_number, "⚠️ El DNI no es válido. Debe tener 7 u 8 dígitos.\n"
                "Ejemplo: *30123456*\n\n0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "pro_descripcion"
        enviar_respuesta(from_number, "Describí brevemente el *curso que querés dictar*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "pro_descripcion":
        if len(text_body.strip()) < 10:
            enviar_respuesta(
                from_number, "⚠️ La descripción es muy breve. Contanos un poco más.\n\n0. Volver al menú principal"
            )
            return
        session["temp_prof_data"]["descripcion_curso"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_menu_profesional_confirmacion_lista(from_number, session["temp_prof_data"])
        return

    if session["pending_action"] == "pro_confirmacion":
        if text_lower == "c":
            session["pending_action"] = "pro_cv_confirmacion"
            enviar_respuesta(
                from_number,
                "Excelente. Para finalizar, cargá tu CV en este enlace:\n"
                f"🔗 {CV_UPLOAD_URL}\n\n"
                "Cuando termines, respondé *LISTO* para guardar tu postulación.\n\n"
                "0. Volver al menú principal"
            )
        elif text == "1":
            session["pending_action"] = "pro_edit_nombre_apellido"
            enviar_respuesta(from_number, "Ingresá el nuevo *Nombre y apellido*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "pro_edit_nacionalidad"
            enviar_respuesta(from_number, "Ingresá la nueva *nacionalidad*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "pro_edit_dni"
            enviar_respuesta(from_number, "Ingresá el nuevo *DNI* (solo números):\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "pro_edit_descripcion"
            enviar_respuesta(from_number, "Ingresá la nueva *descripción del curso*:\n\n0. Volver al menú principal")
        else:
            enviar_menu_profesional_confirmacion_lista(from_number, session["temp_prof_data"])
        return

    if session["pending_action"] == "pro_edit_nombre_apellido":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(from_number, "⚠️ Ingresá un nombre y apellido válidos.\n\n0. Volver al menú principal")
            return
        session["temp_prof_data"]["nombre_apellido"] = text_body.strip()
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number, nombre=text_body.strip(), telefono=from_number,
            evento="edicion_profesional_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_profesional_confirmacion_lista(from_number, session["temp_prof_data"])
        return

    if session["pending_action"] == "pro_edit_nacionalidad":
        if not validar_texto_sin_numeros(text_body, min_len=3):
            enviar_respuesta(from_number, "⚠️ La nacionalidad no es válida.\n\n0. Volver al menú principal")
            return
        session["temp_prof_data"]["nacionalidad"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_profesional_confirmacion_lista(from_number, session["temp_prof_data"])
        return

    if session["pending_action"] == "pro_edit_dni":
        if not validar_dni(text_body):
            enviar_respuesta(from_number, "⚠️ El DNI no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_prof_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_profesional_confirmacion_lista(from_number, session["temp_prof_data"])
        return

    if session["pending_action"] == "pro_edit_descripcion":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ La descripción es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_prof_data"]["descripcion_curso"] = text_body.strip()
        session["pending_action"] = "pro_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_profesional_confirmacion_lista(from_number, session["temp_prof_data"])
        return

    if session["pending_action"] == "pro_cv_confirmacion":
        if text_lower != "listo":
            enviar_respuesta(
                from_number,
                "Para continuar, cargá tu CV en el enlace y respondé *LISTO*.\n"
                f"🔗 {CV_UPLOAD_URL}\n\n0. Volver al menú principal"
            )
            return
        data = session.get("temp_prof_data", {})
        registro = {
            "fecha": datetime.now(ZoneInfo("America/Argentina/Mendoza")).isoformat(),
            "whatsapp": normalize_number(from_number),
            "nombre_apellido": data.get("nombre_apellido", ""),
            "profesion": data.get("profesion", ""),
            "nacionalidad": data.get("nacionalidad", ""),
            "dni": data.get("dni", ""),
            "descripcion_curso": data.get("descripcion_curso", ""),
            "cv_link": CV_UPLOAD_URL,
            "cv_confirmado": True,
        }
        save_profesional_interesado(registro)
        upsert_user_profile_firestore(
            whatsapp_number=from_number,
            nombre=registro.get("nombre_apellido", ""),
            telefono=from_number,
            intereses=["quiero_capacitar"],
            evento="postulacion_profesional_confirmada",
            extra_fields={
                "postulacion_profesional": {
                    "profesion": registro.get("profesion", ""),
                    "nacionalidad": registro.get("nacionalidad", ""),
                    "dni": registro.get("dni", ""),
                    "descripcion_curso": registro.get("descripcion_curso", ""),
                    "cv_confirmado": True,
                }
            },
            etiqueta_cliente="lead_profesional",
        )
        resumen = (
            "✅ ¡Postulación recibida!\n\nDatos registrados:\n\n"
            + build_labeled_data_block([
                ("Nombre y apellido", registro["nombre_apellido"]),
                ("Profesión", registro["profesion"]),
                ("Nacionalidad", registro["nacionalidad"]),
                ("DNI", registro["dni"]),
                ("Curso a dictar", registro["descripcion_curso"]),
                ("CV", "carga confirmada"),
            ])
            + "\n\nNuestro equipo revisará tu propuesta y te contactará a la brevedad."
        )
        enviar_respuesta(from_number, resumen)
        enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        if not session.get("notificacion_admin_enviada"):
            _disparar_notificacion_primer_contacto(
                from_number, session,
                nombre=registro.get("nombre_apellido", ""),
                menu_origen="Profesional docente",
                datos_adicionales={
                    "nombre_apellido": registro.get("nombre_apellido", ""),
                    "profesion": registro.get("profesion", ""),
                    "nacionalidad": registro.get("nacionalidad", ""),
                    "dni": registro.get("dni", ""),
                    "curso_a_dictar": registro.get("descripcion_curso", ""),
                    "cv_confirmado": "Sí" if registro.get("cv_confirmado") else "No",
                },
            )
        reset_user_flow(session)
        return

    # --- ASESOR ---

    if session["pending_action"] == "asesor_tipo":
        if text_lower in ["1", "empresa"]:
            session["advisor_flow_from_audio"] = False
            session["temp_asesor_data"] = {"tipo": "empresa"}
            session["pending_action"] = "asesor_empresa_nombre"
            enviar_respuesta(from_number, "Indicános el *nombre de la empresa*:\n\n0. Volver al menú principal")
        elif text_lower in ["2", "persona", "persona fisica", "persona física"]:
            if session.get("advisor_flow_from_audio"):
                notificar_vendedor_atencion_personalizada(from_number, session)
            session["advisor_flow_from_audio"] = False
            session["temp_asesor_data"] = {"tipo": "persona_fisica"}
            if saved_name:
                session["temp_asesor_data"]["nombre_completo"] = saved_name
                session["pending_action"] = "asesor_persona_dni"
                enviar_respuesta(
                    from_number, f"Perfecto, {saved_name}. Indicános tu *DNI*:\n\n0. Volver al menú principal"
                )
            else:
                session["pending_action"] = "asesor_persona_nombre"
                enviar_respuesta(from_number, "Indicános tu *nombre completo*:\n\n0. Volver al menú principal")
        else:
            enviar_menu_tipo_asesor_lista(from_number)
        return

    if session["pending_action"] == "asesor_empresa_nombre":
        if not validar_nombre_empresa(text_body):
            enviar_respuesta(from_number, "⚠️ El nombre de empresa no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_nombre"] = text_body.strip()
        upsert_user_profile_firestore(
            whatsapp_number=from_number, nombre=text_body.strip(), telefono=from_number,
            intereses=["hablar_con_asesor", "asesoria_empresa"], evento="asesor_empresa_nombre",
        )
        session["pending_action"] = "asesor_empresa_correo"
        enviar_respuesta(from_number, "Indicános un *correo* de contacto:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_empresa_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_correo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_email"
        enviar_respuesta(from_number, "Indicános un *email* alternativo:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_empresa_email":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El email no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_email"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_motivo"
        enviar_respuesta(from_number, "Describí el *motivo de la consulta*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_empresa_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ El motivo es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_menu_asesor_empresa_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_empresa_confirmacion":
        if text_lower == "c":
            data = session["temp_asesor_data"]
            registro = {
                "fecha": datetime.now(ZoneInfo("America/Argentina/Mendoza")).isoformat(),
                "whatsapp": normalize_number(from_number),
                "tipo": "empresa",
                "empresa_nombre": data.get("empresa_nombre", ""),
                "correo": data.get("empresa_correo", ""),
                "email": data.get("empresa_email", ""),
                "motivo": data.get("motivo", ""),
            }
            save_asesor_consulta(registro)
            upsert_user_profile_firestore(
                whatsapp_number=from_number, nombre=data.get("empresa_nombre", ""),
                telefono=from_number, intereses=["hablar_con_asesor", "asesoria_empresa"],
                evento="asesoria_empresa_confirmada",
                extra_fields={"consulta_asesor_empresa": registro}, etiqueta_cliente="lead_asesoria_empresa",
            )
            enviar_respuesta(
                from_number,
                "✅ Consulta enviada correctamente.\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad.\n\n"
                + build_asesores_contacto_message(menu_config, "Hola, quiero hablar con un asesor sobre capacitaciones para empresas.")
            )
            enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
            _enviar_correos_formulario(
                nombre=data.get("empresa_nombre", ""),
                correo_usuario=data.get("empresa_correo", ""),
                telefono=from_number,
                menu_origen="Formulario empresa",
                datos_adicionales={
                    "Empresa": data.get("empresa_nombre", ""),
                    "Correo": data.get("empresa_correo", ""),
                    "Email alternativo": data.get("empresa_email", ""),
                    "Motivo": data.get("motivo", ""),
                },
            )
            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session, nombre=data.get("empresa_nombre", ""),
                    menu_origen="Asesoría para empresa",
                    datos_adicionales={
                        "empresa_nombre": data.get("empresa_nombre", ""),
                        "correo": data.get("empresa_correo", ""),
                        "motivo_consulta": data.get("motivo", ""),
                    },
                )
            reset_user_flow(session)
        elif text == "1":
            session["pending_action"] = "asesor_empresa_edit_nombre"
            enviar_respuesta(from_number, "Ingresá el nuevo *nombre de la empresa*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "asesor_empresa_edit_correo"
            enviar_respuesta(from_number, "Ingresá el nuevo *correo*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "asesor_empresa_edit_email"
            enviar_respuesta(from_number, "Ingresá el nuevo *email*:\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "asesor_empresa_edit_motivo"
            enviar_respuesta(from_number, "Ingresá el nuevo *motivo*:\n\n0. Volver al menú principal")
        else:
            enviar_menu_asesor_empresa_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_empresa_edit_nombre":
        if not validar_nombre_empresa(text_body):
            enviar_respuesta(from_number, "⚠️ El nombre de empresa no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_nombre"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_empresa_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_empresa_edit_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_correo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_empresa_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_empresa_edit_email":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El email no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["empresa_email"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_empresa_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_empresa_edit_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ El motivo es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_empresa_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_empresa_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_persona_nombre":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(from_number, "⚠️ Ingresá un nombre completo válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["nombre_completo"] = text_body.strip()
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number, nombre=text_body.strip(), telefono=from_number,
            intereses=["hablar_con_asesor", "asesoria_persona_fisica"], evento="asesor_persona_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
        session["pending_action"] = "asesor_persona_dni"
        enviar_respuesta(from_number, "Indicános tu *DNI*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_dni":
        if not validar_solo_numeros(text_body):
            enviar_respuesta(from_number, "⚠️ El DNI debe contener solo números.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "asesor_persona_telefono"
        enviar_respuesta(from_number, "Indicános tu *teléfono*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_telefono":
        if not validar_telefono(text_body):
            enviar_respuesta(from_number, "⚠️ El teléfono no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["telefono"] = text_body.strip()
        session["pending_action"] = "asesor_persona_correo"
        enviar_respuesta(from_number, "Indicános tu *correo*:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["correo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_motivo"
        enviar_respuesta(from_number, "Indicános el *motivo* de tu consulta:\n\n0. Volver al menú principal")
        return

    if session["pending_action"] == "asesor_persona_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ El motivo es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_persona_confirmacion":
        if text == "1":
            data = session["temp_asesor_data"]
            registro = {
                "fecha": datetime.now(ZoneInfo("America/Argentina/Mendoza")).isoformat(),
                "whatsapp": normalize_number(from_number),
                "tipo": "persona_fisica",
                "nombre_completo": data.get("nombre_completo", ""),
                "telefono": data.get("telefono", ""),
                "dni": data.get("dni", ""),
                "correo": data.get("correo", ""),
                "motivo": data.get("motivo", ""),
            }
            save_asesor_consulta(registro)
            upsert_user_profile_firestore(
                whatsapp_number=from_number, nombre=data.get("nombre_completo", ""),
                telefono=from_number, intereses=["hablar_con_asesor", "asesoria_persona_fisica"],
                evento="asesoria_persona_confirmada",
                extra_fields={"consulta_asesor_persona": registro}, etiqueta_cliente="lead_asesoria_persona",
            )
            enviar_respuesta(
                from_number,
                "✅ Consulta enviada correctamente.\n\n"
                "Un asesor de Cursala se pondrá en contacto a la brevedad.\n\n"
                + build_asesores_contacto_message(menu_config, "Hola, quiero hablar con un asesor sobre inscripciones.")
            )
            enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
            _enviar_correos_formulario(
                nombre=data.get("nombre_completo", ""),
                correo_usuario=data.get("correo", ""),
                telefono=from_number,
                menu_origen="Formulario persona",
                datos_adicionales={
                    "Nombre completo": data.get("nombre_completo", ""),
                    "DNI": data.get("dni", ""),
                    "Teléfono": data.get("telefono", ""),
                    "Correo": data.get("correo", ""),
                    "Motivo": data.get("motivo", ""),
                },
            )
            if not session.get("notificacion_admin_enviada"):
                _disparar_notificacion_primer_contacto(
                    from_number, session, nombre=data.get("nombre_completo", ""),
                    menu_origen="Asesoría persona física",
                    datos_adicionales={
                        "nombre_completo": data.get("nombre_completo", ""),
                        "telefono": data.get("telefono", ""),
                        "dni": data.get("dni", ""),
                        "correo": data.get("correo", ""),
                        "motivo_consulta": data.get("motivo", ""),
                    },
                )
            reset_user_flow(session)
        elif text == "2":
            session["pending_action"] = "asesor_persona_edit_menu"
            enviar_menu_asesor_persona_editar_lista(from_number)
        else:
            enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_persona_edit_menu":
        if text == "1":
            session["pending_action"] = "asesor_persona_edit_nombre"
            enviar_respuesta(from_number, "Ingresá el nuevo *nombre completo*:\n\n0. Volver al menú principal")
        elif text == "2":
            session["pending_action"] = "asesor_persona_edit_dni"
            enviar_respuesta(from_number, "Ingresá el nuevo *DNI*:\n\n0. Volver al menú principal")
        elif text == "3":
            session["pending_action"] = "asesor_persona_edit_telefono"
            enviar_respuesta(from_number, "Ingresá el nuevo *teléfono*:\n\n0. Volver al menú principal")
        elif text == "4":
            session["pending_action"] = "asesor_persona_edit_correo"
            enviar_respuesta(from_number, "Ingresá el nuevo *correo*:\n\n0. Volver al menú principal")
        elif text == "5":
            session["pending_action"] = "asesor_persona_edit_motivo"
            enviar_respuesta(from_number, "Ingresá el nuevo *motivo*:\n\n0. Volver al menú principal")
        elif text == "0":
            session["pending_action"] = "asesor_persona_confirmacion"
            enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        else:
            enviar_menu_asesor_persona_editar_lista(from_number)
        return

    if session["pending_action"] == "asesor_persona_edit_nombre":
        if not validar_texto_sin_numeros(text_body, min_len=5):
            enviar_respuesta(from_number, "⚠️ Nombre completo inválido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["nombre_completo"] = text_body.strip()
        session["user_name"] = sanitize_contact_name(text_body)
        upsert_user_profile_firestore(
            whatsapp_number=from_number, nombre=text_body.strip(), telefono=from_number,
            evento="edicion_asesor_persona_nombre",
            extra_fields={"nombre_contacto": sanitize_contact_name(text_body)},
        )
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_persona_edit_dni":
        if not validar_solo_numeros(text_body):
            enviar_respuesta(from_number, "⚠️ El DNI debe contener solo números.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["dni"] = "".join(ch for ch in text_body if ch.isdigit())
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_persona_edit_telefono":
        if not validar_telefono(text_body):
            enviar_respuesta(from_number, "⚠️ El teléfono no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["telefono"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_persona_edit_correo":
        if not validar_correo(text_body):
            enviar_respuesta(from_number, "⚠️ El correo no es válido.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["correo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    if session["pending_action"] == "asesor_persona_edit_motivo":
        if len(text_body.strip()) < 10:
            enviar_respuesta(from_number, "⚠️ El motivo es muy breve.\n\n0. Volver al menú principal")
            return
        session["temp_asesor_data"]["motivo"] = text_body.strip()
        session["pending_action"] = "asesor_persona_confirmacion"
        enviar_respuesta(from_number, "✏️ Dato actualizado.")
        enviar_menu_asesor_persona_confirmacion_lista(from_number, session["temp_asesor_data"])
        return

    # ============================================================
    # NAVEGACION DE CURSOS
    # ============================================================

    direct_course_action = parse_course_action_identifier(command_text, menu_config)
    if direct_course_action is not None:
        curso_id, action = direct_course_action
        menu_trace("route_direct_course_action", from_number, command=command_text, curso_id=curso_id, action=action)
        handle_course_detail_action(from_number, curso_id, action, menu_config, session)
        return

    direct_course_selection = parse_course_selection(command_text, menu_config)
    if direct_course_selection is not None:
        menu_trace("route_direct_course_selection", from_number, command=command_text, curso_id=direct_course_selection)
        session["in_course_menu"] = True
        session["in_course_detail"] = True
        session["current_course"] = direct_course_selection
        track_user_interest(from_number, menu_config["cursos"][direct_course_selection]["nombre"], "curso_seleccionado")
        enviar_detalle_curso(from_number, direct_course_selection, menu_config)
        return

    if session["in_course_detail"]:
        curso_id = session["current_course"]
        selected_action = resolve_course_detail_action(text, curso_id)
        menu_trace(
            "route_in_course_detail", from_number, command=command_text, curso_id=curso_id,
            selected_action=selected_action, session=course_session_snapshot(session),
        )
        if selected_action in {"0", "1", "2", "3"}:
            handle_course_detail_action(from_number, curso_id, selected_action, menu_config, session)
        else:
            menu_trace("route_in_course_detail_invalid", from_number, command=command_text, curso_id=curso_id)
            respuesta_ia = responder_con_gemini(text_body, from_number, session)
            if respuesta_ia:
                enviar_respuesta(from_number, respuesta_ia)
                enviar_detalle_curso(from_number, curso_id, menu_config)
                return
            enviar_respuesta(from_number, "Opción inválida. Elegí VER CURSO, TEMARIO, 3 o 0.")
            enviar_detalle_curso(from_number, curso_id, menu_config)
        return

    if session["in_course_menu"]:
        if command_text == "0":
            menu_trace("route_course_menu_home", from_number, command=command_text)
            session["in_course_menu"] = False
            enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        elif command_text == "ver_mas_cursos":
            menu_trace("route_course_menu_more", from_number, command=command_text)
            enviar_menu_cursos_lista(from_number, menu_config, page=1)
        elif command_text in get_unified_courses() or direct_course_selection is not None:
            cursos = get_unified_courses()
            selected_course_id = command_text if command_text in cursos else direct_course_selection
            menu_trace("route_course_menu_select", from_number, command=command_text, curso_id=selected_course_id)
            session["in_course_detail"] = True
            session["current_course"] = selected_course_id
            track_user_interest(from_number, cursos[selected_course_id]["nombre"], "curso_seleccionado")
            enviar_detalle_curso(from_number, selected_course_id, menu_config)
        else:
            menu_trace(
                "route_course_menu_invalid", from_number, command=command_text,
                available_courses=sorted(menu_config["cursos"].keys(), key=int)
            )
            enviar_respuesta(from_number, "Opción inválida.")
            enviar_menu_cursos_lista(from_number, menu_config)
        return

    if session.get("in_response_menu"):
        if command_text == "0":
            session["in_response_menu"] = False
            session["last_response_option"] = None
            enviar_menu_principal_lista(from_number, menu_config, include_greeting=False)
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa: 0 para volver")
        return

    # ============================================================
    # OPCIONES PRINCIPALES DEL MENU
    # ============================================================

    if command_text == "1":
        menu_trace("route_main_option_courses", from_number, command=command_text)
        session["in_course_menu"] = True
        track_user_interest(from_number, "cursos_disponibles", "menu_opcion_1", etiqueta_cliente="interesado_cursos")
        enviar_menu_cursos_lista(from_number, menu_config)
        return

    if command_text == "2":
        # Refactorización: Llama a la función centralizada para iniciar el flujo de empresa.
        iniciar_flujo_empresa(from_number, session)
        return

    if command_text == "3":
        # Refactorización: Llama a la función centralizada para iniciar el flujo de profesional.
        # `saved_name` ya fue obtenido previamente en el flujo de `manejar_usuario`.
        iniciar_flujo_profesional(from_number, session, saved_name)
        return

    if command_text == "4":
        via_audio = bool(session.get("recent_audio_interaction"))
        session["recent_audio_interaction"] = False
        iniciar_flujo_asesor(from_number, session, via_audio=via_audio)
        return

    if command_text in menu_config["responses"]:
        msg = menu_config["responses"][command_text] + "\n\n0. ← Volver al menú principal"
        session["in_response_menu"] = True
        session["last_response_option"] = command_text
        enviar_respuesta(from_number, msg)
        return

    respuesta_ia = responder_con_gemini(text_body, from_number, session)
    if respuesta_ia:
        enviar_respuesta(from_number, respuesta_ia)
        return

    enviar_respuesta(
        from_number,
        "No pude interpretar tu mensaje.\n\n"
        "Escribí *MENU* para ver las opciones o *4* para hablar con un asesor.",
    )
    enviar_menu_principal_lista(from_number, menu_config)
