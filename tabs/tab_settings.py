# tabs\tab_settings.py
from PyQt6 import QtWidgets


class SettingsTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QtWidgets.QFormLayout(self)

        self.name_edit = QtWidgets.QLineEdit()
        self.save_btn = QtWidgets.QPushButton("Сохранить")

        layout.addRow("Имя:", self.name_edit)
        layout.addRow(self.save_btn)