from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
CONFIG_PATH = os.path.join(BASE_DIR, "menu_config.json")
APP_VERSION = "2026-03-21-empresas-fix-v1"

print("Buscando .env en:", ENV_PATH)
print("Existe .env?:", os.path.exists(ENV_PATH))
print("APP_VERSION:", APP_VERSION)

load_dotenv(dotenv_path=ENV_PATH)

app = FastAPI()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
TEST_RECIPIENT = os.getenv("TEST_RECIPIENT")
ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "5492615031839")
ADMIN_KEY = os.getenv("ADMIN_KEY", "123456")

print("VERIFY_TOKEN cargado:", repr(VERIFY_TOKEN))


def normalize_number(number: str) -> str:
    if not number:
        return ""
    return "".join(ch for ch in str(number) if ch.isdigit())


def is_admin(number: str) -> bool:
    return normalize_number(number) == normalize_number(ADMIN_NUMBER)


def saludo_por_horario() -> str:
    hora = datetime.now(ZoneInfo("America/Argentina/Mendoza")).hour

    if 5 <= hora < 12:
        return "Buen día"
    elif 12 <= hora < 20:
        return "Buenas tardes"
    else:
        return "Buenas noches"


def load_menu_config() -> dict:
    default_config = {
        "greeting": "Bienvenido/a a Cursala.\nGracias por comunicarte con nosotros.\n\n¿Cómo podemos ayudarte hoy?",
        "options": {
            "1": "Cursos disponibles",
            "2": "Capacitaciones para empresas",
            "3": "Quiero capacitar",
            "4": "Quiero hablar con un asesor",
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
            "2": {
                "nombre": "Soldadura",
                "descripcion": "Cursos de soldadura MIG, TIG y SMAW.",
                "link_web": "https://www.cursala.com/cursos/soldadura",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "3": {
                "nombre": "Piping",
                "descripcion": "Diseño e instalación de sistemas de tuberías.",
                "link_web": "https://www.cursala.com/cursos/piping",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "4": {
                "nombre": "Redes y telecomunicaciones",
                "descripcion": "Formación en redes y tecnología IT.",
                "link_web": "https://www.cursala.com/cursos/redes",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "5": {
                "nombre": "Instrumentación y control",
                "descripcion": "Cursos de automatización e instrumentación.",
                "link_web": "https://www.cursala.com/cursos/instrumentacion",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "6": {
                "nombre": "Herramientas para pymes",
                "descripcion": "Capacitación para pequeñas y medianas empresas.",
                "link_web": "https://www.cursala.com/cursos/pymes",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "7": {
                "nombre": "Ensayos No destructivos",
                "descripcion": "Técnicas avanzadas de inspección.",
                "link_web": "https://www.cursala.com/cursos/ensayos",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "8": {
                "nombre": "Diseño mecánico",
                "descripcion": "Formación en CAD y diseño mecanico.",
                "link_web": "https://www.cursala.com/cursos/diseno",
                "link_descarga": "https://drive.google.com/ejemplo",
                "vendedor_id": "1"
            },
            "9": {
                "nombre": "Logística para Pymes",
                "descripcion": "Gestión de cadena de suministro.",
                "link_web": "https://www.cursala.com/cursos/logistica",
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
        }
    }

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        changed = False

        for key in ["greeting", "options", "responses", "cursos", "vendedores"]:
            if key not in config:
                config[key] = default_config[key]
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
            print("⚠️ menu_config.json fue completado con claves faltantes.")
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

        return config

    except FileNotFoundError:
        print("📝 Creando menu_config.json con valores por defecto...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config

    except json.JSONDecodeError as e:
        print(f"⚠️ Error: menu_config.json corrupto. {e}")
        print("Regenerando con valores por defecto...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return default_config


def save_menu_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def reorganize_course_ids():
    if not menu_config.get("cursos"):
        return

    cursos_ordenados = []
    for key in sorted(menu_config["cursos"].keys(), key=int):
        cursos_ordenados.append(menu_config["cursos"][key])

    menu_config["cursos"] = {}
    for index, curso in enumerate(cursos_ordenados, 1):
        menu_config["cursos"][str(index)] = curso

    save_menu_config(menu_config)


try:
    menu_config = load_menu_config()
    print("✅ Configuración cargada correctamente")
    print(f"Claves en menu_config: {menu_config.keys()}")
    admin_sessions = {}
except Exception as e:
    print(f"⚠️ Error cargando configuración: {e}")
    menu_config = {"greeting": "", "options": {}, "responses": {}, "cursos": {}, "vendedores": {}}
    admin_sessions = {}


def get_admin_session(number: str) -> dict:
    key = normalize_number(number)
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
            "temp_course_field_index": 0,
            "last_response_option": None
        }
    return admin_sessions[key]


def reset_user_flow(session: dict):
    session["in_course_menu"] = False
    session["in_course_detail"] = False
    session["in_response_menu"] = False
    session["current_course"] = None
    session["pending_action"] = None
    session["temp_option"] = None
    session["temp_option_text"] = None
    session["temp_field"] = None
    session["temp_course_data"] = {}
    session["last_response_option"] = None


def build_main_menu() -> str:
    saludo = saludo_por_horario()
    lines = [f"{saludo} 👋", menu_config["greeting"], ""]
    for key in sorted(menu_config["options"].keys(), key=int):
        lines.append(f"{key}. {menu_config['options'][key]}")
    lines.append("\nPor favor, respondé con el número de la opción que te interesa.")
    return "\n".join(lines)


def build_courses_menu() -> str:
    if "cursos" not in menu_config:
        return "⚠️ Error: No hay cursos disponibles. Por favor, contacta al administrador."
    menu = "📚 MENÚ DE CURSOS DISPONIBLES\n\n"
    for key in sorted(menu_config["cursos"].keys(), key=int):
        menu += f"{key}. {menu_config['cursos'][key]['nombre']}\n"
    menu += "\n0. Volver al menú principal"
    return menu


def build_course_detail_menu(curso_id: str) -> str:
    if curso_id not in menu_config["cursos"]:
        return "Curso no encontrado."
    curso = menu_config["cursos"][curso_id]
    return (
        f"📖 {curso['nombre'].upper()}\n\n"
        f"{curso['descripcion']}\n\n"
        "1. 🌐 Ver en la web\n"
        "2. 📥 Descargar programa\n"
        "3. 💳 Comprar\n"
        "0. ↩️ Volver"
    )


def build_courses_edit_menu() -> str:
    menu = "📚 EDITAR CURSOS DISPONIBLES\n\n"
    menu += "1. ➕ Agregar curso\n"
    menu += "2. ❌ Eliminar curso\n"
    menu += "3. ✏️ Editar curso\n"
    menu += "4. 📋 Ver cursos disponibles\n"
    menu += "\n0. Volver al menú admin"
    return menu


def build_admin_menu() -> str:
    return (
        "⚙️ MODO ADMINISTRADOR\n\n"
        "1. Ver menú actual\n"
        "2. Modificar saludo\n"
        "3. Editar opción\n"
        "4. Agregar opción\n"
        "5. Modificar respuesta\n"
        "6. Editar cursos disponibles\n"
        "7. Gestionar vendedores\n"
        "8. Deshacer cambio\n"
        "9. Desactivar admin\n\n"
        "0. Volver al menú principal"
    )


def enviar_respuesta(to_number: str, message: str):
    destino = TEST_RECIPIENT if TEST_RECIPIENT else to_number
    print(f"Enviando a {destino}: {message[:80]}...")

    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        print("⚠️ Credenciales no configuradas")
        return

    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "text",
        "text": {"body": message}
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=15
        )
        print(f"Respuesta Meta: {response.status_code} - {response.text}")

    except requests.exceptions.Timeout:
        print("⚠️ Timeout enviando mensaje a Meta")

    except requests.exceptions.RequestException as e:
        print(f"⚠️ Error HTTP enviando mensaje: {e}")

    except Exception as e:
        print(f"⚠️ Error inesperado enviando mensaje: {e}")


def manejar_usuario(from_number: str, text_body: str):
    session = get_admin_session(from_number)
    text = text_body.strip()
    text_lower = text.lower()

    if text_lower in ["hola", "menu", "inicio"]:
        reset_user_flow(session)
        enviar_respuesta(from_number, build_main_menu())
        return

    if text_lower == "admin":
        if not is_admin(from_number):
            enviar_respuesta(from_number, "❌ No autorizado.")
            return
        session["awaiting_admin_password"] = True
        enviar_respuesta(from_number, "Por favor, ingresá la contraseña:")
        return

    if session["pending_action"] == "empresa_nombre":
        session["temp_course_data"]["empresa"] = text_body
        enviar_respuesta(from_number, "Perfecto. Ahora indicános el CUIT de la empresa:")
        session["pending_action"] = "empresa_cuit"
        return

    if session["pending_action"] == "empresa_cuit":
        session["temp_course_data"]["cuit"] = text_body
        enviar_respuesta(from_number, "Gracias. ¿En qué provincia se encuentra la empresa?")
        session["pending_action"] = "empresa_provincia"
        return

    if session["pending_action"] == "empresa_provincia":
        session["temp_course_data"]["provincia"] = text_body
        enviar_respuesta(from_number, "Indicános un correo de contacto:")
        session["pending_action"] = "empresa_correo"
        return

    if session["pending_action"] == "empresa_correo":
        session["temp_course_data"]["correo"] = text_body
        enviar_respuesta(from_number, "Ahora compartinos un teléfono de contacto:")
        session["pending_action"] = "empresa_telefono"
        return

    if session["pending_action"] == "empresa_telefono":
        session["temp_course_data"]["telefono"] = text_body
        enviar_respuesta(from_number, "Por favor, describí las necesidades de formación de tu empresa:")
        session["pending_action"] = "empresa_necesidades"
        return

    if session["pending_action"] == "empresa_necesidades":
        session["temp_course_data"]["necesidades"] = text_body

        resumen = (
            "✅ Gracias por la información.\n\n"
            "Hemos registrado los siguientes datos:\n"
            f"🏢 Empresa: {session['temp_course_data'].get('empresa', '')}\n"
            f"🧾 CUIT: {session['temp_course_data'].get('cuit', '')}\n"
            f"📍 Provincia: {session['temp_course_data'].get('provincia', '')}\n"
            f"📧 Correo: {session['temp_course_data'].get('correo', '')}\n"
            f"📞 Teléfono: {session['temp_course_data'].get('telefono', '')}\n"
            f"📝 Necesidades de formación: {session['temp_course_data'].get('necesidades', '')}\n\n"
            "Un asesor de Cursala se pondrá en contacto a la brevedad para brindarte la información solicitada."
        )

        enviar_respuesta(from_number, resumen)
        reset_user_flow(session)
        return

    if session["in_course_detail"]:
        curso_id = session["current_course"]
        if text == "0":
            session["in_course_detail"] = False
            session["current_course"] = None
            enviar_respuesta(from_number, build_courses_menu())
        elif text == "1":
            curso = menu_config["cursos"].get(curso_id, {})
            enviar_respuesta(from_number, f"🌐 Link: {curso.get('link_web', 'N/A')}\n\n0. Volver")
        elif text == "2":
            curso = menu_config["cursos"].get(curso_id, {})
            enviar_respuesta(from_number, f"📥 Descarga: {curso.get('link_descarga', 'N/A')}\n\n0. Volver")
        elif text == "3":
            curso = menu_config["cursos"].get(curso_id, {})
            vendedor_id = curso.get("vendedor_id", "1")
            vendedor = menu_config["vendedores"].get(vendedor_id, {})
            msg = (
                f"📞 Contacta a:\n"
                f"{vendedor.get('nombre', 'N/A')} {vendedor.get('apellido', 'N/A')}\n"
                f"📱 {vendedor.get('telefono', 'N/A')}\n"
                f"📧 {vendedor.get('correo', 'N/A')}"
            )
            enviar_respuesta(from_number, msg)
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_course_detail_menu(curso_id))
        return

    if session["in_course_menu"]:
        if text == "0":
            session["in_course_menu"] = False
            enviar_respuesta(from_number, build_main_menu())
        elif text in menu_config["cursos"]:
            session["in_course_detail"] = True
            session["current_course"] = text
            enviar_respuesta(from_number, build_course_detail_menu(text))
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_courses_menu())
        return

    if session.get("in_response_menu"):
        if text == "0":
            session["in_response_menu"] = False
            session["last_response_option"] = None
            enviar_respuesta(from_number, build_main_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa: 0 para volver")
        return

    if text == "1":
        session["in_course_menu"] = True
        enviar_respuesta(from_number, build_courses_menu())
        return

    if text == "2":
        session["temp_course_data"] = {}
        session["pending_action"] = "empresa_nombre"
        session["in_response_menu"] = False
        session["last_response_option"] = None
        enviar_respuesta(
            from_number,
            "Excelente. Para poder asesorarte mejor, indicános el nombre de la empresa:"
        )
        return

    if text in menu_config["responses"]:
        msg = menu_config["responses"][text] + "\n\n0. ← Volver al menú principal"
        session["in_response_menu"] = True
        session["last_response_option"] = text
        enviar_respuesta(from_number, msg)
        return

    enviar_respuesta(from_number, "Opción inválida.\n\n" + build_main_menu())


def manejar_admin(from_number: str, text_body: str):
    global menu_config
    session = get_admin_session(from_number)
    text = text_body.strip()
    text_lower = text.lower()

    if session["awaiting_admin_password"]:
        if text == ADMIN_KEY:
            session["active"] = True
            session["awaiting_admin_password"] = False
            enviar_respuesta(from_number, build_admin_menu())
        else:
            session["awaiting_admin_password"] = False
            enviar_respuesta(from_number, "❌ Contraseña incorrecta.\n\n" + build_main_menu())
        return

    if not session["active"]:
        manejar_usuario(from_number, text_body)
        return

    if text_lower in ["hola", "menu", "inicio"]:
        session["active"] = False
        session["awaiting_admin_password"] = False
        reset_user_flow(session)
        enviar_respuesta(from_number, build_main_menu())
        return

    if session["pending_action"] == "awaiting_course_name":
        session["temp_course_data"]["nombre"] = text_body
        enviar_respuesta(from_number, "✅ Nombre ingresado.\n\n📝 Ahora ingresa el link del curso (sitio web):")
        session["pending_action"] = "awaiting_course_link"
        return

    if session["pending_action"] == "awaiting_course_link":
        session["temp_course_data"]["link_web"] = text_body
        enviar_respuesta(from_number, "✅ Link del curso ingresado.\n\n📄 Ahora ingresa el link del PDF del programa:")
        session["pending_action"] = "awaiting_course_pdf"
        return

    if session["pending_action"] == "awaiting_course_pdf":
        session["temp_course_data"]["link_descarga"] = text_body

        resumen = "📋 RESUMEN DE DATOS INGRESADOS\n\n"
        resumen += f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
        resumen += f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
        resumen += f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
        resumen += "¿Deseas continuar?\n"
        resumen += "1. ✅ ACEPTAR\n"
        resumen += "2. ✏️ EDITAR\n\n"
        resumen += "Escribe tu opción:"

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
                "vendedor_id": "1"
            }
            save_menu_config(menu_config)

            enviar_respuesta(
                from_number,
                f"✅ Curso '{session['temp_course_data']['nombre']}' agregado exitosamente con ID {nuevo_id}.\n\n"
                + build_courses_edit_menu()
            )
            session["pending_action"] = None
            session["temp_course_data"] = {}
        elif text == "2":
            menu_edit = "✏️ ¿QUÉ DESEAS EDITAR?\n\n"
            menu_edit += "1. ✏️ Nombre\n"
            menu_edit += "2. ✏️ Link Curso\n"
            menu_edit += "3. ✏️ Link PDF\n"
            menu_edit += "\n0. Volver\n\nEscribe tu opción:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field_add"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Usa 1 o 2.")
        return

    if session["pending_action"] == "edit_course_field_add":
        fields = {
            "1": ("nombre", "Nombre del curso"),
            "2": ("link_web", "Link del curso"),
            "3": ("link_descarga", "Link del PDF")
        }
        if text == "0":
            resumen = "📋 RESUMEN DE DATOS INGRESADOS\n\n"
            resumen += f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
            resumen += f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
            resumen += f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
            resumen += "¿Deseas continuar?\n"
            resumen += "1. ✅ ACEPTAR\n"
            resumen += "2. ✏️ EDITAR\n\n"
            resumen += "Escribe tu opción:"
            enviar_respuesta(from_number, resumen)
            session["pending_action"] = "confirm_course_data"
        elif text in fields:
            field_key, field_name = fields[text]
            session["temp_field"] = field_key
            enviar_respuesta(from_number, f"📝 Ingresa el nuevo valor para {field_name}:")
            session["pending_action"] = "awaiting_field_value_add"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Intenta de nuevo.")
        return

    if session["pending_action"] == "awaiting_field_value_add":
        field = session["temp_field"]
        session["temp_course_data"][field] = text_body

        resumen = "📋 RESUMEN DE DATOS INGRESADOS\n\n"
        resumen += f"📖 Nombre: {session['temp_course_data']['nombre']}\n"
        resumen += f"🌐 Link Curso: {session['temp_course_data']['link_web']}\n"
        resumen += f"📄 Link PDF: {session['temp_course_data']['link_descarga']}\n\n"
        resumen += "¿Deseas continuar?\n"
        resumen += "1. ✅ ACEPTAR\n"
        resumen += "2. ✏️ EDITAR\n\n"
        resumen += "Escribe tu opción:"

        enviar_respuesta(from_number, resumen)
        session["pending_action"] = "confirm_course_data"
        session["temp_field"] = None
        return

    if session["pending_action"] == "delete_course":
        if text in menu_config["cursos"]:
            curso = menu_config["cursos"][text]
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"⚠️ ¿Estás seguro de eliminar '{curso['nombre']}'?\n\n1. ✅ Sí\n0. ❌ No\n\nEscribe tu opción:"
            )
            session["pending_action"] = "confirm_delete_course"
        else:
            enviar_respuesta(from_number, "❌ Curso no encontrado. Intenta de nuevo.\n\n" + build_courses_menu())
        return

    if session["pending_action"] == "confirm_delete_course":
        if text == "1":
            curso_id = session["temp_option"]
            curso = menu_config["cursos"][curso_id]
            del menu_config["cursos"][curso_id]
            reorganize_course_ids()
            enviar_respuesta(
                from_number,
                f"✅ Curso '{curso['nombre']}' eliminado exitosamente.\n\nℹ️ Los IDs se han reorganizado automáticamente.\n\n"
                + build_courses_edit_menu()
            )
        elif text == "0":
            enviar_respuesta(from_number, "❌ Eliminación cancelada.\n\n" + build_courses_edit_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida. Usa 1 o 0.")
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "edit_course_select":
        if text in menu_config["cursos"]:
            session["current_course"] = text
            curso = menu_config["cursos"][text]
            menu_edit = f"📝 EDITAR CURSO: {curso['nombre']}\n\n"
            menu_edit += "1. ✏️ Nombre\n"
            menu_edit += "2. ✏️ Descripción\n"
            menu_edit += "3. ✏️ Link web\n"
            menu_edit += "4. ✏️ Link descarga\n"
            menu_edit += "\n0. Volver\n\nEscribe el número del campo a editar:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_course_field"
        else:
            enviar_respuesta(from_number, "❌ Curso no encontrado. Intenta de nuevo.\n\n" + build_courses_menu())
        return

    if session["pending_action"] == "edit_course_field":
        fields = {"1": "nombre", "2": "descripcion", "3": "link_web", "4": "link_descarga"}
        if text == "0":
            session["pending_action"] = None
            session["current_course"] = None
            enviar_respuesta(from_number, build_courses_edit_menu())
        elif text in fields:
            session["temp_field"] = fields[text]
            field_name = {
                "nombre": "nombre",
                "descripcion": "descripción",
                "link_web": "link web",
                "link_descarga": "link de descarga"
            }
            enviar_respuesta(from_number, f"📝 Ingresa el nuevo valor para {field_name.get(fields[text], fields[text])}:")
            session["pending_action"] = "awaiting_field_value"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida. Intenta de nuevo.")
        return

    if session["pending_action"] == "awaiting_field_value":
        curso_id = session["current_course"]
        field = session["temp_field"]
        menu_config["cursos"][curso_id][field] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, f"✅ Campo actualizado exitosamente.\n\n" + build_courses_edit_menu())
        session["pending_action"] = None
        session["temp_field"] = None
        session["current_course"] = None
        return

    if session["in_courses_edit_menu"]:
        if text == "0":
            session["in_courses_edit_menu"] = False
            enviar_respuesta(from_number, build_admin_menu())
        elif text == "1":
            session["temp_course_data"] = {}
            enviar_respuesta(from_number, "📝 AGREGAR NUEVO CURSO\n\n¿Cuál es el nombre del curso?")
            session["pending_action"] = "awaiting_course_name"
        elif text == "2":
            enviar_respuesta(from_number, "❌ Ingresa el número del curso a eliminar:\n\n" + build_courses_menu())
            session["pending_action"] = "delete_course"
        elif text == "3":
            enviar_respuesta(from_number, "✏️ Ingresa el número del curso a editar:\n\n" + build_courses_menu())
            session["pending_action"] = "edit_course_select"
        elif text == "4":
            enviar_respuesta(from_number, build_courses_menu())
        else:
            enviar_respuesta(from_number, "Opción inválida.\n\n" + build_courses_edit_menu())
        return

    if text == "0":
        session["active"] = False
        reset_user_flow(session)
        enviar_respuesta(from_number, build_main_menu())
        return

    if text == "1":
        enviar_respuesta(from_number, "📋 " + build_main_menu())
        return

    if text == "2":
        enviar_respuesta(from_number, f"📝 SALUDO ACTUAL:\n\n{menu_config['greeting']}\n\n✏️ Escribe el nuevo saludo:")
        session["pending_action"] = "edit_greeting"
        return

    if text == "3":
        menu_str = "✏️ EDITAR OPCIÓN DEL MENÚ\n\n"
        for key in sorted(menu_config["options"].keys(), key=int):
            menu_str += f"{key}. {menu_config['options'][key]}\n"
        menu_str += "\n¿Qué opción deseas editar? (1-" + str(len(menu_config["options"])) + ")"
        enviar_respuesta(from_number, menu_str)
        session["pending_action"] = "edit_option_select"
        return

    if text == "4":
        enviar_respuesta(from_number, "➕ AGREGAR NUEVA OPCIÓN\n\n¿Cuál es el título de la nueva opción?")
        session["pending_action"] = "add_option_title"
        return

    if text == "5":
        resp_str = "📝 EDITAR RESPUESTA\n\n"
        for key in sorted(menu_config["responses"].keys(), key=int):
            resp_str += f"{key}. {menu_config['responses'][key][:40]}...\n"
        resp_str += "\n¿Qué respuesta deseas editar? (1-" + str(len(menu_config["responses"])) + ")"
        enviar_respuesta(from_number, resp_str)
        session["pending_action"] = "edit_response_select"
        return

    if text == "6":
        session["in_courses_edit_menu"] = True
        enviar_respuesta(from_number, build_courses_edit_menu())
        return

    if text == "7":
        vendor_str = "👥 GESTOR DE VENDEDORES\n\n"
        for key in sorted(menu_config["vendedores"].keys(), key=int):
            vendor = menu_config["vendedores"][key]
            vendor_str += f"{key}. {vendor['nombre']} {vendor['apellido']}\n"
        vendor_str += "\n1. ➕ Agregar vendedor\n"
        vendor_str += "2. ✏️ Editar vendedor\n"
        vendor_str += "3. ❌ Eliminar vendedor\n"
        vendor_str += "\n0. Volver\n\nEscribe tu opción:"
        enviar_respuesta(from_number, vendor_str)
        session["pending_action"] = "vendor_menu"
        return

    if text == "8":
        if session["change_history"]:
            ultimo_cambio = session["change_history"].pop()
            enviar_respuesta(from_number, f"⏮️ Cambio deshecho:\n{ultimo_cambio}\n\n" + build_admin_menu())
        else:
            enviar_respuesta(from_number, "❌ No hay cambios para deshacer.\n\n" + build_admin_menu())
        return

    if text == "9":
        session["active"] = False
        reset_user_flow(session)
        enviar_respuesta(from_number, "✅ Admin desactivado.\n\n" + build_main_menu())
        return

    if session["pending_action"] == "edit_greeting":
        session["change_history"].append(f"Saludo anterior: {menu_config['greeting'][:50]}...")
        menu_config["greeting"] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Saludo actualizado.\n\n" + build_admin_menu())
        session["pending_action"] = None
        return

    if session["pending_action"] == "edit_option_select":
        if text in menu_config["options"]:
            session["temp_option"] = text
            enviar_respuesta(from_number, f"✏️ OPCIÓN ACTUAL: {menu_config['options'][text]}\n\nEscribe el nuevo texto:")
            session["pending_action"] = "edit_option_text"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.")
        return

    if session["pending_action"] == "edit_option_text":
        option_id = session["temp_option"]
        session["change_history"].append(f"Opción {option_id}: '{menu_config['options'][option_id]}' → '{text_body}'")
        menu_config["options"][option_id] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Opción actualizada.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "add_option_title":
        session["temp_option_text"] = text_body
        enviar_respuesta(from_number, f"💬 Título: '{text_body}'\n\n¿Cuál será la respuesta a esta opción?")
        session["pending_action"] = "add_option_response"
        return

    if session["pending_action"] == "add_option_response":
        max_id = max([int(k) for k in menu_config["options"].keys()]) if menu_config["options"] else 0
        nuevo_id = str(max_id + 1)
        menu_config["options"][nuevo_id] = session["temp_option_text"]
        menu_config["responses"][nuevo_id] = text_body
        save_menu_config(menu_config)
        session["change_history"].append(f"Opción agregada: {nuevo_id}. {session['temp_option_text']}")
        enviar_respuesta(from_number, f"✅ Opción [{nuevo_id}] agregada con éxito.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option_text"] = None
        return

    if session["pending_action"] == "edit_response_select":
        if text in menu_config["responses"]:
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"📝 RESPUESTA ACTUAL ({text}):\n\n{menu_config['responses'][text]}\n\n✏️ Escribe la nueva respuesta:"
            )
            session["pending_action"] = "edit_response_text"
        else:
            enviar_respuesta(from_number, "❌ Respuesta no encontrada.")
        return

    if session["pending_action"] == "edit_response_text":
        response_id = session["temp_option"]
        session["change_history"].append(
            f"Respuesta {response_id}: '{menu_config['responses'][response_id][:40]}...' → '{text_body[:40]}...'"
        )
        menu_config["responses"][response_id] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Respuesta actualizada.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "vendor_menu":
        if text == "0":
            session["pending_action"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text == "1":
            enviar_respuesta(from_number, "➕ AGREGAR VENDEDOR\n\n¿Cuál es el nombre del vendedor?")
            session["pending_action"] = "add_vendor_name"
        elif text == "2":
            vendor_str = "✏️ EDITAR VENDEDOR\n\n"
            for key in sorted(menu_config["vendedores"].keys(), key=int):
                vendor = menu_config["vendedores"][key]
                vendor_str += f"{key}. {vendor['nombre']} {vendor['apellido']}\n"
            vendor_str += "\n¿Cuál deseas editar?"
            enviar_respuesta(from_number, vendor_str)
            session["pending_action"] = "edit_vendor_select"
        elif text == "3":
            vendor_str = "❌ ELIMINAR VENDEDOR\n\n"
            for key in sorted(menu_config["vendedores"].keys(), key=int):
                vendor = menu_config["vendedores"][key]
                vendor_str += f"{key}. {vendor['nombre']} {vendor['apellido']}\n"
            vendor_str += "\n¿Cuál deseas eliminar?"
            enviar_respuesta(from_number, vendor_str)
            session["pending_action"] = "delete_vendor"
        return

    if session["pending_action"] == "add_vendor_name":
        session["temp_option_text"] = text_body
        session["temp_course_data"] = {}
        enviar_respuesta(from_number, "Apellido:")
        session["pending_action"] = "add_vendor_lastname"
        return

    if session["pending_action"] == "add_vendor_lastname":
        session["temp_course_data"]["apellido"] = text_body
        enviar_respuesta(from_number, "Teléfono:")
        session["pending_action"] = "add_vendor_phone"
        return

    if session["pending_action"] == "add_vendor_phone":
        session["temp_course_data"]["telefono"] = text_body
        enviar_respuesta(from_number, "Correo:")
        session["pending_action"] = "add_vendor_email"
        return

    if session["pending_action"] == "add_vendor_email":
        max_id = max([int(k) for k in menu_config["vendedores"].keys()]) if menu_config["vendedores"] else 0
        nuevo_id = str(max_id + 1)
        menu_config["vendedores"][nuevo_id] = {
            "nombre": session["temp_option_text"],
            "apellido": session["temp_course_data"].get("apellido", ""),
            "telefono": session["temp_course_data"].get("telefono", ""),
            "correo": text_body
        }
        save_menu_config(menu_config)
        session["change_history"].append(f"Vendedor agregado: {session['temp_option_text']}")
        enviar_respuesta(from_number, "✅ Vendedor agregado.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option_text"] = None
        session["temp_course_data"] = {}
        return

    if session["pending_action"] == "edit_vendor_select":
        if text in menu_config["vendedores"]:
            session["temp_option"] = text
            vendor = menu_config["vendedores"][text]
            menu_edit = f"✏️ EDITAR VENDEDOR: {vendor['nombre']} {vendor['apellido']}\n\n"
            menu_edit += "1. 📝 Nombre\n"
            menu_edit += "2. 📝 Apellido\n"
            menu_edit += "3. 📱 Teléfono\n"
            menu_edit += "4. 📧 Correo\n"
            menu_edit += "\n0. Volver\n\nEscribe tu opción:"
            enviar_respuesta(from_number, menu_edit)
            session["pending_action"] = "edit_vendor_field"
        else:
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.")
        return

    if session["pending_action"] == "edit_vendor_field":
        fields = {"1": "nombre", "2": "apellido", "3": "telefono", "4": "correo"}
        if text == "0":
            session["pending_action"] = None
            session["temp_option"] = None
            enviar_respuesta(from_number, build_admin_menu())
        elif text in fields:
            session["temp_field"] = fields[text]
            field_names = {
                "nombre": "Nombre",
                "apellido": "Apellido",
                "telefono": "Teléfono",
                "correo": "Correo"
            }
            enviar_respuesta(from_number, f"📝 Nuevo {field_names.get(fields[text], fields[text])}:")
            session["pending_action"] = "edit_vendor_value"
        else:
            enviar_respuesta(from_number, "❌ Opción inválida.")
        return

    if session["pending_action"] == "edit_vendor_value":
        vendor_id = session["temp_option"]
        field = session["temp_field"]
        menu_config["vendedores"][vendor_id][field] = text_body
        save_menu_config(menu_config)
        enviar_respuesta(from_number, "✅ Vendedor actualizado.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_field"] = None
        session["temp_option"] = None
        return

    if session["pending_action"] == "delete_vendor":
        if text in menu_config["vendedores"]:
            vendor = menu_config["vendedores"][text]
            session["temp_option"] = text
            enviar_respuesta(
                from_number,
                f"⚠️ ¿Estás seguro de eliminar '{vendor['nombre']} {vendor['apellido']}'?\n\n1. ✅ Sí\n0. ❌ No"
            )
            session["pending_action"] = "confirm_delete_vendor"
        else:
            enviar_respuesta(from_number, "❌ Vendedor no encontrado.")
        return

    if session["pending_action"] == "confirm_delete_vendor":
        if text == "1":
            vendor_id = session["temp_option"]
            vendor = menu_config["vendedores"][vendor_id]
            del menu_config["vendedores"][vendor_id]
            save_menu_config(menu_config)
            session["change_history"].append(f"Vendedor eliminado: {vendor['nombre']} {vendor['apellido']}")
            enviar_respuesta(from_number, "✅ Vendedor eliminado.\n\n" + build_admin_menu())
        elif text == "0":
            enviar_respuesta(from_number, "❌ Eliminación cancelada.\n\n" + build_admin_menu())
        session["pending_action"] = None
        session["temp_option"] = None
        return

    enviar_respuesta(from_number, "❌ Opción inválida. " + build_admin_menu())


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Invalid token", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print("Webhook:", data)
    print("APP_VERSION webhook:", APP_VERSION)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        messages = value.get("messages")
        statuses = value.get("statuses")

        if messages:
            print("MENSAJE ENTRANTE:", messages)

        if statuses:
            print("STATUS:", statuses)

        if messages:
            msg = messages[0]
            from_number = msg.get("from", "")

            if msg.get("type") == "text":
                text_body = msg["text"]["body"].strip()
                print(f"De {from_number}: {text_body}")
                manejar_admin(from_number, text_body)
            else:
                print(f"Mensaje no soportado. Tipo recibido: {msg.get('type')}")

    except Exception as e:
        print(f"Error en webhook: {e}")
        import traceback
        traceback.print_exc()

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)