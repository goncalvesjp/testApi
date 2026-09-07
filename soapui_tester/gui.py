"""IHM PyQt6 : charger un projet SoapUI, lancer les tests, consulter le
rapport (requete/reponse/assertions avec attendu vs recu) et exporter en HTML."""
import sys
import threading

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidgetItem,
)

from gui.ui_main_window import Ui_MainWindow
from gui.ui_properties_dialog import Ui_PropertiesDialog

from . import serializer
from .models import Assertion
from .parser import parse_project
from .report import save_html_report
from .runner import run_project

_HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]

_STATUS_COLORS = {
    "PASS": QColor("#1b8a4c"),
    "FAIL": QColor("#c0392b"),
    "ERROR": QColor("#a33ba0"),
    "SKIPPED": QColor("#8a8f98"),
    "RUNNING": QColor("#c98a12"),
}


def _proxies_from_text(text: str) -> dict:
    text = text.strip()
    if not text:
        return None
    url = text if "://" in text else f"http://{text}"
    return {"http": url, "https": url}


def _fmt_headers(headers: dict) -> str:
    if not headers:
        return "(aucun en-tete)"
    return "\n".join(f"{k}: {v}" for k, v in headers.items())


def _add_kv_row(table: QTableWidget, key: str = "", value: str = ""):
    row = table.rowCount()
    table.insertRow(row)
    table.setItem(row, 0, QTableWidgetItem(key))
    table.setItem(row, 1, QTableWidgetItem(value))


def _fill_kv_table(table: QTableWidget, data: dict):
    table.setRowCount(0)
    for key, value in data.items():
        _add_kv_row(table, key, value)


def _read_kv_table(table: QTableWidget) -> dict:
    result = {}
    for row in range(table.rowCount()):
        key_item = table.item(row, 0)
        value_item = table.item(row, 1)
        key = key_item.text().strip() if key_item else ""
        if key:
            result[key] = value_item.text() if value_item else ""
    return result


def _remove_selected_rows(table: QTableWidget):
    rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
    for row in rows:
        table.removeRow(row)


def _config_to_text(config: dict) -> str:
    lines = []
    for key, value in config.items():
        for item in value if isinstance(value, list) else [value]:
            lines.append(f"{key}: {item}")
    return "\n".join(lines)


def _text_to_config(text: str) -> dict:
    config = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if key in config:
            existing = config[key]
            config[key] = existing + [value] if isinstance(existing, list) else [existing, value]
        else:
            config[key] = value
    return config


class RunWorker(QObject):
    step_started = pyqtSignal(str, str, str)
    step_done = pyqtSignal(str, str, str, object)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, project, timeout, verify_ssl, extra_properties, cancel_event, proxies=None):
        super().__init__()
        self.project = project
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.extra_properties = extra_properties
        self.cancel_event = cancel_event
        self.proxies = proxies

    def run(self):
        try:
            result = run_project(
                self.project,
                timeout=self.timeout,
                verify_ssl=self.verify_ssl,
                on_step_start=lambda s, c, st: self.step_started.emit(s, c, st),
                on_step_done=lambda s, c, st, r: self.step_done.emit(s, c, st, r),
                cancel_event=self.cancel_event,
                extra_properties=self.extra_properties,
                proxies=self.proxies,
            )
            self.finished.emit(result)
        except Exception as exc:  # garde-fou
            self.failed.emit(str(exc))


class PropertiesDialog(QDialog, Ui_PropertiesDialog):
    def __init__(self, properties: dict, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        _fill_kv_table(self.table, properties)

        self.add_btn.clicked.connect(lambda: _add_kv_row(self.table))
        self.del_btn.clicked.connect(lambda: _remove_selected_rows(self.table))
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    def get_properties(self) -> dict:
        return _read_kv_table(self.table)


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()

        self.project = None
        self.run_result = None
        self.property_overrides = {}
        self.cancel_event = None
        self.thread = None
        self.worker = None

        self._suite_items = {}
        self._case_items = {}
        self._step_items = {}
        self._runnable_coords = []
        self._step_results = {}
        self._progress_index = 0

        self._current_edit_coords = None
        self._editing_assertions = []

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        self.setupUi(self)

        # Widgets non representables proprement dans le .ui : inseres dans la
        # toolbar par code, comme avant la migration vers Designer. Le .ui
        # place deja un separateur entre export_action et insecure_action ;
        # on insere le label + le spinbox entre les deux.
        self.toolbar.insertWidget(self.insecure_action, QLabel(" Timeout (s): "))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 300)
        self.timeout_spin.setValue(30)
        self.toolbar.insertWidget(self.insecure_action, self.timeout_spin)

        self.toolbar.insertWidget(self.insecure_action, QLabel(" Proxy : "))
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("host:port (vide = aucun)")
        self.proxy_edit.setMaximumWidth(160)
        self.toolbar.insertWidget(self.insecure_action, self.proxy_edit)

        self.edit_method_combo.addItems(_HTTP_METHODS)

        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.assertions_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.assertions_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.assertions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.edit_headers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.edit_headers_table.setMaximumHeight(120)

        self.splitter.setSizes([420, 780])

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.status_bar.showMessage("Ouvrez un fichier soapui-project.xml pour commencer.")

        # ---------- Connexions de signaux ----------
        self.open_action.triggered.connect(self.open_project)
        self.run_action.triggered.connect(self.run_tests)
        self.stop_action.triggered.connect(self.stop_tests)
        self.props_action.triggered.connect(self.edit_properties)
        self.save_action.triggered.connect(self.save_project)
        self.export_action.triggered.connect(self.export_report)

        self.tree.currentItemChanged.connect(self._on_selection_changed)
        self.tree.customContextMenuRequested.connect(self._show_tree_context_menu)

        self.add_header_btn.clicked.connect(lambda: _add_kv_row(self.edit_headers_table))
        self.del_header_btn.clicked.connect(lambda: _remove_selected_rows(self.edit_headers_table))

        self.edit_assertions_table.currentCellChanged.connect(self._on_assertion_row_changed)
        self.add_assertion_btn.clicked.connect(self._add_assertion_row)
        self.del_assertion_btn.clicked.connect(self._remove_assertion_row)

        self.apply_edit_btn.clicked.connect(self._apply_step_edits)

    # ---------- Chargement du projet ----------
    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un projet SoapUI", "", "Projets SoapUI (*.xml)")
        if not path:
            return
        try:
            self.project = parse_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Erreur de parsing", f"Impossible de lire le projet :\n{exc}")
            return

        self.property_overrides = {}
        self.run_result = None
        self._step_results = {}
        self.export_action.setEnabled(False)
        self._populate_tree()
        self.run_action.setEnabled(True)
        self.save_action.setEnabled(True)
        total_steps = len(self._runnable_coords)
        self.status_bar.showMessage(
            f"Projet '{self.project.name}' charge — {len(self.project.test_suites)} test suite(s), "
            f"{total_steps} step(s) executable(s)."
        )

    def _populate_tree(self):
        self.tree.clear()
        self._suite_items = {}
        self._case_items = {}
        self._step_items = {}
        self._runnable_coords = []

        for si, suite in enumerate(self.project.test_suites):
            suite_item = QTreeWidgetItem([suite.name, "", f"{len(suite.test_cases)} test case(s)"])
            self.tree.addTopLevelItem(suite_item)
            self._suite_items[si] = suite_item

            for ci, case in enumerate(suite.test_cases):
                label = case.name + (" (desactive)" if case.disabled else "")
                case_item = QTreeWidgetItem([label, "", f"{len(case.test_steps)} step(s)"])
                case_item.setData(0, Qt.ItemDataRole.UserRole, (si, ci))
                suite_item.addChild(case_item)
                self._case_items[(si, ci)] = case_item

                for sti, step in enumerate(case.test_steps):
                    info = f"{step.method} {step.endpoint}" if step.is_executable else step.step_type
                    step_item = QTreeWidgetItem([step.name, "", info])
                    step_item.setData(0, Qt.ItemDataRole.UserRole, (si, ci, sti))
                    case_item.addChild(step_item)
                    self._step_items[(si, ci, sti)] = step_item

                if not case.disabled:
                    for sti in range(len(case.test_steps)):
                        self._runnable_coords.append((si, ci, sti))

        self.tree.expandAll()

    # ---------- Duplication ----------
    def _show_tree_context_menu(self, pos):
        if self.stop_action.isEnabled():
            return  # execution en cours : ne pas muter le projet en parallele
        item = self.tree.itemAt(pos)
        if item is None:
            return
        coords = item.data(0, Qt.ItemDataRole.UserRole)
        if not coords:
            return

        menu = QMenu(self)
        if len(coords) == 3:
            duplicate_action = menu.addAction("Dupliquer ce test step")
        else:
            duplicate_action = menu.addAction("Dupliquer ce test case")

        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is duplicate_action:
            if len(coords) == 3:
                self._duplicate_step(coords)
            else:
                self._duplicate_case(coords)

    def _duplicate_step(self, coords):
        si, ci, sti = coords
        case = self.project.test_suites[si].test_cases[ci]
        step = case.test_steps[sti]
        namespace = getattr(self.project, "_xml_namespace", "")
        new_step = serializer.duplicate_test_step(namespace, case, step)

        self._populate_tree()
        new_item = self._step_items.get((si, ci, len(case.test_steps) - 1))
        if new_item:
            self.tree.setCurrentItem(new_item)
        self.status_bar.showMessage(f"Etape dupliquee : « {new_step.name} ».")

    def _duplicate_case(self, coords):
        si, ci = coords
        suite = self.project.test_suites[si]
        case = suite.test_cases[ci]
        namespace = getattr(self.project, "_xml_namespace", "")
        new_case = serializer.duplicate_test_case(namespace, suite, case)

        self._populate_tree()
        new_item = self._case_items.get((si, len(suite.test_cases) - 1))
        if new_item:
            self.tree.setCurrentItem(new_item)
        self.status_bar.showMessage(f"Test case duplique : « {new_case.name} ».")

    # ---------- Proprietes ----------
    def edit_properties(self):
        if not self.project:
            QMessageBox.information(self, "Aucun projet", "Ouvrez d'abord un projet SoapUI.")
            return
        merged = dict(self.project.properties)
        merged.update(self.property_overrides)
        dialog = PropertiesDialog(merged, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.property_overrides = dialog.get_properties()

    # ---------- Execution ----------
    def run_tests(self):
        if not self.project or not self._runnable_coords:
            QMessageBox.information(self, "Rien a executer", "Aucun test step executable dans ce projet.")
            return

        self._step_results = {}
        self._progress_index = 0
        self.progress_bar.setRange(0, len(self._runnable_coords))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.run_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.export_action.setEnabled(False)
        self.edit_tab.setEnabled(False)
        self.status_bar.showMessage("Execution en cours…")

        for item in self._suite_items.values():
            item.setText(1, "")
        for item in self._case_items.values():
            item.setText(1, "")
        for item in self._step_items.values():
            item.setText(1, "")
            for col in range(3):
                item.setForeground(col, QColor("#1b1f24"))

        self.cancel_event = threading.Event()
        self.thread = QThread()
        self.worker = RunWorker(
            self.project,
            timeout=self.timeout_spin.value(),
            verify_ssl=not self.insecure_action.isChecked(),
            extra_properties=self.property_overrides,
            cancel_event=self.cancel_event,
            proxies=_proxies_from_text(self.proxy_edit.text()),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.step_started.connect(self._on_step_started)
        self.worker.step_done.connect(self._on_step_done)
        self.worker.finished.connect(self._on_run_finished)
        self.worker.failed.connect(self._on_run_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.start()

    def stop_tests(self):
        if self.cancel_event:
            self.cancel_event.set()
        self.stop_action.setEnabled(False)
        self.status_bar.showMessage("Arret demande…")

    def _current_coords(self):
        if 0 <= self._progress_index < len(self._runnable_coords):
            return self._runnable_coords[self._progress_index]
        return None

    def _on_step_started(self, suite_name, case_name, step_name):
        coords = self._current_coords()
        if coords is None:
            return
        item = self._step_items.get(coords)
        if item:
            item.setText(1, "en cours…")
            item.setForeground(1, _STATUS_COLORS["RUNNING"])
            self.tree.scrollToItem(item)

    def _on_step_done(self, suite_name, case_name, step_name, step_result):
        coords = self._current_coords()
        if coords is not None:
            self._step_results[coords] = step_result
            item = self._step_items.get(coords)
            if item:
                item.setText(1, step_result.status)
                item.setForeground(1, _STATUS_COLORS.get(step_result.status, QColor("black")))
            self._progress_index += 1
            self.progress_bar.setValue(self._progress_index)
            if self.tree.currentItem() is item:
                self._show_step_detail(coords)

    def _on_run_finished(self, run_result):
        self.run_result = run_result
        self.progress_bar.setVisible(False)
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.export_action.setEnabled(True)
        self.edit_tab.setEnabled(True)

        for si, suite in enumerate(self.project.test_suites):
            self._refresh_case_and_suite_status(si)

        totals = run_result.totals
        self.status_bar.showMessage(
            f"Termine en {run_result.duration_s:.2f}s — "
            f"PASS={totals['passed']} FAIL={totals['failed']} ERROR={totals['errors']} SKIPPED={totals['skipped']}"
        )

    def _refresh_case_and_suite_status(self, si):
        suite = self.project.test_suites[si]
        suite_statuses = []
        for ci, case in enumerate(suite.test_cases):
            case_statuses = []
            for sti in range(len(case.test_steps)):
                result = self._step_results.get((si, ci, sti))
                if result:
                    case_statuses.append(result.status)
            if case_statuses:
                if "ERROR" in case_statuses:
                    status = "ERROR"
                elif "FAIL" in case_statuses:
                    status = "FAIL"
                elif all(s == "SKIPPED" for s in case_statuses):
                    status = "SKIPPED"
                else:
                    status = "PASS"
                item = self._case_items[(si, ci)]
                item.setText(1, status)
                item.setForeground(1, _STATUS_COLORS.get(status, QColor("black")))
                suite_statuses.append(status)

        if suite_statuses:
            if "ERROR" in suite_statuses:
                s_status = "ERROR"
            elif "FAIL" in suite_statuses:
                s_status = "FAIL"
            elif all(s == "SKIPPED" for s in suite_statuses):
                s_status = "SKIPPED"
            else:
                s_status = "PASS"
            item = self._suite_items[si]
            item.setText(1, s_status)
            item.setForeground(1, _STATUS_COLORS.get(s_status, QColor("black")))

    def _on_run_failed(self, message):
        self.progress_bar.setVisible(False)
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.edit_tab.setEnabled(True)
        self.status_bar.showMessage("Echec de l'execution.")
        QMessageBox.critical(self, "Erreur d'execution", message)

    # ---------- Detail panel ----------
    def _step_at(self, coords):
        si, ci, sti = coords
        return self.project.test_suites[si].test_cases[ci].test_steps[sti]

    def _on_selection_changed(self, current, previous):
        if current is None:
            return
        coords = current.data(0, Qt.ItemDataRole.UserRole)
        # Seuls les items de test step (coords a 3 elements) ont un detail /
        # une edition ; les suites (pas de coords) et les test cases (coords
        # a 2 elements) se contentent de vider le panneau de droite.
        if not coords or len(coords) != 3:
            self.detail_title.setText(current.text(0))
            self.request_view.setPlainText("")
            self.response_view.setPlainText("")
            self.assertions_table.setRowCount(0)
            self._current_edit_coords = None
            self.edit_tab.setEnabled(False)
            return
        self.edit_tab.setEnabled(True)
        self._show_step_detail(coords)

    def _show_step_detail(self, coords):
        step = self._step_at(coords)
        result = self._step_results.get(coords)
        self._load_step_for_edit(coords)

        self.detail_title.setText(f"{step.name}  —  {step.step_type}")

        req_lines = [f"{step.method} {step.endpoint}", "", "En-tetes :", _fmt_headers(step.headers)]
        if step.request_body:
            req_lines += ["", "Corps :", step.request_body]
        self.request_view.setPlainText("\n".join(req_lines))

        if result is None:
            self.response_view.setPlainText("(pas encore execute)")
            self.assertions_table.setRowCount(0)
            return

        if result.error_message and result.response_status is None:
            self.response_view.setPlainText(f"ERREUR : {result.error_message}")
        else:
            resp_lines = [
                f"HTTP {result.response_status}  —  {result.elapsed_ms:.0f} ms",
                "",
                "En-tetes :",
                _fmt_headers(result.response_headers),
                "",
                "Corps :",
                result.response_body,
            ]
            self.response_view.setPlainText("\n".join(resp_lines))

        self.assertions_table.setRowCount(len(result.assertion_results))
        for row, ar in enumerate(result.assertion_results):
            values = [ar.name, ar.type, ar.status, ar.expected, ar.actual]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 2:
                    cell.setForeground(_STATUS_COLORS.get(ar.status, QColor("black")))
                self.assertions_table.setItem(row, col, cell)

    # ---------- Edition des test steps ----------
    def _load_step_for_edit(self, coords):
        self._current_edit_coords = coords
        step = self._step_at(coords)

        self.edit_name.setText(step.name)
        self.edit_enabled_cb.setChecked(not step.disabled)

        is_rest = step.step_type == "restrequest"
        self.edit_method_combo.setEnabled(is_rest)
        if is_rest:
            idx = self.edit_method_combo.findText(step.method)
            self.edit_method_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.edit_endpoint.setText(step.endpoint)
        self.edit_body.setPlainText(step.request_body)
        _fill_kv_table(self.edit_headers_table, step.headers)

        self._editing_assertions = [
            Assertion(type=a.type, name=a.name, config=dict(a.config)) for a in step.assertions
        ]
        self._refresh_assertions_table()

        editable = step.step_type in ("restrequest", "request")
        for widget in (
            self.edit_endpoint,
            self.edit_body,
            self.edit_headers_table,
            self.add_header_btn,
            self.del_header_btn,
            self.edit_assertions_table,
            self.add_assertion_btn,
            self.del_assertion_btn,
        ):
            widget.setEnabled(editable)

    def _refresh_assertions_table(self):
        self.edit_assertions_table.blockSignals(True)
        self.edit_assertions_table.setRowCount(len(self._editing_assertions))
        for row, assertion in enumerate(self._editing_assertions):
            self.edit_assertions_table.setItem(row, 0, QTableWidgetItem(assertion.type))
            self.edit_assertions_table.setItem(row, 1, QTableWidgetItem(assertion.name))
        self.edit_assertions_table.blockSignals(False)
        self.edit_assertion_config.clear()
        self.edit_assertion_config.setEnabled(False)

    def _flush_assertion_config(self, row):
        if 0 <= row < len(self._editing_assertions):
            self._editing_assertions[row].config = _text_to_config(self.edit_assertion_config.toPlainText())

    def _on_assertion_row_changed(self, current_row, current_col, previous_row, previous_col):
        self._flush_assertion_config(previous_row)
        if 0 <= current_row < len(self._editing_assertions):
            self.edit_assertion_config.setEnabled(self.edit_assertions_table.isEnabled())
            self.edit_assertion_config.setPlainText(_config_to_text(self._editing_assertions[current_row].config))
        else:
            self.edit_assertion_config.clear()
            self.edit_assertion_config.setEnabled(False)

    def _add_assertion_row(self):
        self._editing_assertions.append(
            Assertion(type="Valid HTTP Status Codes", name="Valid HTTP Status Codes", config={})
        )
        self._refresh_assertions_table()
        self.edit_assertions_table.setCurrentCell(len(self._editing_assertions) - 1, 0)

    def _remove_assertion_row(self):
        rows = sorted({idx.row() for idx in self.edit_assertions_table.selectedIndexes()}, reverse=True)
        for row in rows:
            del self._editing_assertions[row]
        self._refresh_assertions_table()

    def _collect_assertions(self) -> list:
        self._flush_assertion_config(self.edit_assertions_table.currentRow())
        result = []
        for row, assertion in enumerate(self._editing_assertions):
            type_item = self.edit_assertions_table.item(row, 0)
            name_item = self.edit_assertions_table.item(row, 1)
            a_type = type_item.text().strip() if type_item else assertion.type
            a_name = (name_item.text().strip() if name_item else assertion.name) or a_type
            result.append(Assertion(type=a_type, name=a_name, config=dict(assertion.config)))
        return result

    def _apply_step_edits(self):
        coords = self._current_edit_coords
        if coords is None:
            return
        step = self._step_at(coords)

        name = self.edit_name.text().strip()
        if name:
            step.name = name
        step.disabled = not self.edit_enabled_cb.isChecked()

        if step.step_type in ("restrequest", "request"):
            if step.step_type == "restrequest":
                step.method = self.edit_method_combo.currentText()
            step.endpoint = self.edit_endpoint.text()
            step.request_body = self.edit_body.toPlainText()
            step.headers = _read_kv_table(self.edit_headers_table)
            step.assertions = self._collect_assertions()

        item = self._step_items.get(coords)
        if item:
            label = step.name + (" (desactive)" if step.disabled else "")
            item.setText(0, label)
            info = f"{step.method} {step.endpoint}" if step.is_executable else step.step_type
            item.setText(2, info)

        self.status_bar.showMessage(f"Modifications appliquees a l'etape « {step.name} ».")

    def save_project(self):
        if not self.project:
            QMessageBox.information(self, "Aucun projet", "Ouvrez d'abord un projet SoapUI.")
            return
        path = self.project.source_path
        reply = QMessageBox.question(
            self,
            "Enregistrer le projet",
            f"Ecrire les modifications dans :\n{path}\n\nCeci ecrasera le fichier source. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            serializer.save_project(self.project)
        except Exception as exc:
            QMessageBox.critical(self, "Erreur d'enregistrement", str(exc))
            return
        self.status_bar.showMessage(f"Projet enregistre : {path}")

    # ---------- Export ----------
    def export_report(self):
        if not self.run_result:
            QMessageBox.information(self, "Aucun resultat", "Lancez d'abord les tests.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le rapport HTML", "report.html", "HTML (*.html)")
        if not path:
            return
        save_html_report(self.run_result, path)
        self.status_bar.showMessage(f"Rapport exporte : {path}")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
