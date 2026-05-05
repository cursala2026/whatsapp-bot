"""Cliente HTTP para comunicarse con la API del bot."""

import requests
import json
from typing import Dict, Any, Tuple
from requests.exceptions import RequestException

from settings import CONFIG


class BotApiClient:
    """Cliente para interactuar con la API del bot."""

    def __init__(self, server_url: str, admin_key: str):
        self.server_url = server_url.rstrip("/")
        self.admin_key = admin_key
        self.headers = {
            "x-admin-key": admin_key,
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: requests.Response) -> Tuple[bool, Any, str]:
        """Procesa respuesta HTTP."""
        try:
            if response.status_code >= 400:
                return False, None, f"Error {response.status_code}: {response.text[:200]}"
            return True, response.json() if response.text else {}, ""
        except json.JSONDecodeError:
            return True, response.text, ""
        except Exception as e:
            return False, None, str(e)

    def get_version(self) -> Tuple[bool, Dict, str]:
        """Obtiene versión del servicio."""
        try:
            url = f"{self.server_url}/version"
            response = requests.get(url, timeout=5)
            return self._handle_response(response)
        except RequestException as e:
            return False, None, f"No se puede conectar: {str(e)}"

    def get_all_contacts(self, limit: int = 200) -> Tuple[bool, list, str]:
        """Obtiene todos los contactos de Firestore."""
        try:
            url = f"{self.server_url}/admin/firestore/users"
            safe_limit = max(1, min(limit, 200))
            params = {"limit": safe_limit}
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            ok, data, err = self._handle_response(response)
            if ok and isinstance(data, dict):
                items = data.get("items")
                if isinstance(items, list):
                    return ok, items, err
                users = data.get("users")
                if isinstance(users, list):
                    return ok, users, err
            return ok, [], err
        except RequestException as e:
            return False, [], f"Error obteniendo contactos: {str(e)}"

    def get_contact(self, phone: str) -> Tuple[bool, Dict, str]:
        """Obtiene un contacto específico por teléfono."""
        try:
            url = f"{self.server_url}/admin/firestore/users/{phone}"
            response = requests.get(url, headers=self.headers, timeout=5)
            return self._handle_response(response)
        except RequestException as e:
            return False, None, f"Error: {str(e)}"

    def import_contacts(self, contacts: list) -> Tuple[bool, Dict, str]:
        """Importa contactos desde JSON."""
        try:
            url = f"{self.server_url}/admin/firestore/contacts/import"
            payload = {"contactos": contacts}
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            return self._handle_response(response)
        except RequestException as e:
            return False, None, f"Error importando: {str(e)}"

    def send_test_message(self, phone: str, message: str) -> Tuple[bool, Dict, str]:
        """Envía mensaje de prueba a un número."""
        try:
            url = f"{self.server_url}/admin/send-test-message"
            payload = {"numero": phone, "mensaje": message}
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            return self._handle_response(response)
        except RequestException as e:
            return False, None, f"Error enviando: {str(e)}"

    def download_contacts_template(self) -> Tuple[bool, bytes, str]:
        """Descarga plantilla de contactos."""
        try:
            url = f"{self.server_url}/admin/download-contacts-template"
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return True, response.content, ""
            return False, None, f"Error {response.status_code}"
        except RequestException as e:
            return False, None, f"Error: {str(e)}"

    def export_all_contacts_xlsx(self) -> Tuple[bool, bytes, str]:
        """Descarga todos los contactos en Excel."""
        try:
            url = f"{self.server_url}/admin/export-all-contacts-xlsx"
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                return True, response.content, ""
            return False, None, f"Error {response.status_code}"
        except RequestException as e:
            return False, None, f"Error: {str(e)}"

    def export_contacts_xlsx(
        self,
        *,
        label_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 5000,
    ) -> Tuple[bool, bytes, str]:
        """Exporta contactos con filtros opcionales."""
        try:
            url = f"{self.server_url}/admin/firestore/contacts/export-xlsx"
            params = {
                "limit": max(1, min(limit, 5000)),
            }
            if label_filter.strip():
                params["label_filter"] = label_filter.strip()
            if date_from.strip():
                params["date_from"] = date_from.strip()
            if date_to.strip():
                params["date_to"] = date_to.strip()

            response = requests.get(url, headers=self.headers, params=params, timeout=90)
            if response.status_code == 200:
                return True, response.content, ""
            return False, None, f"Error {response.status_code}: {response.text[:200]}"
        except RequestException as e:
            return False, None, f"Error: {str(e)}"

    def get_labels(self) -> Tuple[bool, list, str]:
        """Obtiene etiquetas disponibles de contactos."""
        try:
            url = f"{self.server_url}/admin/firestore/labels"
            response = requests.get(url, headers=self.headers, timeout=15)
            ok, data, err = self._handle_response(response)
            if ok and isinstance(data, dict):
                labels = data.get("labels", [])
                if isinstance(labels, list):
                    return True, labels, ""
            return False, [], err or "No se pudieron obtener etiquetas"
        except RequestException as e:
            return False, [], f"Error: {str(e)}"

    def get_menu_config(self) -> Tuple[bool, Dict, str]:
        """Obtiene menu_config actual."""
        try:
            url = f"{self.server_url}/admin/menu-config"
            response = requests.get(url, headers=self.headers, timeout=15)
            ok, data, err = self._handle_response(response)
            if ok and isinstance(data, dict):
                config = data.get("config")
                if isinstance(config, dict):
                    return True, config, ""
            return False, {}, err or "Respuesta inválida"
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"

    def save_menu_config(self, config: dict) -> Tuple[bool, Dict, str]:
        """Guarda menu_config completo."""
        try:
            url = f"{self.server_url}/admin/menu-config"
            response = requests.put(url, headers=self.headers, json={"config": config}, timeout=20)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"

    def create_backup(self) -> Tuple[bool, Dict, str]:
        """Crea backup remoto de menu_config."""
        try:
            url = f"{self.server_url}/admin/menu-config/backup"
            response = requests.post(url, headers=self.headers, json={}, timeout=15)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"

    def list_backups(self) -> Tuple[bool, list, str]:
        """Lista backups remotos de menu_config."""
        try:
            url = f"{self.server_url}/admin/menu-config/backups"
            response = requests.get(url, headers=self.headers, timeout=15)
            ok, data, err = self._handle_response(response)
            if ok and isinstance(data, dict):
                backups = data.get("backups", [])
                if isinstance(backups, list):
                    return True, backups, ""
            return False, [], err or "Respuesta inválida"
        except RequestException as e:
            return False, [], f"Error: {str(e)}"

    def restore_backup(self, filename: str) -> Tuple[bool, Dict, str]:
        """Restaura backup remoto de menu_config."""
        try:
            url = f"{self.server_url}/admin/menu-config/backups/restore"
            response = requests.post(url, headers=self.headers, json={"filename": filename}, timeout=20)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"

    def send_broadcast(
        self,
        *,
        filter_mode: str,
        msg_type: str,
        message: str = "",
        label: str = "",
        template_name: str = "mensaje_inicial",
        template_lang: str = "es",
    ) -> Tuple[bool, Dict, str]:
        """Dispara envío masivo como modo admin WhatsApp."""
        try:
            url = f"{self.server_url}/admin/broadcast/send"
            payload = {
                "filter_mode": filter_mode,
                "label": label,
                "msg_type": msg_type,
                "message": message,
                "template_name": template_name,
                "template_lang": template_lang,
            }
            response = requests.post(url, headers=self.headers, json=payload, timeout=120)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"


    def update_contact(self, phone: str, data: dict) -> Tuple[bool, Dict, str]:
        """Actualiza datos de un contacto existente."""
        try:
            url = f"{self.server_url}/admin/firestore/users/{phone}"
            response = requests.put(url, headers=self.headers, json=data, timeout=10)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"

    def delete_contact(self, phone: str) -> Tuple[bool, Dict, str]:
        """Elimina un contacto por teléfono."""
        try:
            url = f"{self.server_url}/admin/firestore/users/{phone}"
            response = requests.delete(url, headers=self.headers, timeout=10)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"

    def get_backup_content(self, filename: str) -> Tuple[bool, Dict, str]:
        """Obtiene el contenido de un backup específico."""
        try:
            url = f"{self.server_url}/admin/menu-config/backups/{filename}"
            response = requests.get(url, headers=self.headers, timeout=15)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"

    def delete_backup(self, filename: str) -> Tuple[bool, Dict, str]:
        """Elimina un backup específico."""
        try:
            url = f"{self.server_url}/admin/menu-config/backups/{filename}"
            response = requests.delete(url, headers=self.headers, timeout=10)
            return self._handle_response(response)
        except RequestException as e:
            return False, {}, f"Error: {str(e)}"


def get_client() -> BotApiClient:

    """Factory para obtener cliente configurado."""
    return BotApiClient(CONFIG["server_url"], CONFIG.get("admin_key", ""))
