"""Tab para gestionar backups."""

import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QLabel, QMessageBox, QHeaderView,
    QTextEdit, QSplitter,
)
from PyQt6.QtCore import Qt

from api_client import get_client


class BackupsManagerTab(QWidget):
    """Pestaña para gestionar backups."""

    def __init__(self):
        super().__init__()
        self._backups: list = []    # lista de nombres de backups
        self._init_ui()
        self.load_backups()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("💾 Gestión de Backups"))

        # ── Tabla + preview lado a lado ───────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Tabla
        table_widget = QWidget()
        tw_layout = QVBoxLayout(table_widget)
        tw_layout.addWidget(QLabel("Backups disponibles (click para previsualizar):"))

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Nombre del backup", "Fecha"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.clicked.connect(self._on_backup_selected)
        tw_layout.addWidget(self.table)
        splitter.addWidget(table_widget)

        # Preview
        preview_widget = QWidget()
        pw_layout = QVBoxLayout(preview_widget)
        pw_layout.addWidget(QLabel("Contenido del backup seleccionado:"))
        self.preview_box = QTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setPlaceholderText(
            "Seleccioná un backup de la lista para ver su contenido…"
        )
        pw_layout.addWidget(self.preview_box)
        splitter.addWidget(preview_widget)

        splitter.setSizes([350, 500])
        layout.addWidget(splitter)

        # ── Botones ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        btn_create = QPushButton("➕ Crear Backup Ahora")
        btn_create.setStyleSheet("background-color: #1976D2; color: white;")
        btn_create.clicked.connect(self._create_backup)

        btn_restore = QPushButton("↩️ Restaurar Seleccionado")
        btn_restore.setStyleSheet("background-color: #388E3C; color: white;")
        btn_restore.clicked.connect(self._restore_backup)

        btn_delete = QPushButton("🗑️ Eliminar Seleccionado")
        btn_delete.setStyleSheet("background-color: #c62828; color: white;")
        btn_delete.clicked.connect(self._delete_backup)

        btn_reload = QPushButton("🔄 Recargar")
        btn_reload.clicked.connect(self.load_backups)

        for b in [btn_create, btn_restore, btn_delete, btn_reload]:
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Snapshot estado bot ───────────────────────────────────────────────
        layout.addWidget(QLabel("Estado actual de la config en el bot:"))
        self.snapshot_box = QTextEdit()
        self.snapshot_box.setReadOnly(True)
        self.snapshot_box.setMaximumHeight(100)
        self.snapshot_box.setPlainText("Cargando…")
        layout.addWidget(self.snapshot_box)

        self.setLayout(layout)

    # ── Carga de datos ────────────────────────────────────────────────────────

    def load_backups(self):
        client = get_client()
        ok, data, err = client.list_backups()
        if not ok:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar backups:\n{err}")
            self._fill_table([])
            return

        self._backups = [str(item) for item in data]
        self._fill_table(self._backups)
        self._refresh_snapshot(len(self._backups))
        self.preview_box.clear()
        self.preview_box.setPlaceholderText(
            "Seleccioná un backup de la lista para ver su contenido…"
        )

    def _fill_table(self, backups: list):
        self.table.setRowCount(len(backups))
        for row, name in enumerate(backups):
            date_str = name.replace(".json", "").replace("_", " ")
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(date_str))

    def _refresh_snapshot(self, backup_count: int):
        client = get_client()
        ok, config, _ = client.get_menu_config()
        lines = [f"Backups disponibles: {backup_count}", ""]
        if ok and isinstance(config, dict):
            rev = config.get("revision", {})
            lines.append(f"Config versión: {rev.get('version', '—')}")
            lines.append(f"Último cambio: {rev.get('fecha', '—')} {rev.get('hora', '—')}")
            lines.append(f"Cursos: {len(config.get('cursos', {}))}")
            lines.append(f"Vendedores: {len(config.get('vendedores', {}))}")
        else:
            lines.append("No se pudo obtener info del bot.")
        self.snapshot_box.setPlainText("\n".join(lines))

    # ── Preview de contenido ──────────────────────────────────────────────────

    def _on_backup_selected(self, index):
        row = index.row()
        if row < 0 or row >= len(self._backups):
            return
        filename = self._backups[row]
        self.preview_box.setPlainText("Cargando contenido…")
        client = get_client()
        ok, data, err = client.get_backup_content(filename)
        if not ok:
            self.preview_box.setPlainText(f"⚠️ No se pudo obtener contenido:\n{err}")
            return
        # data puede ser dict (JSON del backup) o string
        if isinstance(data, dict):
            config = data.get("config", data)
            text = json.dumps(config, ensure_ascii=False, indent=2)
        elif isinstance(data, str):
            try:
                parsed = json.loads(data)
                text = json.dumps(parsed, ensure_ascii=False, indent=2)
            except Exception:
                text = data
        else:
            text = str(data)
        self.preview_box.setPlainText(text)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _create_backup(self):
        client = get_client()
        ok, data, err = client.create_backup()
        if ok:
            filename = (
                data.get("filename", "(sin nombre)")
                if isinstance(data, dict) else "(sin nombre)"
            )
            QMessageBox.information(self, "Éxito", f"✅ Backup creado:\n{filename}")
            self.load_backups()
        else:
            QMessageBox.critical(self, "Error", f"Error creando backup:\n{err}")

    def _restore_backup(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._backups):
            QMessageBox.warning(self, "Aviso", "Seleccioná un backup primero.")
            return
        filename = self._backups[row]
        reply = QMessageBox.question(
            self, "Confirmar restauración",
            f"¿Restaurar '{filename}'?\n\nEsto reemplazará la configuración actual del bot.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_client()
        ok, _, err = client.restore_backup(filename)
        if ok:
            QMessageBox.information(self, "Éxito", "✅ Backup restaurado correctamente.")
            self.load_backups()
        else:
            QMessageBox.critical(self, "Error", f"No se pudo restaurar:\n{err}")

    def _delete_backup(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._backups):
            QMessageBox.warning(self, "Aviso", "Seleccioná un backup primero.")
            return
        filename = self._backups[row]
        reply = QMessageBox.question(
            self, "Confirmar eliminación",
            f"¿Eliminar '{filename}'?\nEsta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_client()
        ok, _, err = client.delete_backup(filename)
        if ok:
            QMessageBox.information(self, "Éxito", f"✅ Backup '{filename}' eliminado.")
            self.preview_box.clear()
            self.load_backups()
        else:
            QMessageBox.critical(self, "Error", f"No se pudo eliminar:\n{err}")
