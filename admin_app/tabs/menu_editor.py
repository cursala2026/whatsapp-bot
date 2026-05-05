"""Tab para editar menús y configuración general."""

import json
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLabel, QMessageBox, QTabWidget, QLineEdit, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QAbstractItemView, QGroupBox, QScrollArea, QCheckBox,
    QSizePolicy,
)

from api_client import get_client


# ─── Threads ──────────────────────────────────────────────────────────────────

class DeployThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def run(self):
        project_root = Path(__file__).resolve().parents[2]
        cmd = [
            "gcloud", "run", "deploy", "cursala-bot",
            "--source", ".",
            "--region", "southamerica-east1",
            "--project", "datosbotcursala",
            "--quiet",
        ]
        try:
            result = subprocess.run(
                cmd, cwd=str(project_root), capture_output=True, text=True, check=False
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            self.finished_signal.emit(result.returncode == 0, output.strip())
        except Exception as exc:
            self.finished_signal.emit(False, str(exc))


# ─── Diálogo curso ────────────────────────────────────────────────────────────

class CourseDialog(QDialog):
    """Diálogo para agregar / editar un curso."""

    def __init__(self, course_id: str = "", course: dict = None,
                 vendedores: dict = None, parent=None):
        super().__init__(parent)
        self.course_id = course_id
        self.course = course or {}
        self.vendedores = vendedores or {}
        self.vendor_checkboxes: dict = {}
        self.setWindowTitle("Nuevo Curso" if not course_id else "Editar Curso")
        self.setMinimumWidth(520)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        form = QFormLayout()

        self.id_input = QLineEdit(self.course_id)
        self.id_input.setEnabled(not bool(self.course_id))   # inmutable al editar
        form.addRow("ID del Curso *:", self.id_input)

        self.nombre_input = QLineEdit(self.course.get("nombre", ""))
        form.addRow("Nombre *:", self.nombre_input)

        self.descripcion_input = QTextEdit()
        desc = self.course.get("descripcion") or self.course.get("description", "")
        self.descripcion_input.setPlainText(str(desc))
        self.descripcion_input.setMaximumHeight(80)
        form.addRow("Descripción:", self.descripcion_input)

        self.precio_input = QLineEdit(str(self.course.get("precio", "") or ""))
        form.addRow("Precio:", self.precio_input)

        self.duracion_input = QLineEdit(str(self.course.get("duracion", "") or ""))
        form.addRow("Duración:", self.duracion_input)

        self.modalidad_input = QLineEdit(str(self.course.get("modalidad", "") or ""))
        form.addRow("Modalidad:", self.modalidad_input)

        layout.addLayout(form)

        # ── Vendedores asignables ─────────────────────────────────────────────
        if self.vendedores:
            grp = QGroupBox("Vendedores asignados a este curso")
            grp_layout = QVBoxLayout()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(160)
            inner = QWidget()
            inner_layout = QVBoxLayout(inner)
            inner_layout.setSpacing(2)

            assigned = set(
                [str(x) for x in (self.course.get("vendedor_ids") or [])]
            )
            single = str(self.course.get("vendedor_id", "")).strip()
            if single:
                assigned.add(single)

            for vid in sorted(self.vendedores.keys(),
                               key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
                v = self.vendedores[vid]
                label = f"[{vid}] {v.get('nombre', '')} {v.get('apellido', '')}".strip()
                chk = QCheckBox(label)
                chk.setChecked(str(vid) in assigned)
                self.vendor_checkboxes[str(vid)] = chk
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

    def get_course_id(self) -> str:
        return self.id_input.text().strip()

    def get_course(self) -> dict:
        d = dict(self.course)
        d["nombre"] = self.nombre_input.text().strip()
        d["descripcion"] = self.descripcion_input.toPlainText().strip()
        d["precio"] = self.precio_input.text().strip()
        d["duracion"] = self.duracion_input.text().strip()
        d["modalidad"] = self.modalidad_input.text().strip()
        return d

    def get_assigned_vendor_ids(self) -> list:
        return [vid for vid, chk in self.vendor_checkboxes.items() if chk.isChecked()]


# ─── Widget de opciones dinámicas ─────────────────────────────────────────────

class DynamicOptionsWidget(QWidget):
    """Widget editable para opciones de menú (número → texto)."""

    def __init__(self):
        super().__init__()
        self._rows: list = []   # list of (key_input, val_input, row_widget)
        self._init_ui()

    def _init_ui(self):
        self._outer = QVBoxLayout(self)
        self._rows_layout = QVBoxLayout()
        self._outer.addLayout(self._rows_layout)
        add_btn = QPushButton("➕ Agregar opción")
        add_btn.clicked.connect(lambda: self.add_row())
        self._outer.addWidget(add_btn)
        self._outer.addStretch()

    def add_row(self, key: str = "", value: str = ""):
        rw = QWidget()
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        ki = QLineEdit(str(key))
        ki.setMaximumWidth(52)
        ki.setPlaceholderText("N°")
        vi = QLineEdit(str(value))
        vi.setPlaceholderText("Texto de la opción")
        rm = QPushButton("✕")
        rm.setFixedWidth(28)
        rm.clicked.connect(lambda: self._remove(rw))
        rl.addWidget(ki)
        rl.addWidget(vi)
        rl.addWidget(rm)
        self._rows_layout.addWidget(rw)
        self._rows.append((ki, vi, rw))

    def _remove(self, rw: QWidget):
        self._rows = [(k, v, w) for k, v, w in self._rows if w is not rw]
        rw.setParent(None)

    def set_options(self, options: dict):
        for _, _, rw in self._rows:
            rw.setParent(None)
        self._rows = []
        for key in sorted(options.keys(),
                           key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
            self.add_row(key, options[key])

    def get_options(self) -> dict:
        result = {}
        for ki, vi, _ in self._rows:
            k = ki.text().strip()
            if k:
                result[k] = vi.text().strip()
        return result


# ─── Tab principal ─────────────────────────────────────────────────────────────

class MenuEditorTab(QWidget):
    """Pestaña para editar menús y configuración."""

    def __init__(self):
        super().__init__()
        self.menu_config: dict = {}
        self.deploy_thread = None
        self._init_ui()
        self.load_menu_config()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("📝 Editor de Menús y Configuración"))

        self.inner_tabs = QTabWidget()

        # ── [1] Saludo ────────────────────────────────────────────────────────
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.addWidget(QLabel("Mensaje de bienvenida que ve el usuario al iniciar el bot:"))
        self.greeting_input = QTextEdit()
        self.greeting_input.setPlaceholderText("Ej: ¡Hola! Bienvenido a Cursala ✨ …")
        l1.addWidget(self.greeting_input)
        self.inner_tabs.addTab(w1, "💬 Saludo")

        # ── [2] Opciones ──────────────────────────────────────────────────────
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.addWidget(QLabel(
            "Opciones del menú principal (número → texto que ve el usuario):"
        ))
        scroll2 = QScrollArea()
        scroll2.setWidgetResizable(True)
        self.options_widget = DynamicOptionsWidget()
        scroll2.setWidget(self.options_widget)
        l2.addWidget(scroll2)
        self.inner_tabs.addTab(w2, "🔢 Opciones")

        # ── [3] Respuestas ────────────────────────────────────────────────────
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        l3.addWidget(QLabel(
            "Texto mostrado al usuario cuando elige cada opción del menú:"
        ))
        self.responses_container = QVBoxLayout()
        self.responses_inputs: dict = {}
        inner3 = QWidget()
        inner3.setLayout(self.responses_container)
        scroll3 = QScrollArea()
        scroll3.setWidgetResizable(True)
        scroll3.setWidget(inner3)
        l3.addWidget(scroll3)
        self.inner_tabs.addTab(w3, "💡 Respuestas")

        # ── [4] Cursos ────────────────────────────────────────────────────────
        w4 = QWidget()
        l4 = QVBoxLayout(w4)
        l4.addWidget(QLabel("Cursos disponibles en el bot:"))

        self.courses_table = QTableWidget()
        self.courses_table.setColumnCount(6)
        self.courses_table.setHorizontalHeaderLabels(
            ["ID", "Nombre", "Precio", "Duración", "Modalidad", "Vendedores"]
        )
        ch = self.courses_table.horizontalHeader()
        ch.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.courses_table.setColumnWidth(0, 44)
        self.courses_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.courses_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.courses_table.doubleClicked.connect(
            lambda idx: self._edit_course(idx.row())
        )
        l4.addWidget(self.courses_table)

        c_btns = QHBoxLayout()
        btn_add_c = QPushButton("➕ Nuevo Curso")
        btn_add_c.setStyleSheet("background-color: #4CAF50; color: white;")
        btn_add_c.clicked.connect(self._add_course)
        btn_edit_c = QPushButton("✏️ Editar")
        btn_edit_c.clicked.connect(self._edit_course)
        btn_del_c = QPushButton("🗑️ Eliminar")
        btn_del_c.setStyleSheet("background-color: #c62828; color: white;")
        btn_del_c.clicked.connect(self._delete_course)
        for b in [btn_add_c, btn_edit_c, btn_del_c]:
            c_btns.addWidget(b)
        c_btns.addStretch()
        l4.addLayout(c_btns)
        self.inner_tabs.addTab(w4, "📚 Cursos")

        # ── [5] Configuración ─────────────────────────────────────────────────
        w5 = QWidget()
        l5 = QVBoxLayout(w5)
        form5 = QFormLayout()

        self.email_enabled_chk = QCheckBox("Notificaciones por email activas")
        form5.addRow(self.email_enabled_chk)

        self.email_dest_input = QLineEdit()
        form5.addRow("Email destinatario:", self.email_dest_input)

        self.email_subject_input = QLineEdit()
        form5.addRow("Asunto del email:", self.email_subject_input)

        self.email_intro_input = QTextEdit()
        self.email_intro_input.setPlaceholderText("Texto de introducción del email")
        self.email_intro_input.setMaximumHeight(90)
        form5.addRow("Intro email:", self.email_intro_input)

        l5.addLayout(form5)
        l5.addWidget(QLabel("Reglas de IA / Gemini (una por línea):"))
        self.prompt_rules_input = QTextEdit()
        self.prompt_rules_input.setPlaceholderText(
            "Ej: Si consultan precio, ofrecer 3 cuotas sin interés."
        )
        l5.addWidget(self.prompt_rules_input)
        self.inner_tabs.addTab(w5, "⚙️ Configuración")

        layout.addWidget(self.inner_tabs)

        # ── Barra de acciones globales ─────────────────────────────────────────
        act_row = QHBoxLayout()

        btn_load = QPushButton("🔄 Recargar")
        btn_load.clicked.connect(self.load_menu_config)

        btn_save = QPushButton("💾 Guardar Cambios")
        btn_save.setStyleSheet("background-color: #1976D2; color: white;")
        btn_save.clicked.connect(self.save_menu_config)

        btn_backup = QPushButton("📦 Crear Backup")
        btn_backup.clicked.connect(self._create_backup)

        btn_deploy = QPushButton("🚀 Guardar y Deploy")
        btn_deploy.setStyleSheet("background-color: #E65100; color: white;")
        btn_deploy.clicked.connect(self._deploy)

        for b in [btn_load, btn_save, btn_backup, btn_deploy]:
            act_row.addWidget(b)
        act_row.addStretch()
        layout.addLayout(act_row)

        # ── Preview de sendeo + snapshot ──────────────────────────────────────
        prev_row = QHBoxLayout()
        self.test_phone_input = QLineEdit()
        self.test_phone_input.setPlaceholderText("Teléfono de prueba (ej: 5492615031839)")
        btn_prev = QPushButton("📨 Enviar menú de prueba al teléfono")
        btn_prev.clicked.connect(self._send_preview)
        prev_row.addWidget(self.test_phone_input)
        prev_row.addWidget(btn_prev)
        layout.addLayout(prev_row)

        layout.addWidget(QLabel("Estado actual cargado en el bot (solo lectura):"))
        self.snapshot_box = QTextEdit()
        self.snapshot_box.setReadOnly(True)
        self.snapshot_box.setMaximumHeight(140)
        layout.addWidget(self.snapshot_box)

        self.setLayout(layout)

    # ── Carga de datos ────────────────────────────────────────────────────────

    def load_menu_config(self):
        client = get_client()
        ok, data, err = client.get_menu_config()
        if not ok:
            QMessageBox.critical(self, "Error", f"No se pudo cargar menu_config:\n{err}")
            return
        self.menu_config = data
        self._populate_ui()

    def _populate_ui(self):
        cfg = self.menu_config

        # Saludo
        self.greeting_input.setPlainText(cfg.get("greeting", ""))

        # Opciones
        self.options_widget.set_options(cfg.get("options", {}))

        # Respuestas: reconstruir sección dinámica
        for i in reversed(range(self.responses_container.count())):
            item = self.responses_container.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        self.responses_inputs = {}
        responses = cfg.get("responses", {})
        for key in sorted(responses.keys(),
                           key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
            lbl = QLabel(f"Respuesta a la opción {key}:")
            lbl.setStyleSheet("font-weight: bold; margin-top: 6px;")
            inp = QTextEdit()
            inp.setPlainText(str(responses.get(key, "")))
            inp.setMaximumHeight(90)
            self.responses_inputs[str(key)] = inp
            self.responses_container.addWidget(lbl)
            self.responses_container.addWidget(inp)

        # Cursos
        self._fill_courses_table(cfg.get("cursos", {}))

        # Configuración
        email_cfg = cfg.get("email_notificacion_admin", {})
        self.email_enabled_chk.setChecked(bool(email_cfg.get("activo", True)))
        self.email_dest_input.setText(str(email_cfg.get("destinatario", "")))
        self.email_subject_input.setText(str(email_cfg.get("asunto", "")))
        self.email_intro_input.setPlainText(str(email_cfg.get("cuerpo_intro", "")))

        rules = cfg.get("gemini_prompt_rules", [])
        if isinstance(rules, list):
            self.prompt_rules_input.setPlainText("\n".join([str(r) for r in rules]))

        # Snapshot
        self.snapshot_box.setPlainText(self._build_snapshot())

    # ── Tabla de cursos ───────────────────────────────────────────────────────

    def _fill_courses_table(self, cursos: dict):
        vendedores = self.menu_config.get("vendedores", {})
        self.courses_table.setRowCount(len(cursos))
        for row, cid in enumerate(
            sorted(cursos.keys(), key=lambda x: int(str(x)) if str(x).isdigit() else 9999)
        ):
            c = cursos[cid]
            vids = list(dict.fromkeys(
                [str(x) for x in (c.get("vendedor_ids") or [])]
            ))
            single = str(c.get("vendedor_id", "")).strip()
            if single and single not in vids:
                vids.append(single)
            vendor_names = ", ".join([
                f"{vendedores[v].get('nombre', v)}" if v in vendedores else v
                for v in vids
            ])
            self.courses_table.setItem(row, 0, QTableWidgetItem(str(cid)))
            self.courses_table.setItem(row, 1, QTableWidgetItem(str(c.get("nombre", ""))))
            self.courses_table.setItem(row, 2, QTableWidgetItem(str(c.get("precio", "—"))))
            self.courses_table.setItem(row, 3, QTableWidgetItem(str(c.get("duracion", "—"))))
            self.courses_table.setItem(row, 4, QTableWidgetItem(str(c.get("modalidad", "—"))))
            self.courses_table.setItem(row, 5, QTableWidgetItem(vendor_names or "—"))
        # guardar ids en orden para uso de edit/delete
        self._course_ids_order = sorted(
            cursos.keys(), key=lambda x: int(str(x)) if str(x).isdigit() else 9999
        )

    def _add_course(self):
        vendedores = self.menu_config.get("vendedores", {})
        dlg = CourseDialog(vendedores=vendedores, parent=self)
        if not dlg.exec():
            return
        cid = dlg.get_course_id()
        if not cid:
            QMessageBox.warning(self, "Aviso", "El ID del curso es obligatorio.")
            return
        cursos = self.menu_config.get("cursos", {})
        if cid in cursos:
            QMessageBox.warning(self, "Aviso", f"Ya existe un curso con ID '{cid}'.")
            return
        course = dlg.get_course()
        assigned_vids = dlg.get_assigned_vendor_ids()
        course["vendedor_ids"] = assigned_vids
        course["vendedor_id"] = assigned_vids[0] if assigned_vids else ""
        cursos[cid] = course
        self.menu_config["cursos"] = cursos
        self._save_and_reload()

    def _edit_course(self, row: int = -1):
        if row < 0:
            row = self.courses_table.currentRow()
        if row < 0 or not hasattr(self, "_course_ids_order") or row >= len(self._course_ids_order):
            QMessageBox.warning(self, "Aviso", "Seleccioná un curso primero.")
            return
        cid = self._course_ids_order[row]
        cursos = self.menu_config.get("cursos", {})
        vendedores = self.menu_config.get("vendedores", {})
        dlg = CourseDialog(
            course_id=str(cid), course=cursos.get(cid, {}),
            vendedores=vendedores, parent=self
        )
        if not dlg.exec():
            return
        course = dlg.get_course()
        assigned_vids = dlg.get_assigned_vendor_ids()
        course["vendedor_ids"] = assigned_vids
        course["vendedor_id"] = assigned_vids[0] if assigned_vids else ""
        cursos[cid] = course
        self.menu_config["cursos"] = cursos
        self._save_and_reload()

    def _delete_course(self):
        row = self.courses_table.currentRow()
        if row < 0 or not hasattr(self, "_course_ids_order") or row >= len(self._course_ids_order):
            QMessageBox.warning(self, "Aviso", "Seleccioná un curso primero.")
            return
        cid = self._course_ids_order[row]
        reply = QMessageBox.question(
            self, "Confirmar", f"¿Eliminar el curso '{cid}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cursos = self.menu_config.get("cursos", {})
        if cid in cursos:
            del cursos[cid]
        self.menu_config["cursos"] = cursos
        self._save_and_reload()

    # ── Guardar ───────────────────────────────────────────────────────────────

    def save_menu_config(self) -> bool:
        try:
            rules_raw = self.prompt_rules_input.toPlainText().splitlines()
            rules = [" ".join(l.split()).strip() for l in rules_raw if l.strip()]

            email_cfg = self.menu_config.get("email_notificacion_admin", {})
            email_cfg["activo"] = self.email_enabled_chk.isChecked()
            email_cfg["destinatario"] = self.email_dest_input.text().strip()
            email_cfg["asunto"] = self.email_subject_input.text().strip()
            email_cfg["cuerpo_intro"] = self.email_intro_input.toPlainText().strip()

            self.menu_config["greeting"] = self.greeting_input.toPlainText()
            self.menu_config["options"] = self.options_widget.get_options()
            self.menu_config["responses"] = {
                k: v.toPlainText() for k, v in self.responses_inputs.items()
            }
            self.menu_config["email_notificacion_admin"] = email_cfg
            self.menu_config["gemini_prompt_rules"] = rules

            client = get_client()
            ok, _, err = client.save_menu_config(self.menu_config)
            if not ok:
                QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{err}")
                return False
            self.snapshot_box.setPlainText(self._build_snapshot())
            QMessageBox.information(self, "Éxito", "Configuración guardada exitosamente.")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Error guardando: {str(exc)}")
            return False

    def _save_and_reload(self):
        client = get_client()
        ok, _, err = client.save_menu_config(self.menu_config)
        if ok:
            self._fill_courses_table(self.menu_config.get("cursos", {}))
            self.snapshot_box.setPlainText(self._build_snapshot())
        else:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{err}")

    # ── Acciones extras ───────────────────────────────────────────────────────

    def _create_backup(self):
        client = get_client()
        ok, data, err = client.create_backup()
        if ok:
            filename = data.get("filename", "(sin nombre)") if isinstance(data, dict) else "(sin nombre)"
            QMessageBox.information(self, "Backup", f"Backup creado: {filename}")
        else:
            QMessageBox.critical(self, "Error", f"No se pudo crear backup:\n{err}")

    def _deploy(self):
        if self.deploy_thread and self.deploy_thread.isRunning():
            QMessageBox.information(self, "Deploy", "Ya hay un deploy en curso.")
            return
        self.save_menu_config()
        self.deploy_thread = DeployThread()
        self.deploy_thread.finished_signal.connect(self._on_deploy_done)
        self.deploy_thread.start()
        QMessageBox.information(self, "Deploy", "Deploy iniciado. Te avisaré al terminar.")

    def _on_deploy_done(self, ok: bool, output: str):
        if ok:
            QMessageBox.information(self, "Deploy", "✅ Deploy completado correctamente.")
        else:
            QMessageBox.critical(self, "Deploy", f"❌ Deploy falló:\n{output[:1000]}")

    def _send_preview(self):
        phone = self.test_phone_input.text().strip()
        if not phone:
            QMessageBox.warning(self, "Prueba", "Ingresá un teléfono de prueba.")
            return
        opts = self.options_widget.get_options()
        lines = [self.greeting_input.toPlainText().strip(), "", "*MENÚ PRINCIPAL*"]
        for k in sorted(opts.keys(), key=lambda x: int(str(x)) if str(x).isdigit() else 9999):
            if opts[k]:
                lines.append(f"{k}. {opts[k]}")
        lines.append("\nEsperando tu respuesta…")
        preview_text = "\n".join(lines)
        client = get_client()
        ok, _, err = client.send_test_message(phone, preview_text)
        if ok:
            QMessageBox.information(self, "Prueba", "✅ Menú de prueba enviado.")
        else:
            QMessageBox.critical(self, "Prueba", f"Error enviando:\n{err}")

    def _build_snapshot(self) -> str:
        cfg = self.menu_config
        options = cfg.get("options", {})
        responses = cfg.get("responses", {})
        cursos = cfg.get("cursos", {})
        vendedores = cfg.get("vendedores", {})
        email_cfg = cfg.get("email_notificacion_admin", {})
        rules = cfg.get("gemini_prompt_rules", [])
        lines = [
            f"Saludo: {cfg.get('greeting', '')[:80]}…",
            f"Opciones: {len(options)}  |  Respuestas: {len(responses)}",
            f"Cursos: {len(cursos)}  |  Vendedores: {len(vendedores)}",
            f"Email: {email_cfg.get('destinatario', '—')} (activo: {email_cfg.get('activo', True)})",
            f"Reglas IA: {len(rules) if isinstance(rules, list) else 0}",
        ]
        return "\n".join(lines)
