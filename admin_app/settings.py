"""Configuración de la app de administración."""

import json
from pathlib import Path

# Rutas
APP_DIR = Path(__file__).parent
CONFIG_FILE = APP_DIR / ".admin_config.json"
BACKUPS_DIR = APP_DIR / "backups"
APP_NAME = "ADMIN CURSALA BOT"
DEFAULT_SERVER_URL = "https://cursala-bot-517209792054.southamerica-east1.run.app"

# Crear directorios si no existen
BACKUPS_DIR.mkdir(exist_ok=True)

# Configuración por defecto
DEFAULT_CONFIG = {
    "server_url": DEFAULT_SERVER_URL,
    "admin_username": "admin",
    "admin_key": "",
    "theme": "light",
    "window_width": 1200,
    "window_height": 800,
    "auto_save_menu_config": True,
    "auto_backup_enabled": True,
}


def find_logo_path():
    """Busca un logo de la app en rutas conocidas."""
    candidates = [
        APP_DIR / "assets" / "logo.png",
        APP_DIR / "assets" / "logo.jpg",
        APP_DIR / "assets" / "logo.jpeg",
        APP_DIR / "assets" / "logo.webp",
        APP_DIR / "assets" / "logo.ico",
        APP_DIR / "logo.png",
        APP_DIR / "logo.jpg",
        APP_DIR / "logo.ico",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_config():
    """Carga configuración desde archivo JSON."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = {**DEFAULT_CONFIG, **json.load(f)}
                # Mantener backend oficial para evitar desalineación entre app y WhatsApp admin.
                cfg["server_url"] = DEFAULT_SERVER_URL
                return cfg
        except Exception as e:
            print(f"Error cargando config: {e}")
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG


def save_config(config: dict):
    """Guarda configuración a archivo JSON."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error guardando config: {e}")


# Config global
CONFIG = load_config()
