"""Tab para enviar mensajes de prueba."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QTextEdit, QLabel, QMessageBox, QComboBox
)
from PyQt6.QtCore import QThread, pyqtSignal

from api_client import get_client


class BotInfoThread(QThread):
    """Thread para cargar info del bot sin bloquear UI."""

    finished = pyqtSignal(dict)

    def run(self):
        client = get_client()
        info = {}
        ok_v, version_data, _ = client.get_version()
        if ok_v and isinstance(version_data, dict):
            info["version"] = version_data.get("version", "-")
            info["app"] = version_data.get("app", "-")
        ok_c, config, _ = client.get_menu_config()
        if ok_c and isinstance(config, dict):
            info["cursos"] = len(config.get("cursos", {}))
            info["vendedores"] = len(config.get("vendedores", {}))
            rev = config.get("revision", {})
            info["config_version"] = rev.get("version", "-")
        ok_l, labels, _ = client.get_labels()
        if ok_l and isinstance(labels, list):
            info["labels"] = labels
        self.finished.emit(info)


class MessageSenderThread(QThread):
    """Thread para enviar mensajes sin bloquear UI."""
    
    success = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, phone: str, message: str):
        super().__init__()
        self.phone = phone
        self.message = message

    def run(self):
        client = get_client()
        ok, data, err = client.send_test_message(self.phone, self.message)
        
        if ok:
            self.success.emit(f"Mensaje enviado a {self.phone}")
        else:
            self.error.emit(err)


class TestMessagesTab(QWidget):
    """Pestaña para enviar mensajes de prueba."""

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_bot_info()

    def load_bot_info(self):
        self._info_thread = BotInfoThread()
        self._info_thread.finished.connect(self._on_bot_info_loaded)
        self._info_thread.start()

    def _on_bot_info_loaded(self, info: dict):
        lines = [
            "Estado del bot en produccion:",
            "",
            f"  Version app: {info.get('app', '-')}",
            f"  Version config: {info.get('config_version', '-')}",
            f"  Cursos cargados: {info.get('cursos', '-')}",
            f"  Vendedores cargados: {info.get('vendedores', '-')}",
        ]
        labels = info.get("labels", [])
        if labels:
            lines.append("")
            lines.append(f"  Etiquetas disponibles para broadcast ({len(labels)}):")
            for lbl in sorted(labels):
                lines.append(f"    - {lbl}")
        else:
            lines.append("  Sin etiquetas registradas.")
        self.snapshot_box.setPlainText("\n".join(lines))

    def init_ui(self):
        """Inicializa la UI."""
        layout = QVBoxLayout()
        
        # Título
        title = QLabel("Enviar Mensajes de Prueba")
        layout.addWidget(title)
        
        # Destino
        layout.addWidget(QLabel("Número de teléfono:"))
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Ej: 5492615031839")
        layout.addWidget(self.phone_input)
        
        # Mensaje
        layout.addWidget(QLabel("Mensaje:"))
        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("Escribe el mensaje de prueba...")
        layout.addWidget(self.message_input)
        
        # Botones predefinidos
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Presets:"))
        
        hello_btn = QPushButton("Hola")
        hello_btn.clicked.connect(lambda: self.message_input.setPlainText("Hola"))
        preset_layout.addWidget(hello_btn)
        
        test_btn = QPushButton("Mensaje de prueba")
        test_btn.clicked.connect(lambda: self.message_input.setPlainText("Este es un mensaje de prueba del bot."))
        preset_layout.addWidget(test_btn)
        
        preset_layout.addStretch()
        layout.addLayout(preset_layout)
        
        # Botones de acción
        action_layout = QHBoxLayout()
        
        send_btn = QPushButton("✉️ Enviar")
        send_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        send_btn.clicked.connect(self.send_message)
        
        clear_btn = QPushButton("Limpiar")
        clear_btn.clicked.connect(self.clear_fields)
        
        action_layout.addWidget(send_btn)
        action_layout.addWidget(clear_btn)
        action_layout.addStretch()
        
        layout.addLayout(action_layout)

        layout.addWidget(QLabel(""))
        layout.addWidget(QLabel("Mensajería masiva (modo admin WhatsApp)"))

        broadcast_filter_row = QHBoxLayout()
        broadcast_filter_row.addWidget(QLabel("Filtro:"))
        self.broadcast_filter = QComboBox()
        self.broadcast_filter.addItems(["all", "label"])
        self.broadcast_filter.currentTextChanged.connect(self._on_filter_change)
        broadcast_filter_row.addWidget(self.broadcast_filter)

        self.broadcast_label_input = QLineEdit()
        self.broadcast_label_input.setPlaceholderText("Etiqueta (si filtro=label)")
        self.broadcast_label_input.setVisible(False)
        broadcast_filter_row.addWidget(self.broadcast_label_input)
        layout.addLayout(broadcast_filter_row)

        broadcast_type_row = QHBoxLayout()
        broadcast_type_row.addWidget(QLabel("Tipo:"))
        self.broadcast_type = QComboBox()
        self.broadcast_type.addItems(["text", "template"])
        self.broadcast_type.currentTextChanged.connect(self._on_type_change)
        broadcast_type_row.addWidget(self.broadcast_type)
        layout.addLayout(broadcast_type_row)

        self.template_name_input = QLineEdit()
        self.template_name_input.setPlaceholderText("Nombre de template (ej: mensaje_inicial)")
        self.template_name_input.setVisible(False)
        layout.addWidget(self.template_name_input)

        broadcast_btn = QPushButton("📣 Ejecutar envío masivo")
        broadcast_btn.clicked.connect(self.send_broadcast)
        layout.addWidget(broadcast_btn)

        layout.addWidget(QLabel("Estado actual del bot en producción:"))
        self.snapshot_box = QTextEdit()
        self.snapshot_box.setReadOnly(True)
        self.snapshot_box.setMinimumHeight(140)
        self.snapshot_box.setPlainText("Cargando info del bot...")
        layout.addWidget(self.snapshot_box)

        self.setLayout(layout)

    def send_message(self):
        """Envía mensaje de prueba."""
        phone = self.phone_input.text().strip()
        message = self.message_input.toPlainText().strip()
        
        if not phone:
            QMessageBox.warning(self, "Error", "Ingresa un número de teléfono")
            return
        
        if not message:
            QMessageBox.warning(self, "Error", "Escribe un mensaje")
            return
        
        # Enviar en thread separado
        self.sender = MessageSenderThread(phone, message)
        self.sender.success.connect(self.on_success)
        self.sender.error.connect(self.on_error)
        self.sender.start()

    def on_success(self, message: str):
        """Muestra éxito."""
        QMessageBox.information(self, "Éxito", message)

    def on_error(self, error: str):
        """Muestra error."""
        QMessageBox.critical(self, "Error", f"Error:\n{error}")

    def clear_fields(self):
        """Limpia los campos."""
        self.phone_input.clear()
        self.message_input.clear()

    def _on_filter_change(self, value: str):
        self.broadcast_label_input.setVisible(value == "label")

    def _on_type_change(self, value: str):
        self.template_name_input.setVisible(value == "template")

    def send_broadcast(self):
        """Ejecuta envío masivo como admin."""
        filter_mode = self.broadcast_filter.currentText().strip()
        label = self.broadcast_label_input.text().strip()
        msg_type = self.broadcast_type.currentText().strip()
        message = self.message_input.toPlainText().strip()
        template_name = self.template_name_input.text().strip() or "mensaje_inicial"

        if filter_mode == "label" and not label:
            QMessageBox.warning(self, "Error", "Ingresá una etiqueta para filtro por label")
            return
        if msg_type == "text" and not message:
            QMessageBox.warning(self, "Error", "Ingresá un mensaje para el envío masivo")
            return

        reply = QMessageBox.question(
            self,
            "Confirmar",
            "¿Ejecutar envío masivo? Esta acción enviará mensajes reales.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        client = get_client()
        ok, data, err = client.send_broadcast(
            filter_mode=filter_mode,
            msg_type=msg_type,
            message=message,
            label=label,
            template_name=template_name,
            template_lang="es",
        )
        if not ok:
            QMessageBox.critical(self, "Error", f"Broadcast falló:\n{err}")
            return

        enviados = data.get("enviados", 0) if isinstance(data, dict) else 0
        fallidos = data.get("fallidos", 0) if isinstance(data, dict) else 0
        QMessageBox.information(self, "Resultado", f"Broadcast completado\nEnviados: {enviados}\nFallidos: {fallidos}")
