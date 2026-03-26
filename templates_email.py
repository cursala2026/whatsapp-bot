"""Plantillas de correo electrónico para el bot de WhatsApp de Cursala."""


def armar_correo_bienvenida(nombre: str) -> tuple[str, str, str]:
    """Correo de bienvenida para enviar al usuario registrado."""
    subject = "Bienvenido a Cursala"
    html = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#333;">
        <h2>¡Hola {nombre or ''}!</h2>
        <p>Te damos la bienvenida a <strong>Cursala</strong>.</p>
        <p>Gracias por tu interés en nuestra plataforma de capacitación.</p>
        <p>Muy pronto podremos enviarte información útil sobre cursos, novedades y oportunidades.</p>
        <br>
        <p>Saludos cordiales,<br><strong>Cursala</strong></p>
      </body>
    </html>
    """
    text = (
        f"Hola {nombre or ''}\n\n"
        "Te damos la bienvenida a Cursala.\n"
        "Gracias por tu interés en nuestra plataforma de capacitación.\n\n"
        "Saludos cordiales,\nCursala"
    )
    return subject, html, text


def armar_correo_notificacion_registro(
    nombre: str,
    telefono: str,
    menu_origen: str,
    asunto: str = "Nuevo contacto en WhatsApp Bot - Cursala",
    cuerpo_intro: str = "Se ha registrado un nuevo usuario en el bot de Cursala.",
    datos_adicionales: dict = None,
) -> tuple[str, str, str]:
    """Notificación interna al equipo de Cursala cuando un nuevo usuario contacta el bot."""
    if datos_adicionales is None:
        datos_adicionales = {}
    
    subject = asunto
    
    # Construir filas de la tabla con datos básicos + adicionales
    filas_html = f"""
          <tr style="background:#f5f5f5;">
            <td style="border:1px solid #ddd;"><strong>Nombre</strong></td>
            <td style="border:1px solid #ddd;">{nombre or "(sin nombre)"}</td>
          </tr>
          <tr>
            <td style="border:1px solid #ddd;"><strong>Teléfono</strong></td>
            <td style="border:1px solid #ddd;">+{telefono}</td>
          </tr>
          <tr style="background:#f5f5f5;">
            <td style="border:1px solid #ddd;"><strong>Menú de origen</strong></td>
            <td style="border:1px solid #ddd;">{menu_origen}</td>
          </tr>"""
    
    filas_text = f"Nombre: {nombre or '(sin nombre)'}\nTeléfono: +{telefono}\nMenú de origen: {menu_origen}\n"
    
    # Agregar datos adicionales
    for clave, valor in datos_adicionales.items():
        etiqueta = clave.replace("_", " ").title()
        valor_str = str(valor) if valor else "(sin datos)"
        filas_html += f"""
          <tr>
            <td style="border:1px solid #ddd;"><strong>{etiqueta}</strong></td>
            <td style="border:1px solid #ddd;">{valor_str}</td>
          </tr>"""
        filas_text += f"{etiqueta}: {valor_str}\n"
    
    html = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#333;">
        <h2>&#128241; Nuevo contacto registrado</h2>
        <p>{cuerpo_intro}</p>
        <table cellpadding="10" style="border-collapse:collapse;margin-top:16px;width:100%;max-width:600px;">
{filas_html}
        </table>
        <p style="color:#999;font-size:12px;margin-top:24px;">
          Notificaci&oacute;n autom&aacute;tica generada por el Bot de WhatsApp de Cursala.
        </p>
      </body>
    </html>
    """
    text = f"{cuerpo_intro}\n\n{filas_text}"
    return subject, html, text
