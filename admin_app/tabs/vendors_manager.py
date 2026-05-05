"""Tab para gestionar vendedores."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QLabel, QDialog, QFormLayout, QLineEdit,
    QMessageBox, QHeaderView, QTextEdit, QGroupBox, QCheckBox,
    QAbstractItemView, QScrollArea,
)
from PyQt6.QtCore import Qt

from api_client import get_client


# ─── Diálogo ──────────────────────────────────────────────────────────────────

class VendorDialog(QDialog):
    """Diálogo para agregar/editar vendedor con asignación de cursos."""

    def __init__(self, vendor: dict = None, cursos: dict = None, parent=None):
        super().__init__(parent)
        self.vendor = vendor or {}
        self.cursos = cursos or {}
        self.course_checkboxes: dict = {}
        self.setWindowTitle("Nuevo Vendedor" if not vendor else "Editar Vendedor")
        self.setMinimumWidth(460)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        # ── Campos base ───────────────────────────────────────────────────────
        form = QFormLayout()

        self.nombre_input = QLineEdit(self.vendor.get("nombre", ""))
        form.addRow("Nombre *:", self.nombre_input)

        self.apellido_input = QLineEdit(self.vendor.get("apellido", ""))
        form.addRow("Apellido:", self.apellido_input)

        self.telefono_input = QLineEdit(self.vendor.get("telefono", ""))
        form.addRow("Teléfono:", self.telefono_input)

        self.correo_input = QLineEdit(self.vendor.get("correo", ""))
        form.addRow("Correo:", self.correo_input)

        layout.addLayout(form)

        # ── Cursos asignables ─────────────────────────────────────────────────
        if self.cursos:
            grp = QGroupBox("📚 Cursos asignados a este vendedor")
            grp_layout = QVBoxLayout()

            vendor_id = str(self.vendor.get("id", ""))
            assigned = set()
            if vendor_id:
                for cid, curso in self.cursos.items():
                    vids = [str(x) for x in (curso.get("vendedor_ids") or []) if str(x)]
                    single = str(curso.get("vendedor_id", "")).strip()
                    if single and single not in vids:
                        vids.append(single)
                    if vendor_id in vids:
                        assigned.add(str(cid))

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(200)
            inner = QWidget()
            inner_layout = QVBoxLayout(inner)
            inner_layout.setSpacing(2)

            for cid in sorted(self.cursos.keys(),
                               key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
                curso = self.cursos[cid]
                nombre_curso = str(curso.get("nombre", f"Curso {cid}"))
                chk = QCheckBox(f"[{cid}]  {nombre_curso}")
                chk.setChecked(str(cid) in assigned)
                self.course_checkboxes[str(cid)] = chk
                inner_layout.addWidget(chk)

            inner_layout.addStretch()
            scroll.setWidget(inner)
            grp_layout.addWidget(scroll)
            grp.setLayout(grp_layout)
            layout.addWidget(grp)

        # ── Botones ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾 Guardar")
        save_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 6px 18px;")
        cancel_btn = QPushButton("Cancelar")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def get_vendor(self) -> dict:
        return {
            "nombre": self.nombre_input.text().strip(),
            "apellido": self.apellido_input.text().strip(),
            "telefono": self.telefono_input.text().strip(),
            "correo": self.correo_input.text().strip(),
        }

    def get_assigned_course_ids(self) -> list:
        return [cid for cid, chk in self.course_checkboxes.items() if chk.isChecked()]


# ─── Tab principal ─────────────────────────────────────────────────────────────

class VendorsManagerTab(QWidget):
    """Pestaña para gestionar vendedores."""

    def __init__(self):
        super().__init__()
        self.vendors: list = []
        self.menu_config: dict = {}
        self._init_ui()
        self.load_vendors()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("👤 Gestión de Vendedores"))

        # ── Tabla ─────────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Nombre completo", "Teléfono", "Correo", "Cursos asignados"]
        )
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 44)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(lambda idx: self._edit_vendor(row=idx.row()))
        layout.addWidget(self.table)

        # ── Botones ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        btn_add = QPushButton("➕ Agregar Vendedor")
        btn_add.setStyleSheet("background-color: #4CAF50; color: white;")
        btn_add.clicked.connect(self._add_vendor)

        btn_edit = QPushButton("✏️ Editar")
        btn_edit.clicked.connect(self._edit_vendor)

        btn_del = QPushButton("🗑️ Eliminar")
        btn_del.setStyleSheet("background-color: #c62828; color: white;")
        btn_del.clicked.connect(self._delete_vendor)

        btn_reload = QPushButton("🔄 Recargar")
        btn_reload.clicked.connect(self.load_vendors)

        for b in [btn_add, btn_edit, btn_del, btn_reload]:
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Snapshot ──────────────────────────────────────────────────────────
        layout.addWidget(QLabel("Estado actual (vendedores y asignaciones):"))
        self.snapshot_box = QTextEdit()
        self.snapshot_box.setReadOnly(True)
        self.snapshot_box.setMaximumHeight(160)
        layout.addWidget(self.snapshot_box)

        self.setLayout(layout)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _assigned_courses(self, vendor_id: str, cursos: dict) -> list:
        result = []
        for cid in sorted(cursos.keys(),
                           key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
            curso = cursos.get(cid, {})
            vids = [str(x) for x in (curso.get("vendedor_ids") or []) if str(x)]
            single = str(curso.get("vendedor_id", "")).strip()
            if single and single not in vids:
                vids.append(single)
            vids = list(dict.fromkeys(vids))
            if str(vendor_id) in vids:
                result.append(str(curso.get("nombre", f"Curso {cid}")))
        return result

    def _refresh_snapshot(self, vendedores: dict, cursos: dict):
        lines = ["Vendedores registrados:", ""]
        for vid in sorted(vendedores.keys(),
                           key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
            v = vendedores.get(vid, {})
            full = f"{v.get('nombre', '')} {v.get('apellido', '')}".strip()
            assigned = self._assigned_courses(str(vid), cursos)
            lines.append(f"  [{vid}] {full} | {v.get('telefono', '')} | {v.get('correo', '')}")
            lines.append(f"        Cursos: {', '.join(assigned) if assigned else '—'}")
        self.snapshot_box.setPlainText("\n".join(lines))

    # ── Carga de datos ────────────────────────────────────────────────────────

    def load_vendors(self):
        client = get_client()
        ok, config, err = client.get_menu_config()
        if not ok:
            QMessageBox.critical(self, "Error", f"No se pudo cargar vendedores:\n{err}")
            return

        self.menu_config = config
        vendedores = config.get("vendedores", {}) if isinstance(config, dict) else {}
        cursos = config.get("cursos", {}) if isinstance(config, dict) else {}

        self.vendors = []
        for vid in sorted(vendedores.keys(),
                           key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
            v = vendedores.get(vid, {})
            asg = self._assigned_courses(str(vid), cursos)
            self.vendors.append({
                "id": str(vid),
                "nombre": str(v.get("nombre", "")),
                "apellido": str(v.get("apellido", "")),
                "telefono": str(v.get("telefono", "")),
                "correo": str(v.get("correo", "")),
                "cursos": ", ".join(asg) if asg else "—",
            })

        self.table.setRowCount(len(self.vendors))
        for row, vnd in enumerate(self.vendors):
            full = f"{vnd['nombre']} {vnd['apellido']}".strip()
            self.table.setItem(row, 0, QTableWidgetItem(vnd["id"]))
            self.table.setItem(row, 1, QTableWidgetItem(full))
            self.table.setItem(row, 2, QTableWidgetItem(vnd["telefono"] or "—"))
            self.table.setItem(row, 3, QTableWidgetItem(vnd["correo"] or "—"))
            self.table.setItem(row, 4, QTableWidgetItem(vnd["cursos"]))

        self._refresh_snapshot(vendedores, cursos)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _add_vendor(self):
        cursos = self.menu_config.get("cursos", {})
        dlg = VendorDialog(cursos=cursos, parent=self)
        if not dlg.exec():
            return
        vdata = dlg.get_vendor()
        if not vdata["nombre"]:
            QMessageBox.warning(self, "Aviso", "El nombre es obligatorio.")
            return

        vendedores = self.menu_config.get("vendedores", {})
        numeric = [int(k) for k in vendedores if str(k).isdigit()]
        new_id = str((max(numeric) + 1) if numeric else 1)
        vendedores[new_id] = vdata
        self.menu_config["vendedores"] = vendedores

        # Asignar cursos seleccionados
        assigned_ids = dlg.get_assigned_course_ids()
        for cid, curso in cursos.items():
            vids = list(dict.fromkeys(
                [str(x) for x in (curso.get("vendedor_ids") or []) if str(x)]
            ))
            if str(cid) in assigned_ids and new_id not in vids:
                vids.append(new_id)
            curso["vendedor_ids"] = vids
            if vids:
                curso["vendedor_id"] = vids[0]

        client = get_client()
        ok, _, err = client.save_menu_config(self.menu_config)
        if ok:
            QMessageBox.information(self, "Éxito", "Vendedor agregado.")
            self.load_vendors()
        else:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{err}")

    def _edit_vendor(self, row: int = -1):
        if row < 0:
            row = self.table.currentRow()
        if row < 0 or row >= len(self.vendors):
            QMessageBox.warning(self, "Aviso", "Seleccioná un vendedor.")
            return

        vendor = self.vendors[row]
        cursos = self.menu_config.get("cursos", {})
        dlg = VendorDialog(vendor=vendor, cursos=cursos, parent=self)
        if not dlg.exec():
            return

        vdata = dlg.get_vendor()
        vendor_id = str(vendor["id"])
        vendedores = self.menu_config.get("vendedores", {})
        if vendor_id not in vendedores:
            QMessageBox.warning(self, "Aviso", "El vendedor ya no existe.")
            self.load_vendors()
            return

        vendedores[vendor_id] = vdata
        self.menu_config["vendedores"] = vendedores

        # Actualizar asignaciones de cursos
        assigned_ids = dlg.get_assigned_course_ids()
        for cid, curso in cursos.items():
            vids = list(dict.fromkeys(
                [str(x) for x in (curso.get("vendedor_ids") or []) if str(x)]
            ))
            single = str(curso.get("vendedor_id", "")).strip()
            if single and single not in vids:
                vids.append(single)
            if str(cid) in assigned_ids:
                if vendor_id not in vids:
                    vids.append(vendor_id)
            else:
                vids = [x for x in vids if x != vendor_id]
            if not vids:
                others = [v for v in vendedores if v != vendor_id]
                vids = [others[0]] if others else [vendor_id]
            curso["vendedor_ids"] = vids
            curso["vendedor_id"] = vids[0]

        client = get_client()
        ok, _, err = client.save_menu_config(self.menu_config)
        if ok:
            QMessageBox.information(self, "Éxito", "Vendedor actualizado.")
            self.load_vendors()
        else:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{err}")

    def _delete_vendor(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.vendors):
            QMessageBox.warning(self, "Aviso", "Seleccioná un vendedor.")
            return

        reply = QMessageBox.question(
            self, "Confirmar", "¿Eliminar este vendedor?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        vendor = self.vendors[row]
        vendor_id = str(vendor["id"])
        vendedores = self.menu_config.get("vendedores", {})

        if vendor_id not in vendedores:
            self.load_vendors()
            return
        if len(vendedores) <= 1:
            QMessageBox.warning(self, "Aviso", "No podés eliminar el único vendedor.")
            return

        del vendedores[vendor_id]
        self.menu_config["vendedores"] = vendedores

        cursos = self.menu_config.get("cursos", {})
        fallback = sorted(
            vendedores.keys(), key=lambda x: int(str(x)) if str(x).isdigit() else 9999
        )[0]
        for _cid, curso in cursos.items():
            vids = [str(x) for x in (curso.get("vendedor_ids") or [])
                    if str(x) and str(x) != vendor_id]
            if not vids:
                vids = [fallback]
            curso["vendedor_ids"] = vids
            curso["vendedor_id"] = vids[0]

        client = get_client()
        ok, _, err = client.save_menu_config(self.menu_config)
        if ok:
            QMessageBox.information(self, "Éxito", "Vendedor eliminado.")
            self.load_vendors()
        else:
            QMessageBox.critical(self, "Error", f"No se pudo eliminar:\n{err}")
