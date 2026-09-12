from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QComboBox, QPushButton, QGroupBox, QFormLayout, QTabWidget, QWidget,
    QCheckBox, QLineEdit, QFileDialog, QMessageBox, QScrollArea
)

from models.settings import AppSettings, DEFAULT_PANEL_ORDER
from services.settings_service import SettingsService
from gui.device_setup_wizard import DeviceSetupWizard


CATEGORY_LABELS = {
    "control_state": "AC/DC output-state polling",
    "power_flow": "Power-flow polling",
    "battery_summary": "Battery summary polling",
    "temperature": "Temperature polling",
    "settings": "Charging-mode polling",
    "lifetime_energy": "Lifetime energy polling",
    "fault_status": "Fault/status polling",
    "retry_timeout": "Retries / timeouts",
    "unexpected": "Unexpected / mismatched responses",
    "unsolicited": "Unsolicited / out-of-band messages",
    "connection": "Connection / device-info events",
}

PANEL_LABELS = {
    "ac": "AC",
    "dc": "DC",
    "battery": "Battery",
    "temperature": "Temperature",
    "charging_mode": "Charging Mode",
}


class SettingsWindow(QDialog):
    settings_changed = Signal(object)
    device_change_requested = Signal(dict)

    def __init__(self, settings_service: SettingsService, backend=None, parent=None):
        super().__init__(parent)
        self.settings_service = settings_service
        self.backend = backend
        self.settings = self.settings_service.load()
        self._panel_order = list(self.settings.panel_order)

        self.setWindowTitle("BLUETTI Monitor Settings")
        self.setMinimumSize(760, 620)
        self._apply_settings_style()
        self._build_ui()
        self._load_values()
        self._refresh_device_info()

    def _apply_settings_style(self):
        # Explicit colors avoid platform/native-theme combinations that can
        # otherwise produce light text on a light tab or popup background.
        self.setStyleSheet(
            """
            QDialog {
                background-color: #121820;
                color: #dce5ee;
            }
            QTabWidget::pane {
                border: 1px solid #44515f;
                border-radius: 5px;
                background: #121820;
                top: -1px;
            }
            QTabBar::tab {
                background: #26323d;
                color: #dce5ee;
                border: 1px solid #44515f;
                border-bottom: none;
                padding: 9px 20px;
                min-width: 92px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background: #287fb0;
                color: #ffffff;
                border-color: #62b6df;
            }
            QTabBar::tab:hover:!selected {
                background: #34495a;
                color: #ffffff;
                border-color: #62b6df;
            }
            QGroupBox {
                border: 1px solid #44515f;
                border-radius: 5px;
                margin-top: 13px;
                padding-top: 11px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #62b6df;
            }
            QLabel, QCheckBox, QRadioButton {
                color: #dce5ee;
            }
            QLineEdit, QComboBox {
                background-color: #1d2731;
                color: #f2f6fa;
                border: 1px solid #516273;
                border-radius: 4px;
                padding: 5px 8px;
                min-height: 22px;
            }
            QComboBox:hover, QLineEdit:focus, QComboBox:focus {
                border-color: #62b6df;
            }
            QComboBox QAbstractItemView {
                background-color: #1d2731;
                color: #f2f6fa;
                border: 1px solid #62b6df;
                selection-background-color: #287fb0;
                selection-color: #ffffff;
                outline: 0;
            }
            QComboBox QAbstractItemView::item {
                min-height: 28px;
                padding: 4px 8px;
            }
            QPushButton {
                background-color: #2a3641;
                color: #f2f6fa;
                border: 1px solid #526476;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #344b5d;
                border-color: #62b6df;
            }
            QPushButton:pressed {
                background-color: #287fb0;
                color: #ffffff;
            }
            QPushButton:disabled, QComboBox:disabled, QLineEdit:disabled {
                color: #8996a3;
                background-color: #202831;
                border-color: #394550;
            }
            """
        )

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_device_tab(), "Device")
        self.tabs.addTab(self._build_display_tab(), "Display")
        self.tabs.addTab(self._build_dashboard_tab(), "Dashboard")
        self.tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = QPushButton("Cancel")
        save_button = QPushButton("Save")
        cancel_button.clicked.connect(self.reject)
        save_button.clicked.connect(self._save)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)

    def _build_device_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        info_group = QGroupBox("Current Device")
        form = QFormLayout(info_group)
        # Leave enough space below the last row so its text never sits on
        # top of the QGroupBox bottom border.
        form.setContentsMargins(10, 8, 10, 16)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(16)
        self.device_fields = {}
        for key, label in [
            ("model", "Model:"),
            ("device_name", "BLE Device Name:"),
            ("ble_address", "BLE Address:"),
            ("device_serial", "Device Serial Number:"),
            ("communication_board_serial", "Communication Board Serial Number:"),
            ("firmware_version", "Firmware Version:"),
            ("protocol", "Protocol:"),
            ("backend", "Backend:"),
            ("authenticated", "Authentication:"),
        ]:
            value = QLabel("Not available")
            value.setMinimumHeight(24)
            value.setContentsMargins(0, 2, 0, 3)
            value.setTextInteractionFlags(value.textInteractionFlags() | Qt.TextSelectableByMouse)
            self.device_fields[key] = value
            form.addRow(label, value)
        layout.addWidget(info_group)

        wifi_group = QGroupBox("Wi-Fi / Network")
        wifi_form = QFormLayout(wifi_group)
        self.wifi_fields = {}
        for key, label in [
            ("wifi_status", "Status:"),
            ("wifi_ssid", "Network Name (SSID):"),
            ("wifi_ip", "IP Address:"),
            ("wifi_gateway", "Gateway:"),
            ("wifi_subnet_mask", "Subnet Mask:"),
            ("wifi_rssi", "Signal Strength:"),
            ("wifi_mac", "Wi-Fi MAC:"),
            ("ble_mac", "BLE MAC:"),
        ]:
            value = QLabel("Not available")
            self.wifi_fields[key] = value
            wifi_form.addRow(label, value)
        layout.addWidget(wifi_group)

        connection_group = QGroupBox("Connection")
        connection_form = QFormLayout(connection_group)
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Community", "community")
        self.auto_connect_check = QCheckBox("Connect to the saved device when the application starts")
        self.auto_reconnect_check = QCheckBox("Automatically reconnect after an unexpected connection loss")
        connection_form.addRow("Preferred backend:", self.backend_combo)
        connection_form.addRow("", self.auto_connect_check)
        connection_form.addRow("", self.auto_reconnect_check)
        layout.addWidget(connection_group)

        row = QHBoxLayout()
        refresh_button = QPushButton("Refresh Displayed Information")
        refresh_button.clicked.connect(self._refresh_device_info)
        setup_button = QPushButton("Find / Configure Another BLUETTI Device...")
        setup_button.setStyleSheet(
            "QPushButton { background:#287fb0; color:white; border:1px solid #62b6df; font-weight:600; }"
            "QPushButton:hover { background:#3194c8; }"
        )
        setup_button.clicked.connect(self._run_device_wizard)
        forget_button = QPushButton("Forget Saved Device")
        forget_button.clicked.connect(self._forget_device)
        row.addWidget(refresh_button)
        row.addWidget(setup_button)
        row.addWidget(forget_button)
        layout.addLayout(row)
        layout.addStretch()
        return page

    def _build_display_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)

        temp_group = QGroupBox("Temperature Display")
        temp_form = QFormLayout(temp_group)
        self.temperature_combo = QComboBox()
        self.temperature_combo.addItem("Fahrenheit (°F)", "fahrenheit")
        self.temperature_combo.addItem("Celsius (°C)", "celsius")
        self.temperature_combo.addItem("Both (°F / °C)", "both")
        temp_form.addRow("Units:", self.temperature_combo)
        root.addWidget(temp_group)

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
        self.runtime_units_combo = QComboBox()
        self.runtime_units_combo.addItem("Minutes", "minutes")
        self.runtime_units_combo.addItem("Hours", "hours")
        form.addRow("Display Time Remaining In:", self.runtime_units_combo)
        runtime_layout.addLayout(form)
        root.addWidget(runtime_group)
        self.instant_radio.toggled.connect(self._update_enabled_state)
        self.average_radio.toggled.connect(self._update_enabled_state)
        root.addStretch()
        return page

    def _build_dashboard_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)
        note = QLabel(
            "The right-side dashboard panels can be dragged directly on the main screen. "
            "Their order is saved per application profile. You can also reset the default layout here."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.panel_order_label = QLabel()
        self.panel_order_label.setWordWrap(True)
        root.addWidget(self.panel_order_label)
        reset_button = QPushButton("Reset Dashboard Layout")
        reset_button.clicked.connect(self._reset_panel_order)
        root.addWidget(reset_button)
        root.addStretch()
        return page

    def _build_diagnostics_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)

        self.diagnostics_enabled_check = QCheckBox("Enable diagnostic message capture")
        root.addWidget(self.diagnostics_enabled_check)

        categories_group = QGroupBox("Message Categories")
        cat_layout = QVBoxLayout(categories_group)
        self.category_checks = {}
        for key, label in CATEGORY_LABELS.items():
            check = QCheckBox(label)
            self.category_checks[key] = check
            cat_layout.addWidget(check)
        root.addWidget(categories_group)

        output_group = QGroupBox("Output")
        output_form = QFormLayout(output_group)
        self.console_check = QCheckBox("Show selected messages in the console")
        self.file_check = QCheckBox("Write selected messages to a log file")
        self.log_directory_edit = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_log_directory)
        path_row = QHBoxLayout()
        path_row.addWidget(self.log_directory_edit, 1)
        path_row.addWidget(browse)
        output_form.addRow("", self.console_check)
        output_form.addRow("", self.file_check)
        output_form.addRow("Log directory:", path_row)

        self.message_format_combo = QComboBox()
        self.message_format_combo.addItem("Raw protocol message", "raw")
        self.message_format_combo.addItem("Register view (hex / decimal / ASCII)", "registers")
        self.message_format_combo.addItem("Raw + register view", "both")
        output_form.addRow("Unexpected / autonomous message format:", self.message_format_combo)

        self.register_group_size_combo = QComboBox()
        for value in (8, 10, 12, 16):
            self.register_group_size_combo.addItem(str(value), value)
        output_form.addRow("Registers per group:", self.register_group_size_combo)

        root.addWidget(output_group)

        note = QLabel(
            "Unexpected/mismatched responses are packets received while a request is active but do not "
            "match that request. Unsolicited/out-of-band messages are complete packets received when no "
            "request is waiting. Log files never include the stored Wi-Fi password."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch()
        return page

    def _load_values(self):
        if self.settings.runtime_method == "instantaneous":
            self.instant_radio.setChecked(True)
        else:
            self.average_radio.setChecked(True)
        self.average_combo.setCurrentText(str(self.settings.average_minutes))
        idx = self.temperature_combo.findData(self.settings.temperature_units)
        self.temperature_combo.setCurrentIndex(max(0, idx))
        idx = self.runtime_units_combo.findData(self.settings.runtime_display_units)
        self.runtime_units_combo.setCurrentIndex(max(0, idx))

        idx = self.backend_combo.findData(self.settings.preferred_backend)
        self.backend_combo.setCurrentIndex(max(0, idx))
        self.auto_connect_check.setChecked(self.settings.auto_connect)
        self.auto_reconnect_check.setChecked(self.settings.auto_reconnect)

        self.diagnostics_enabled_check.setChecked(self.settings.diagnostics_enabled)
        for key, check in self.category_checks.items():
            check.setChecked(bool(self.settings.diagnostic_categories.get(key, False)))
        self.console_check.setChecked(self.settings.diagnostics_to_console)
        self.file_check.setChecked(self.settings.diagnostics_to_file)
        self.log_directory_edit.setText(self.settings.diagnostics_log_directory or "logs")
        idx = self.message_format_combo.findData(self.settings.diagnostic_message_format)
        self.message_format_combo.setCurrentIndex(max(0, idx))
        idx = self.register_group_size_combo.findData(int(self.settings.diagnostic_registers_per_group))
        self.register_group_size_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._update_panel_order_label()
        self._update_enabled_state()

    def _refresh_device_info(self):
        if self.backend is None or not hasattr(self.backend, "get_device_info"):
            return
        try:
            info = self.backend.get_device_info()
        except Exception:
            return
        data = info.__dict__ if hasattr(info, "__dict__") else {}
        for key, label in self.device_fields.items():
            value = data.get(key)
            if key == "authenticated":
                text = "Encrypted / Authenticated" if value else "Not authenticated"
            else:
                text = str(value) if value not in (None, "") else "Not available"
            label.setText(text)
        for key, label in self.wifi_fields.items():
            value = data.get(key)
            if key == "wifi_rssi" and isinstance(value, (int, float)):
                quality = self._rssi_quality(int(value))
                text = f"{quality} ({int(value)} dBm)"
            else:
                text = str(value) if value not in (None, "") else "Not available"
            label.setText(text)

    @staticmethod
    def _rssi_quality(rssi):
        if rssi >= -50:
            return "Excellent"
        if rssi >= -60:
            return "Very good"
        if rssi >= -70:
            return "Good"
        if rssi >= -80:
            return "Fair"
        return "Weak"

    def _run_device_wizard(self):
        wizard = DeviceSetupWizard(self)
        if wizard.exec() == QDialog.Accepted:
            device = wizard.selected_device()
            if device:
                self.device_change_requested.emit(device)
                self.accept()

    def _forget_device(self):
        answer = QMessageBox.question(
            self,
            "Forget Saved Device",
            "Forget the saved BLUETTI device? The Device Setup Wizard will run the next time the application starts.",
        )
        if answer == QMessageBox.Yes:
            self.settings = self.settings_service.forget_device()
            self.device_change_requested.emit({"forget": True})
            self.accept()

    def _browse_log_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Choose Diagnostics Log Directory", self.log_directory_edit.text() or "."
        )
        if directory:
            self.log_directory_edit.setText(directory)

    def _reset_panel_order(self):
        self._panel_order = list(DEFAULT_PANEL_ORDER)
        self._update_panel_order_label()

    def _update_panel_order_label(self):
        labels = [PANEL_LABELS.get(key, key) for key in self._panel_order]
        self.panel_order_label.setText("Current order: " + " → ".join(labels))

    def _update_enabled_state(self):
        self.average_combo.setEnabled(self.average_radio.isChecked())

    def _save(self):
        self.settings.runtime_method = "average" if self.average_radio.isChecked() else "instantaneous"
        self.settings.average_minutes = int(self.average_combo.currentText())
        self.settings.temperature_units = self.temperature_combo.currentData()
        self.settings.runtime_display_units = self.runtime_units_combo.currentData()
        self.settings.preferred_backend = self.backend_combo.currentData()
        self.settings.auto_connect = self.auto_connect_check.isChecked()
        self.settings.auto_reconnect = self.auto_reconnect_check.isChecked()
        self.settings.panel_order = list(self._panel_order)
        self.settings.diagnostics_enabled = self.diagnostics_enabled_check.isChecked()
        self.settings.diagnostic_categories = {
            key: check.isChecked() for key, check in self.category_checks.items()
        }
        self.settings.diagnostics_to_console = self.console_check.isChecked()
        self.settings.diagnostics_to_file = self.file_check.isChecked()
        self.settings.diagnostics_log_directory = self.log_directory_edit.text().strip() or "logs"
        self.settings.diagnostic_message_format = self.message_format_combo.currentData()
        self.settings.diagnostic_registers_per_group = int(self.register_group_size_combo.currentData())
        self.settings_service.save(self.settings)
        self.settings_changed.emit(self.settings)
        self.accept()
