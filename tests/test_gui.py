"""Tests de la fenêtre principale (IHM)."""
from soapui_tester.gui import MainWindow
from soapui_tester.parser import parse_project

SAMPLE = "sample/sample-soapui-project.xml"


def test_main_window_creation():
    window = MainWindow()
    assert window.windowTitle() == "Testeur de projets SoapUI"
    assert not window.run_action.isEnabled()


def test_populate_tree_from_loaded_project(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.project = parse_project(SAMPLE)
    window._populate_tree()

    assert window.tree.topLevelItemCount() == 1
    suite_item = window.tree.topLevelItem(0)
    assert suite_item.text(0) == "HttpBin TestSuite"
    assert suite_item.childCount() == 1
    assert len(window._runnable_coords) == 3


def test_selecting_step_shows_request_detail(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.project = parse_project(SAMPLE)
    window._populate_tree()

    step_item = window._step_items[(0, 0, 1)]
    window.tree.setCurrentItem(step_item)

    text = window.request_view.toPlainText()
    assert "POST" in text
    # avant execution, l'endpoint est affiche tel quel (${...} non resolu)
    assert "${BaseUrl}/post" in text
