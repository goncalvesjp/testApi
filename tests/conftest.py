"""
Configuration partagée pour les tests unitaires.

Fournit une instance unique de QApplication requise par PyQt6
avant la création de tout QWidget/QDialog.
"""

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
