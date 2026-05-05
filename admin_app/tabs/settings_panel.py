"""Tab para configuración de aplicación."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QCheckBox,
    QPushButton, QLabel, QMessageBox, QTextEdit
)

from settings import APP_NAME, CONFIG, save_config
from api_client import get_client


class SettingsPanelTab(QWidget):
    """Pestaña para configuración general de la app."""

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        """Inicializa la UI."""
        layout = QVBoxLayout()
        
        # Título
        title = QLabel("Configuración de la Aplicación")
        layout.addWidget(title)
        
        # Formulario
        form_layout = QFormLayout()

        server_label = QLabel("Conexión automática al servidor oficial de Cursala")
        server_label.setWordWrap(True)
        form_layout.addRow("Servidor:", server_label)
        
        # Admin Key
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("Contraseña admin:", self.key_input)
        
        # Auto-save menú config
        self.auto_save_checkbox = QCheckBox("Auto-guardar cambios de menú")
        form_layout.addRow(self.auto_save_checkbox)
        
        # Auto-backup
        self.auto_backup_checkbox = QCheckBox("Auto-crear backup al guardar")
        form_layout.addRow(self.auto_backup_checkbox)
        
        # Tema
        self.theme_input = QLineEdit()
        self.theme_input.setPlaceholderText("light o dark")
        form_layout.addRow("Tema (light/dark):", self.theme_input)

        self.email_enabled = QCheckBox("Notificaciones por email activas")
        form_layout.addRow(self.email_enabled)

        self.email_dest_input = QLineEdit()
        form_layout.addRow("Email destinatario:", self.email_dest_input)

        self.email_subject_input = QLineEdit()
        form_layout.addRow("Asunto email:", self.email_subject_input)

        self.email_intro_input = QTextEdit()
        self.email_intro_input.setPlaceholderText("Texto de introducción del email")
        form_layout.addRow("Intro email:", self.email_intro_input)

        self.prompt_rules_input = QTextEdit()
        self.prompt_rules_input.setPlaceholderText("Reglas Gemini (una por línea)")
        form_layout.addRow("Reglas Gemini:", self.prompt_rules_input)
        
        layout.addLayout(form_layout)
        
        # Botones
        button_layout = QVBoxLayout()
        
        save_btn = QPushButton("💾 Guardar Configuración")
        save_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_btn)
        
        reset_btn = QPushButton("↺ Restablecer a Valores por Defecto")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        layout.addLayout(button_layout)

        layout.addWidget(QLabel("Estado actual cargado en el bot (email + reglas Gemini):"))
        self.snapshot_box = QTextEdit()
        self.snapshot_box.setReadOnly(True)
        self.snapshot_box.setMinimumHeight(110)
        self.snapshot_box.setPlainText("Sin datos. Se carga al abrir la pestaña.")
        layout.addWidget(self.snapshot_box)

        self.setLayout(layout)

    def load_settings(self):
        """Carga configuración actual."""
        self.key_input.setText(CONFIG.get("admin_key", ""))
        self.auto_save_checkbox.setChecked(CONFIG.get("auto_save_menu_config", True))
        self.auto_backup_checkbox.setChecked(CONFIG.get("auto_backup_enabled", True))
        self.theme_input.setText(CONFIG.get("theme", "light"))

        client = get_client()
        ok, menu_config, _err = client.get_menu_config()
        if ok and isinstance(menu_config, dict):
            email_cfg = menu_config.get("email_notificacion_admin", {})
            self.email_enabled.setChecked(bool(email_cfg.get("activo", True)))
            self.email_dest_input.setText(str(email_cfg.get("destinatario", "")))
            self.email_subject_input.setText(str(email_cfg.get("asunto", "")))
            self.email_intro_input.setPlainText(str(email_cfg.get("cuerpo_intro", "")))

            rules = menu_config.get("gemini_prompt_rules", [])
            if isinstance(rules, list):
                self.prompt_rules_input.setPlainText("\n".join([str(r) for r in rules]))
            self._refresh_snapshot(menu_config)

    def _refresh_snapshot(self, menu_config: dict):
        email_cfg = menu_config.get("email_notificacion_admin", {})
        rules = menu_config.get("gemini_prompt_rules", [])
        rev = menu_config.get("revision", {})
        lines = [
            "Config cargada desde el bot:",
            "",
            f"  Email activo: {'Si' if email_cfg.get('activo', True) else 'No'}",
            f"  Destinatario: {email_cfg.get('destinatario', '-')}",
            f"  Asunto: {email_cfg.get('asunto', '-')}",
            f"  Reglas Gemini activas: {len(rules) if isinstance(rules, list) else 0}",
            f"  Version config: {rev.get('version', '-')}",
            f"  Ultimo cambio: {rev.get('fecha', '-')} {rev.get('hora', '-')}",
        ]
        self.snapshot_box.setPlainText("\n".join(lines))

    def save_settings(self):
        """Guarda configuración."""
        try:
            CONFIG.update({
                "admin_username": "admin",
                "admin_key": self.key_input.text().strip(),
                "auto_save_menu_config": self.auto_save_checkbox.isChecked(),
                "auto_backup_enabled": self.auto_backup_checkbox.isChecked(),
                "theme": self.theme_input.text().strip() or "light",
            })
            save_config(CONFIG)

            client = get_client()
            ok, menu_config, err = client.get_menu_config()
            if not ok:
                QMessageBox.critical(self, "Error", f"No se pudo cargar menu_config:\n{err}")
                return

            rules = [" ".join(x.split()).strip() for x in self.prompt_rules_input.toPlainText().splitlines()]
            rules = [x for x in rules if x]

            email_cfg = menu_config.get("email_notificacion_admin", {})
            email_cfg["activo"] = self.email_enabled.isChecked()
            email_cfg["destinatario"] = self.email_dest_input.text().strip()
            email_cfg["asunto"] = self.email_subject_input.text().strip()
            email_cfg["cuerpo_intro"] = self.email_intro_input.toPlainText().strip()

            menu_config["email_notificacion_admin"] = email_cfg
            menu_config["gemini_prompt_rules"] = rules

            ok, _save_data, save_err = client.save_menu_config(menu_config)
            if not ok:
                QMessageBox.critical(self, "Error", f"No se pudo guardar configuración admin:\n{save_err}")
                return

            self._refresh_snapshot(menu_config)
            QMessageBox.information(self, "Éxito", f"Configuración de {APP_NAME} guardada")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error guardando: {str(e)}")

    def reset_to_defaults(self):
        """Restablece configuración a valores por defecto."""
        reply = QMessageBox.question(
            self, "Confirmar",
            "¿Restablecer a valores por defecto?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from settings import DEFAULT_CONFIG
            CONFIG.clear()
            CONFIG.update(DEFAULT_CONFIG)
            save_config(CONFIG)
            self.load_settings()
            QMessageBox.information(self, "Éxito", "Configuración restablecida")
