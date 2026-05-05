"""Aplicación de administración del bot - Ventana principal."""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QDialog, QMessageBox,
    QFrame, QStatusBar
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap

from settings import APP_NAME, CONFIG, find_logo_path, save_config
from api_client import BotApiClient, get_client
from tabs.menu_editor import MenuEditorTab
from tabs.contacts_manager import ContactsManagerTab
from tabs.vendors_manager import VendorsManagerTab
from tabs.test_messages import TestMessagesTab
from tabs.settings_panel import SettingsPanelTab
from tabs.backups_manager import BackupsManagerTab


class LoginDialog(QDialog):
    """Pantalla de acceso con bienvenida y autenticación admin."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setModal(True)
        self.setFixedSize(520, 560)
        self._auth_ok = False

        layout = QVBoxLayout()
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        self.setStyleSheet("""
            QDialog {
                background-color: #f6f0e8;
            }
            QLabel#heroCard {
                background-color: #173f35;
                color: white;
                border-radius: 22px;
                padding: 26px;
            }
            QLabel#logoFallback {
                background-color: #e6a64b;
                color: #173f35;
                border-radius: 48px;
                font-size: 28px;
                font-weight: 700;
            }
            QLineEdit {
                background-color: white;
                border: 1px solid #d8c9b4;
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 14px;
            }
            QPushButton {
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 14px;
            }
            QPushButton#primaryButton {
                background-color: #173f35;
                color: white;
            }
            QPushButton#secondaryButton {
                background-color: #efe4d6;
                color: #173f35;
            }
        """)

        hero_card = QLabel()
        hero_card.setObjectName("heroCard")
        hero_card.setText(
            f"<div style='font-size:30px; font-weight:700;'>{APP_NAME}</div>"
            "<div style='margin-top:8px; font-size:15px;'>"
            "Bienvenido al panel de administración de Cursala.</div>"
            "<div style='margin-top:10px; font-size:13px; color:#d9e8e3;'>"
            "Ingresá tu contraseña admin para continuar.</div>"
        )
        hero_card.setWordWrap(True)
        layout.addWidget(hero_card)

        logo_path = find_logo_path()
        if logo_path is not None:
            logo_label = QLabel()
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap(str(logo_path))
            logo_label.setPixmap(
                pixmap.scaled(
                    180,
                    180,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(logo_label)
        else:
            logo_label = QLabel("CB")
            logo_label.setObjectName("logoFallback")
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setFixedSize(96, 96)

            logo_row = QHBoxLayout()
            logo_row.addStretch()
            logo_row.addWidget(logo_label)
            logo_row.addStretch()
            layout.addLayout(logo_row)

        layout.addWidget(QLabel("Contraseña admin"))
        self.password_input = QLineEdit()
        self.password_input.setText(CONFIG.get("admin_key", ""))
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Ingresá tu clave de administrador")
        self.password_input.returnPressed.connect(self.login)
        layout.addWidget(self.password_input)

        helper = QLabel(
            "La app se conecta automáticamente al servidor oficial de Cursala."
        )
        helper.setWordWrap(True)
        helper.setStyleSheet("color: #5f635f; font-size: 12px;")
        layout.addWidget(helper)

        button_layout = QHBoxLayout()
        save_btn = QPushButton("Ingresar")
        save_btn.setObjectName("primaryButton")
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("secondaryButton")

        save_btn.clicked.connect(self.login)
        cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def login(self):
        """Valida credenciales y guarda la sesión local."""
        self._auth_ok = False
        password = self.password_input.text().strip()

        if not password:
            QMessageBox.warning(self, "Acceso", "Completá la contraseña admin.")
            return

        client = BotApiClient(CONFIG["server_url"], password)
        ok, data, err = client.get_version()

        if not ok:
            QMessageBox.critical(
                self,
                "Acceso",
                f"No se pudo conectar al servidor de Cursala:\n{err}",
            )
            return

        ok_admin, _contacts, admin_err = client.get_all_contacts(limit=1)
        if not ok_admin:
            QMessageBox.critical(
                self,
                "Acceso",
                f"Credenciales inválidas o sin permisos admin:\n{admin_err}",
            )
            return

        CONFIG["admin_username"] = "admin"
        CONFIG["admin_key"] = password
        save_config(CONFIG)
        self._auth_ok = True
        QMessageBox.information(
            self,
            "Éxito",
            f"Bienvenido a {APP_NAME}\nVersión: {data.get('app_version', 'desconocida')}",
        )
        self.accept()


class AdminAppWindow(QMainWindow):
    """Ventana principal de la app de administración."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setGeometry(50, 50, CONFIG["window_width"], CONFIG["window_height"])
        
        # Estilo
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f7f2ea;
            }
            QTabBar::tab {
                padding: 8px 20px;
            }
            QTabBar::tab:selected {
                background-color: #173f35;
                color: white;
            }
        """)
        
        # Widget central
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # Header
        header_layout = QHBoxLayout()
        title = QLabel(APP_NAME)
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        
        settings_btn = QPushButton("🔐 Cambiar acceso")
        settings_btn.clicked.connect(self.open_login)
        settings_btn.setMaximumWidth(160)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(settings_btn)
        
        main_layout.addLayout(header_layout)
        
        # Separador
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(separator)
        
        # Tabs
        self.tabs = QTabWidget()
        
        self.menu_tab = MenuEditorTab()
        self.contacts_tab = ContactsManagerTab()
        self.vendors_tab = VendorsManagerTab()
        self.test_tab = TestMessagesTab()
        self.backups_tab = BackupsManagerTab()
        self.settings_tab = SettingsPanelTab()
        
        self.tabs.addTab(self.menu_tab, "📋 Menús")
        self.tabs.addTab(self.contacts_tab, "👥 Contactos")
        self.tabs.addTab(self.vendors_tab, "🏢 Vendedores")
        self.tabs.addTab(self.test_tab, "✉️ Mensajes de Prueba")
        self.tabs.addTab(self.backups_tab, "💾 Backups")
        self.tabs.addTab(self.settings_tab, "⚙️ Configuración")
        
        main_layout.addWidget(self.tabs)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Listo")
        
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # Verificar conexión al iniciar
        self.verify_connection()

    def verify_connection(self):
        """Verifica conexión al servidor."""
        if not CONFIG.get("admin_key"):
            self.open_login()
            return
        
        client = get_client()
        ok, _contacts, err = client.get_all_contacts(limit=1)
        if not ok:
            QMessageBox.warning(
                self,
                "Advertencia",
                f"No se pudo validar el acceso admin:\n{err}\n\nVolvé a ingresar tus credenciales."
            )
            self.open_login()
            return

        self.contacts_tab.ensure_loaded()

    def open_login(self):
        """Abre diálogo de login."""
        dialog = LoginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.statusBar.showMessage(f"Sesión iniciada como {CONFIG.get('admin_username', 'admin')}")
            self.contacts_tab.ensure_loaded()

    def closeEvent(self, event):
        """Al cerrar, guarda tamaño de ventana."""
        CONFIG["window_width"] = self.width()
        CONFIG["window_height"] = self.height()
        save_config(CONFIG)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = AdminAppWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
