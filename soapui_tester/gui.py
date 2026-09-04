"""IHM PyQt6 : charger un projet SoapUI, lancer les tests, consulter le
rapport (requete/reponse/assertions avec attendu vs recu) et exporter en HTML."""
import sys
import threading

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .parser import parse_project
from .report import save_html_report
from .runner import run_project

_STATUS_COLORS = {
    "PASS": QColor("#1b8a4c"),
    "FAIL": QColor("#c0392b"),
    "ERROR": QColor("#a33ba0"),
    "SKIPPED": QColor("#8a8f98"),
    "RUNNING": QColor("#c98a12"),
}


def _fmt_headers(headers: dict) -> str:
    if not headers:
        return "(aucun en-tete)"
    return "\n".join(f"{k}: {v}" for k, v in headers.items())


class RunWorker(QObject):
    step_started = pyqtSignal(str, str, str)
    step_done = pyqtSignal(str, str, str, object)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, project, timeout, verify_ssl, extra_properties, cancel_event):
        super().__init__()
        self.project = project
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.extra_properties = extra_properties
        self.cancel_event = cancel_event

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
            )
            self.finished.emit(result)
        except Exception as exc:  # garde-fou
            self.failed.emit(str(exc))


class PropertiesDialog(QDialog):
    def __init__(self, properties: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Proprietes du projet")
        self.resize(420, 320)
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Nom", "Valeur"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for name, value in properties.items():
            self._add_row(name, value)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Ajouter")
        add_btn.clicked.connect(lambda: self._add_row("", ""))
        del_btn = QPushButton("- Supprimer la ligne")
        del_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self, name, value):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(value))

    def _remove_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def get_properties(self) -> dict:
        props = {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            if name:
                props[name] = value_item.text() if value_item else ""
        return props


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Testeur de projets SoapUI")
        self.resize(1200, 760)

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

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        toolbar = QToolBar("Actions")
        self.addToolBar(toolbar)

        open_action = QAction("Ouvrir un projet SoapUI…", self)
        open_action.triggered.connect(self.open_project)
        toolbar.addAction(open_action)

        self.run_action = QAction("▶ Lancer les tests", self)
        self.run_action.triggered.connect(self.run_tests)
        self.run_action.setEnabled(False)
        toolbar.addAction(self.run_action)

        self.stop_action = QAction("■ Arreter", self)
        self.stop_action.triggered.connect(self.stop_tests)
        self.stop_action.setEnabled(False)
        toolbar.addAction(self.stop_action)

        props_action = QAction("Proprietes du projet…", self)
        props_action.triggered.connect(self.edit_properties)
        toolbar.addAction(props_action)

        self.export_action = QAction("Exporter le rapport HTML…", self)
        self.export_action.triggered.connect(self.export_report)
        self.export_action.setEnabled(False)
        toolbar.addAction(self.export_action)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Timeout (s): "))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 300)
        self.timeout_spin.setValue(30)
        toolbar.addWidget(self.timeout_spin)

        self.insecure_action = QAction("Ignorer erreurs SSL", self)
        self.insecure_action.setCheckable(True)
        toolbar.addAction(self.insecure_action)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nom", "Statut", "Info"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.tree)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.detail_title = QLabel("Selectionnez un test step pour voir le detail.")
        self.detail_title.setStyleSheet("font-weight: 600; padding: 4px;")
        right_layout.addWidget(self.detail_title)

        self.tabs = QTabWidget()
        self.request_view = QTextEdit(readOnly=True)
        self.response_view = QTextEdit(readOnly=True)
        self.assertions_table = QTableWidget(0, 5)
        self.assertions_table.setHorizontalHeaderLabels(["Assertion", "Type", "Statut", "Attendu", "Recu"])
        self.assertions_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.assertions_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.assertions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.tabs.addTab(self.request_view, "Requete")
        self.tabs.addTab(self.response_view, "Reponse")
        self.tabs.addTab(self.assertions_table, "Assertions")
        right_layout.addWidget(self.tabs)

        splitter.addWidget(right)
        splitter.setSizes([420, 780])

        self.setCentralWidget(splitter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar = QStatusBar()
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ouvrez un fichier soapui-project.xml pour commencer.")

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
        self.status_bar.showMessage("Echec de l'execution.")
        QMessageBox.critical(self, "Erreur d'execution", message)

    # ---------- Detail panel ----------
    def _on_selection_changed(self, current, previous):
        if current is None:
            return
        coords = current.data(0, Qt.ItemDataRole.UserRole)
        if coords is None:
            self.detail_title.setText(current.text(0))
            self.request_view.setPlainText("")
            self.response_view.setPlainText("")
            self.assertions_table.setRowCount(0)
            return
        self._show_step_detail(coords)

    def _show_step_detail(self, coords):
        si, ci, sti = coords
        step = self.project.test_suites[si].test_cases[ci].test_steps[sti]
        result = self._step_results.get(coords)

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
