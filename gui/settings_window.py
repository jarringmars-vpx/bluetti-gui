from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QButtonGroup,
    QComboBox,
    QPushButton,
    QGroupBox,
    QFormLayout,
)

from models.settings import AppSettings
from services.settings_service import SettingsService


class SettingsWindow(QDialog):
    settings_changed = Signal(object)

    def __init__(self, settings_service: SettingsService, parent=None):
        super().__init__(parent)
        self.settings_service = settings_service
        self.settings = self.settings_service.load()

        self.setWindowTitle("Settings")
        self.setMinimumWidth(430)

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        root = QVBoxLayout(self)

        runtime_group = QGroupBox("Time Remaining Calculation")
        runtime_layout = QVBoxLayout(runtime_group)

        self.instant_radio = QRadioButton("Instantaneous Load")
        self.average_radio = QRadioButton("Average Load")

        self.method_group = QButtonGroup(self)
        self.method_group.addButton(self.instant_radio)
        self.method_group.addButton(self.average_radio)

        runtime_layout.addWidget(self.instant_radio)
        runtime_layout.addWidget(self.average_radio)

        form = QFormLayout()

        self.average_combo = QComboBox()
        self.average_combo.addItems(["5", "10", "15", "30", "60"])
        form.addRow("Average Period (minutes):", self.average_combo)

        runtime_layout.addLayout(form)
        root.addWidget(runtime_group)

        note = QLabel(
            "Instantaneous Load reacts immediately to the current output.\n"
            "Average Load smooths short spikes and intermittent loads."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_button = QPushButton("Cancel")
        save_button = QPushButton("Save")

        cancel_button.clicked.connect(self.reject)
        save_button.clicked.connect(self._save)

        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)

        root.addLayout(buttons)

        self.instant_radio.toggled.connect(self._update_enabled_state)
        self.average_radio.toggled.connect(self._update_enabled_state)

    def _load_values(self):
        if self.settings.runtime_method == "instantaneous":
            self.instant_radio.setChecked(True)
        else:
            self.average_radio.setChecked(True)

        self.average_combo.setCurrentText(str(self.settings.average_minutes))
        self._update_enabled_state()

    def _update_enabled_state(self):
        self.average_combo.setEnabled(self.average_radio.isChecked())

    def _save(self):
        method = "average" if self.average_radio.isChecked() else "instantaneous"

        self.settings = AppSettings(
            runtime_method=method,
            average_minutes=int(self.average_combo.currentText()),
        )

        self.settings_service.save(self.settings)
        self.settings_changed.emit(self.settings)
        self.accept()
