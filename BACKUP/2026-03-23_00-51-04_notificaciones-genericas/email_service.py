import os
import requests
from typing import Optional


def enviar_correo_brevo(
    to_email: str,
    to_name: Optional[str],
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
) -> tuple[bool, str]:
    api_key = os.getenv("BREVO_API_KEY", "")
    from_email = os.getenv("MAIL_FROM_EMAIL", "")
    from_name = os.getenv("MAIL_FROM_NAME", "Cursala")

    if not api_key:
        return False, "Falta BREVO_API_KEY en .env"

    if not from_email:
        return False, "Falta MAIL_FROM_EMAIL en .env"

    url = "https://api.brevo.com/v3/smtp/email"

    payload = {
        "sender": {
            "name": from_name,
            "email": from_email
        },
        "to": [
            {
                "email": to_email,
                "name": to_name or ""
            }
        ],
        "subject": subject,
        "htmlContent": html_content
    }

    if text_content:
        payload["textContent"] = text_content

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if 200 <= r.status_code < 300:
            data = r.json() if r.content else {}
            message_id = data.get("messageId", "sin_message_id")
            return True, message_id

        return False, f"{r.status_code} - {r.text}"

    except Exception as e:
        return False, str(e)


def procesar_notificacion_registro(
    telefono: str,
    nombre: str,
    menu_origen: str,
    destinatario: str,
    asunto: str,
    cuerpo_intro: str,
    datos_adicionales: dict = None,
) -> tuple[bool, str]:
    """Envía la notificación de nuevo registro al equipo de Cursala."""
    from templates_email import armar_correo_notificacion_registro

    if datos_adicionales is None:
        datos_adicionales = {}

    subject, html, text = armar_correo_notificacion_registro(
        nombre=nombre,
        telefono=telefono,
        menu_origen=menu_origen,
        asunto=asunto,
        cuerpo_intro=cuerpo_intro,
        datos_adicionales=datos_adicionales,
    )
    return enviar_correo_brevo(
        to_email=destinatario,
        to_name="Equipo Cursala",
        subject=subject,
        html_content=html,
        text_content=text,
    )


def enviar_notificacion_evento(
    tipo_evento: str,
    telefono: str,
    nombre: str,
    menu_origen: str,
    destinatario: str,
    asunto: str = "",
    cuerpo_intro: str = "",
    datos_adicionales: dict = None,
) -> tuple[bool, str]:
    """Función genérica para enviar notificaciones de cualquier tipo de evento.
    
    Parámetros:
    - tipo_evento: Identificador único del evento (ej: 'registro_empresa', 'consulta_asesor')
    - telefono: Teléfono normalizado del usuario
    - nombre: Nombre principal (empresa, persona, etc)
    - menu_origen: Descripción del menú/flujo de origen
    - destinatario: Email donde enviar (ej: info@cursala.com.ar)
    - asunto: Línea de asunto del correo (si vacío, se usa default)
    - cuerpo_intro: Introducción personalizada (si vacío, se usa default)
    - datos_adicionales: Dict con todos los datos del evento
    
    Retorna: (bool, str) - (éxito, messageId o error)
    """
    from templates_email import armar_correo_notificacion_registro
    
    if datos_adicionales is None:
        datos_adicionales = {}
    
    if not asunto:
        asunto = f"Nuevo evento: {menu_origen} - Cursala Bot"
    if not cuerpo_intro:
        cuerpo_intro = f"Se ha registrado un nuevo evento de {menu_origen}."
    
    subject, html, text = armar_correo_notificacion_registro(
        nombre=nombre,
        telefono=telefono,
        menu_origen=menu_origen,
        asunto=asunto,
        cuerpo_intro=cuerpo_intro,
        datos_adicionales=datos_adicionales,
    )
    
    return enviar_correo_brevo(
        to_email=destinatario,
        to_name="Equipo Cursala",
        subject=subject,
        html_content=html,
        text_content=text,
    )