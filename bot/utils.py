"""bot/utils.py — Helpers puros de normalizacion, parsing y validacion.

Este modulo evita dependencias cruzadas para poder reutilizarse desde
webhook, flujos y base de datos sin acoplamiento adicional.
"""

import re
import unicodedata
import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from bot.config import logger, ADMIN_NUMBER


# ============================================================
# NORMALIZACION DE NUMEROS E IDENTIFICADORES
# ============================================================

def normalize_number(number: str) -> str:
    if not number:
        return ""
    return "".join(ch for ch in str(number) if ch.isdigit())


def is_bsuid(identifier: str) -> bool:
    """Verifica si el identificador es un BSUID (contiene punto)."""
    return bool(identifier and "." in str(identifier))


def get_session_key(identifier: str) -> str:
    """Genera clave de sesión para teléfono o BSUID."""
    if not identifier:
        return ""
    if is_bsuid(identifier):
        return str(identifier).strip().upper()
    return normalize_number(identifier)


def is_admin(number: str) -> bool:
    return normalize_number(number) == normalize_number(ADMIN_NUMBER)


# ============================================================
# VALIDACIONES DE ENTRADA
# ============================================================

PROVINCIAS_ARGENTINA = {
    "buenos aires", "catamarca", "chaco", "chubut", "córdoba", "cordoba",
    "corrientes", "entre ríos", "entre rios", "formosa", "jujuy",
    "la pampa", "la rioja", "mendoza", "misiones", "neuquén", "neuquen",
    "río negro", "rio negro", "salta", "san juan", "san luis",
    "santa cruz", "santa fe", "santiago del estero",
    "tierra del fuego", "antártida e islas del atlántico sur",
    "antartida e islas del atlantico sur",
    "tucumán", "tucuman",
    "ciudad autónoma de buenos aires", "ciudad autonoma de buenos aires",
    "caba", "ciudad de buenos aires",
}


def validar_correo(texto: str) -> bool:
    partes = texto.strip().split("@")
    return len(partes) == 2 and len(partes[0]) > 0 and "." in partes[1] and len(partes[1]) > 2


def validar_telefono(texto: str) -> bool:
    limpio = texto.strip().replace(" ", "").replace("+", "").replace("-", "")
    return limpio.isdigit() and len(limpio) >= 6


def validar_provincia(texto: str) -> bool:
    return texto.strip().lower() in PROVINCIAS_ARGENTINA


def validar_nombre_empresa(texto: str) -> bool:
    limpio = texto.strip()
    if len(limpio) < 2:
        return False
    return not any(ch.isdigit() for ch in limpio)


def validar_dni(texto: str) -> bool:
    limpio = "".join(ch for ch in texto if ch.isdigit())
    return len(limpio) in [7, 8]


def validar_solo_numeros(texto: str) -> bool:
    limpio = "".join(ch for ch in texto if ch.isdigit())
    return len(limpio) > 0


def validar_texto_sin_numeros(texto: str, min_len: int = 2) -> bool:
    limpio = " ".join(texto.strip().split())
    if len(limpio) < min_len:
        return False
    return not any(ch.isdigit() for ch in limpio)


def validar_cuit(texto: str) -> bool:
    limpio = "".join(ch for ch in texto if ch.isdigit())
    if len(limpio) != 11:
        return False
    if not limpio.isdigit():
        return False
    multiplicadores = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(limpio[i]) * multiplicadores[i] for i in range(10))
    resto = suma % 11
    verificador = 0 if resto == 0 else 9 if resto == 1 else 11 - resto
    return verificador == int(limpio[10])


# ============================================================
# NORMALIZACIÓN DE TEXTO
# ============================================================

def normalize_text_for_filter(text: str) -> str:
    lowered = (text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", lowered)
    without_accents = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    compact = " ".join(without_accents.split())
    return compact


def normalize_interest_tag(label: str) -> str:
    base = normalize_text_for_filter(label)
    safe = "".join(ch if ch.isalnum() else "_" for ch in base)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")


def normalize_menu_command(text: str) -> str:
    normalized_text = (text or "").strip()
    normalized_text = re.sub(r"[\s\.:;,\)\]]+$", "", normalized_text)
    return normalized_text


def normalize_legacy_greeting(greeting_text: str) -> str:
    cleaned = (greeting_text or "").replace("\r\n", "\n").strip()
    legacy_prefixes = [
        "CURSALA | Plataforma de formacion tecnica y profesional",
        "Hola Bienvenido/a a Cursala.",
    ]
    for prefix in legacy_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


def validate_bsuid(bsuid: str) -> Optional[str]:
    if not bsuid:
        return None
    bsuid_clean = str(bsuid).strip()
    if "." not in bsuid_clean:
        return None
    parts = bsuid_clean.split(".")
    if len(parts) == 2:
        country_code, identifier = parts
        ent_prefix = ""
    elif len(parts) == 3 and parts[1].upper() == "ENT":
        country_code, ent_prefix, identifier = parts
    else:
        return None
    if not (len(country_code) == 2 and country_code.isalpha()):
        return None
    if not identifier or not all(c.isalnum() for c in identifier) or len(identifier) > 128:
        return None
    if ent_prefix:
        return f"{country_code.upper()}.ENT.{identifier}"
    return f"{country_code.upper()}.{identifier}"


def build_contact_code(number: str, interest_tag: Optional[str] = None) -> str:
    tag = normalize_interest_tag(interest_tag or "contacto").upper() or "CONTACTO"
    digits = normalize_number(number).zfill(16)
    return f"{tag}_{digits}"


# ============================================================
# PROVINCIA POR CÓDIGO DE ÁREA
# ============================================================

AREA_CODE_TO_PROVINCE = {
    "220": "Buenos Aires", "221": "Buenos Aires", "223": "Buenos Aires",
    "230": "Buenos Aires", "236": "Buenos Aires", "237": "Buenos Aires",
    "249": "Buenos Aires", "261": "Mendoza", "264": "San Juan",
    "266": "San Luis", "280": "Chubut", "291": "Buenos Aires",
    "294": "Rio Negro", "297": "Chubut", "299": "Neuquen",
    "341": "Santa Fe", "342": "Santa Fe", "343": "Entre Rios",
    "351": "Cordoba", "362": "Chaco", "370": "Formosa",
    "376": "Misiones", "379": "Corrientes", "381": "Tucuman",
    "385": "Santiago del Estero", "387": "Salta", "388": "Jujuy",
}


def infer_argentina_province_from_phone(number: str) -> Tuple[str, str]:
    digits = normalize_number(number)
    if digits.startswith("54"):
        digits = digits[2:]
    if digits.startswith("9"):
        digits = digits[1:]
    if digits.startswith("0"):
        digits = digits[1:]
    for size in [4, 3, 2]:
        area_code = digits[:size]
        if area_code in AREA_CODE_TO_PROVINCE:
            return AREA_CODE_TO_PROVINCE[area_code], area_code
    return "Desconocida", ""


# ============================================================
# HELPERS DE CONTACTO
# ============================================================

def sanitize_contact_name(raw_name: str) -> str:
    cleaned = " ".join((raw_name or "").strip().split())
    return cleaned


def saludo_por_horario() -> str:
    hora = datetime.now(ZoneInfo("America/Argentina/Mendoza")).hour
    if 5 <= hora < 12:
        return "¡Buen día!"
    elif 12 <= hora < 20:
        return "¡Buenas tardes!"
    else:
        return "¡Buenas noches!"


def format_display_value(value: Any) -> str:
    text = str(value or "").strip()
    return text.lower() if text else "—"


def build_labeled_data_block(items: List[Tuple[str, Any]]) -> str:
    blocks = []
    for label, value in items:
        blocks.append(f"*{label.strip().upper()}*\n{format_display_value(value)}")
    return "\n\n".join(blocks)


def parse_full_name(full_name: str) -> Tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def extract_url_suffix(url: str, prefixes: List[str]) -> Optional[str]:
    clean_url = (url or "").strip()
    for prefix in prefixes:
        if clean_url.startswith(prefix):
            return clean_url[len(prefix):]
    return None


# ============================================================
# CSV HELPERS
# ============================================================

def _normalize_csv_header(header: str) -> str:
    raw = (header or "").strip().lower()
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.replace("-", "_").replace(" ", "_")
    return raw


def _extract_phone_from_row(row: Dict[str, Any]) -> str:
    candidates = ["whatsapp_number", "phone", "telefono", "numero", "celular", "movil", "wa_id"]
    for key in candidates:
        value = row.get(key)
        normalized = normalize_number(value)
        if normalized:
            return normalized
    return ""


def _parse_intereses_csv(value: str) -> List[str]:
    if not value:
        return []
    raw = value.replace(";", ",").replace("|", ",")
    items = [" ".join(part.strip().split()) for part in raw.split(",")]
    return [item for item in items if item]


def parse_csv_contacts_file(file_bytes: bytes) -> List[dict]:
    content = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            content = file_bytes.decode(encoding)
            break
        except Exception:
            continue
    if not content:
        return []
    reader = csv.DictReader(io.StringIO(content))
    contacts = []
    for raw_row in reader:
        normalized_row = {}
        for key, value in (raw_row or {}).items():
            normalized_row[_normalize_csv_header(str(key))] = " ".join(str(value or "").strip().split())
        phone = _extract_phone_from_row(normalized_row)
        nombre = normalized_row.get("nombre") or normalized_row.get("name") or normalized_row.get("full_name")
        etiqueta = (
            normalized_row.get("etiqueta_cliente")
            or normalized_row.get("etiqueta")
            or normalized_row.get("tag")
            or normalized_row.get("label")
        )
        intereses_raw = normalized_row.get("intereses") or normalized_row.get("interes") or normalized_row.get("tags")
        ultimo_evento = normalized_row.get("ultimo_evento") or "importacion_backup_csv"
        contacts.append({
            "whatsapp_number": phone,
            "nombre": nombre or "",
            "etiqueta_cliente": etiqueta or "",
            "intereses": _parse_intereses_csv(intereses_raw or ""),
            "ultimo_evento": ultimo_evento,
        })
    return contacts


def build_upload_progress_message(percent: int, stage: str) -> str:
    safe_percent = max(0, min(100, int(percent)))
    filled = safe_percent // 10
    bar = ("#" * filled) + ("-" * (10 - filled))
    return f"CARGA CSV: {safe_percent}%\n[{bar}]\n{stage}"


def parse_xlsx_contacts_file(file_bytes: bytes) -> List[dict]:
    """Parsea un archivo Excel (.xlsx / .xls) con contactos y retorna List[dict]
    con el mismo formato que parse_csv_contacts_file."""
    try:
        import openpyxl  # type: ignore[import-not-found]
    except ImportError:
        logger.error("openpyxl no está instalado. Instalar con: pip install openpyxl")
        return []

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as e:
        logger.warning("parse_xlsx_contacts_file: no se pudo abrir el archivo: %s", e)
        return []

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Primera fila como encabezados
    raw_headers = [str(h or "").strip() for h in rows[0]]
    headers = [_normalize_csv_header(h) for h in raw_headers]

    contacts = []
    for row in rows[1:]:
        if not any(cell is not None for cell in row):
            continue  # fila vacía

        normalized_row: Dict[str, str] = {}
        for col_idx, header in enumerate(headers):
            cell_val = row[col_idx] if col_idx < len(row) else None
            normalized_row[header] = " ".join(str(cell_val or "").strip().split())

        phone = _extract_phone_from_row(normalized_row)
        nombre = (
            normalized_row.get("nombre")
            or normalized_row.get("name")
            or normalized_row.get("full_name")
        )
        etiqueta = (
            normalized_row.get("etiqueta_cliente")
            or normalized_row.get("etiqueta")
            or normalized_row.get("tag")
            or normalized_row.get("label")
        )
        intereses_raw = (
            normalized_row.get("intereses")
            or normalized_row.get("interes")
            or normalized_row.get("tags")
        )
        ultimo_evento = normalized_row.get("ultimo_evento") or "importacion_backup_xlsx"

        contacts.append({
            "whatsapp_number": phone,
            "nombre": nombre or "",
            "etiqueta_cliente": etiqueta or "",
            "intereses": _parse_intereses_csv(intereses_raw or ""),
            "ultimo_evento": ultimo_evento,
        })

    return contacts


def _normalize_intereses_backup(intereses_raw: Any) -> List[str]:
    if not intereses_raw:
        return []
    if isinstance(intereses_raw, str):
        cleaned = " ".join(intereses_raw.strip().split())
        return [cleaned] if cleaned else []
    if isinstance(intereses_raw, list):
        cleaned_items = []
        for item in intereses_raw:
            item_clean = " ".join(str(item).strip().split())
            if item_clean:
                cleaned_items.append(item_clean)
        return cleaned_items
    return []
