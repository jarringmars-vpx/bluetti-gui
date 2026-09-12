from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QByteArray, Signal, QMimeData, QPoint
from PySide6.QtGui import QPixmap, QAction, QPainter, QDrag
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QPushButton,
    QComboBox,
    QProgressBar,
    QSizePolicy,
    QDialog,
)

from backends.community_backend import CommunityBackend
from gui.widgets.device_visual import DeviceVisualWidget, DeviceVisualState
from services.runtime_estimator import RuntimeEstimator
from services.settings_service import SettingsService
from gui.settings_window import SettingsWindow
from gui.device_setup_wizard import DeviceSetupWizard
from devices.definitions.EL30V2 import (
    CAPACITY_WH as EL30V2_CAPACITY_WH,
    VISUAL_PROFILE as EL30V2_VISUAL_PROFILE,
)


PANEL_ACCENT = "#62B6DF"


def load_tinted_svg(path: str, color: str, size: int = 22) -> QPixmap:
    try:
        svg_text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return QPixmap()

    svg_text = svg_text.replace("#dce5ee", color)
    svg_text = svg_text.replace("#DCE5EE", color)

    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    if not renderer.isValid():
        return QPixmap()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return pixmap


def format_optional(value, decimals: int, unit: str) -> str:
    if value is None:
        return "--"

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"

    return f"{number:.{decimals}f} {unit}"


class MetricRow(QWidget):
    def __init__(self, label: str, value: str = "--", parent=None):
        super().__init__(parent)
        self.setObjectName("metricRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        name = QLabel(label)
        name.setObjectName("metricRowLabel")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricRowValue")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(name)
        layout.addStretch()
        layout.addWidget(self.value_label)

    def set_value(self, value: str):
        self.value_label.setText(value)


class InfoGroup(QFrame):
    panel_dropped = Signal(str, str)

    def __init__(self, title: str, icon_path: str | None = None, parent=None, panel_key: str = ""):
        super().__init__(parent)
        self.setObjectName("infoGroup")
        self.panel_key = panel_key
        self._drag_start = QPoint()
        self.setAcceptDrops(bool(panel_key))

        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(16, 14, 16, 14)
        self.layout_box.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        icon_label = QLabel()
        icon_label.setObjectName("groupIcon")
        icon_label.setFixedSize(22, 22)

        if icon_path:
            pixmap = load_tinted_svg(icon_path, PANEL_ACCENT, 22)
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap)

        title_label = QLabel(title)
        title_label.setObjectName("groupTitle")

        title_row.addWidget(icon_label)
        title_row.addWidget(title_label)
        title_row.addStretch()

        self.layout_box.addLayout(title_row)
        self.layout_box.addSpacing(16)

    def mousePressEvent(self, event):
        if self.panel_key and event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.panel_key or not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 10:
            return super().mouseMoveEvent(event)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-bluetti-panel", self.panel_key.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if self.panel_key and event.mimeData().hasFormat("application/x-bluetti-panel"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if not self.panel_key or not event.mimeData().hasFormat("application/x-bluetti-panel"):
            return super().dropEvent(event)
        source = bytes(event.mimeData().data("application/x-bluetti-panel")).decode("utf-8", "ignore")
        if source and source != self.panel_key:
            self.panel_dropped.emit(source, self.panel_key)
        event.acceptProposedAction()



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings_service = SettingsService()
        self.app_settings = self.settings_service.load()
        self.runtime_estimator = RuntimeEstimator()
        self.backend = self._create_backend()

        self.setWindowTitle("BLUETTI Monitor")
        self.resize(1220, 780)

        self._build_menu()
        self._build_ui()
        self._apply_styles()

        self._update_control_enabled_state(False)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

        self.refresh()
        QTimer.singleShot(300, self._maybe_run_first_setup)

    def _diagnostic_config(self):
        return {
            "enabled": self.app_settings.diagnostics_enabled,
            "categories": dict(self.app_settings.diagnostic_categories),
            "to_console": self.app_settings.diagnostics_to_console,
            "to_file": self.app_settings.diagnostics_to_file,
            "log_directory": self.app_settings.diagnostics_log_directory,
            "message_format": self.app_settings.diagnostic_message_format,
            "registers_per_group": self.app_settings.diagnostic_registers_per_group,
        }

    def _create_backend(self):
        address = self.app_settings.device_address.strip() or None
        should_start = bool(address and self.app_settings.auto_connect)
        return CommunityBackend(
            model=self.app_settings.device_model or "EL30V2",
            address=address,
            device_name=self.app_settings.device_name,
            auto_start=should_start,
            auto_reconnect=self.app_settings.auto_reconnect,
            diagnostic_config=self._diagnostic_config(),
        )

    def _replace_backend(self):
        old = getattr(self, "backend", None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.backend = self._create_backend()
        self._update_control_enabled_state(False)

    def _maybe_run_first_setup(self):
        if self.app_settings.setup_complete and self.app_settings.device_address:
            return
        self._run_device_setup_wizard(first_run=True)

    def _run_device_setup_wizard(self, first_run=False):
        wizard = DeviceSetupWizard(self)
        if first_run:
            wizard.setWindowTitle("Welcome — BLUETTI Device Setup")
        if wizard.exec() != QDialog.Accepted:
            return
        device = wizard.selected_device()
        if not device:
            return
        self.app_settings = self.settings_service.mark_device_configured(
            model=device.get("model") or "EL30V2",
            name=device.get("name") or "",
            address=device.get("address") or "",
            backend="community",
        )
        self._replace_backend()
        self.refresh()

    def closeEvent(self, event):
        try:
            close = getattr(self.backend, "close", None)
            if callable(close):
                close()
        finally:
            super().closeEvent(event)

    def _icon(self, name: str) -> str:
        return f"Images/Icons/{name}.svg"

    def _build_menu(self):
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self._open_settings)

        settings_menu = self.menuBar().addMenu("Settings")
        settings_menu.addAction(settings_action)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(18)

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        app_title = QLabel("BLUETTI Monitor")
        app_title.setObjectName("appTitle")

        self.model_label = QLabel("--")
        self.model_label.setObjectName("modelLabel")

        title_box.addWidget(app_title)
        title_box.addWidget(self.model_label)

        self.fault_label = QLabel("● No Faults")
        self.fault_label.setObjectName("faultLabel")
        self.fault_label.setProperty("fault", False)

        self.connection_label = QLabel("● Disconnected")
        self.connection_label.setObjectName("connectionLabel")

        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(self.fault_label)
        header.addSpacing(18)
        header.addWidget(self.connection_label)

        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(18)

        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        self.image_label = DeviceVisualWidget()
        self.image_label.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

        self.image_label.dc_output_requested.connect(
            self._set_dc_output_from_image
        )
        self.image_label.ac_output_requested.connect(
            self._set_ac_output_from_image
        )

        soc_caption = QLabel("Battery State of Charge")
        soc_caption.setObjectName("sectionLabel")

        self.soc_value = QLabel("--%")
        self.soc_value.setAlignment(Qt.AlignCenter)
        self.soc_value.setObjectName("socValue")

        self.soc_bar = QProgressBar()
        self.soc_bar.setRange(0, 100)
        self.soc_bar.setTextVisible(False)
        self.soc_bar.setFixedHeight(18)

        runtime_caption = QLabel("Time Remaining")
        runtime_caption.setAlignment(Qt.AlignCenter)
        runtime_caption.setObjectName("sectionLabel")

        self.runtime_value = QLabel("--")
        self.runtime_value.setAlignment(Qt.AlignCenter)
        self.runtime_value.setObjectName("runtimeValue")

        left_layout.addWidget(self.image_label, 1)
        left_layout.addWidget(soc_caption)
        left_layout.addWidget(self.soc_value)
        left_layout.addWidget(self.soc_bar)
        left_layout.addSpacing(4)
        left_layout.addWidget(runtime_caption)
        left_layout.addWidget(self.runtime_value)

        content.addWidget(left, 4)

        right = QFrame()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(16)

        top_grid = QGridLayout()
        top_grid.setHorizontalSpacing(14)
        top_grid.setVerticalSpacing(14)

        ac_group = InfoGroup("AC", self._icon("ac"), panel_key="ac")
        self.ac_button = QPushButton("AC OUTPUT")
        self.ac_button.setCheckable(True)
        self.ac_button.setObjectName("stateButton")
        self.ac_button.clicked.connect(self._set_ac_output)

        self.ac_input_row = MetricRow("Input")
        self.ac_output_row = MetricRow("Output")

        ac_group.layout_box.addWidget(self.ac_button)
        ac_group.layout_box.addWidget(self.ac_input_row)
        ac_group.layout_box.addWidget(self.ac_output_row)
        ac_group.layout_box.addStretch()

        dc_group = InfoGroup("DC", self._icon("dc"), panel_key="dc")
        self.dc_button = QPushButton("DC OUTPUT")
        self.dc_button.setCheckable(True)
        self.dc_button.setObjectName("stateButton")
        self.dc_button.clicked.connect(self._set_dc_output)

        self.dc_input_row = MetricRow("Input")
        self.dc_output_row = MetricRow("Output")

        dc_group.layout_box.addWidget(self.dc_button)
        dc_group.layout_box.addWidget(self.dc_input_row)
        dc_group.layout_box.addWidget(self.dc_output_row)
        dc_group.layout_box.addStretch()

        battery_group = InfoGroup("Battery", self._icon("battery"), panel_key="battery")
        self.battery_voltage_row = MetricRow("Voltage")
        self.battery_current_row = MetricRow("Current")
        self.battery_flow_row = MetricRow("State")
        self.lifetime_energy_row = MetricRow("PV Generation")

        battery_group.layout_box.addWidget(self.battery_voltage_row)
        battery_group.layout_box.addWidget(self.battery_current_row)
        battery_group.layout_box.addWidget(self.battery_flow_row)
        battery_group.layout_box.addWidget(self.lifetime_energy_row)
        battery_group.layout_box.addStretch()

        thermal_group = InfoGroup(
            "Temperature",
            self._icon("temperature"),
            panel_key="temperature",
        )
        self.temperature_value = QLabel("--")
        self.temperature_value.setObjectName("secondaryValue")
        self.fan_state_row = MetricRow("Fan")
        thermal_group.layout_box.addWidget(self.temperature_value)
        thermal_group.layout_box.addWidget(self.fan_state_row)
        thermal_group.layout_box.addStretch()

        charging_group = InfoGroup(
            "Charging Mode",
            self._icon("charging_mode"),
            panel_key="charging_mode",
        )
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Standard", "Silent", "Turbo"])
        self.mode_combo.currentTextChanged.connect(self._set_mode)
        charging_group.layout_box.addWidget(self.mode_combo)
        charging_group.layout_box.addStretch()

        self.dashboard_grid = top_grid
        self.panel_widgets = {
            "ac": ac_group,
            "dc": dc_group,
            "battery": battery_group,
            "temperature": thermal_group,
            "charging_mode": charging_group,
        }
        for panel in self.panel_widgets.values():
            panel.panel_dropped.connect(self._panel_dropped)

        top_grid.setColumnStretch(0, 1)
        top_grid.setColumnStretch(1, 1)
        top_grid.setColumnStretch(2, 1)
        right_layout.addLayout(top_grid)
        right_layout.addStretch()
        self._apply_panel_order()

        content.addWidget(right, 6)
        root.addLayout(content, 1)

        self.footer = QLabel("Starting Community BLE backend...")
        self.footer.setObjectName("footer")
        root.addWidget(self.footer)

    def _apply_panel_order(self):
        if not hasattr(self, "dashboard_grid"):
            return
        while self.dashboard_grid.count():
            item = self.dashboard_grid.takeAt(0)
        order = [key for key in self.app_settings.panel_order if key in self.panel_widgets]
        for key in self.panel_widgets:
            if key not in order:
                order.append(key)
        for index, key in enumerate(order):
            row, col = divmod(index, 3)
            self.dashboard_grid.addWidget(self.panel_widgets[key], row, col)

    def _panel_dropped(self, source_key: str, target_key: str):
        order = list(self.app_settings.panel_order)
        if source_key not in order or target_key not in order:
            return
        a, b = order.index(source_key), order.index(target_key)
        order[a], order[b] = order[b], order[a]
        self.app_settings.panel_order = order
        self.settings_service.save(self.app_settings)
        self._apply_panel_order()

    def _open_settings(self):
        dialog = SettingsWindow(self.settings_service, self.backend, self)
        dialog.settings_changed.connect(self._settings_changed)
        dialog.device_change_requested.connect(self._device_change_requested)
        dialog.exec()

    def _settings_changed(self, settings):
        old_address = self.app_settings.device_address
        old_model = self.app_settings.device_model
        self.app_settings = settings
        configure = getattr(self.backend, "configure_diagnostics", None)
        if callable(configure):
            configure(self._diagnostic_config())
        if old_address != settings.device_address or old_model != settings.device_model:
            self._replace_backend()
        self._apply_panel_order()
        self.refresh()

    def _device_change_requested(self, device):
        if device.get("forget"):
            self.app_settings = self.settings_service.load()
            self._replace_backend()
            return
        self.app_settings = self.settings_service.mark_device_configured(
            model=device.get("model") or "EL30V2",
            name=device.get("name") or "",
            address=device.get("address") or "",
            backend="community",
        )
        self._replace_backend()

    def _update_control_enabled_state(self, connected: bool):
        ac_enabled = bool(connected and getattr(
            self.backend, "supports_ac_output_writes",
            getattr(self.backend, "supports_writes", False),
        ))
        dc_enabled = bool(connected and getattr(
            self.backend, "supports_dc_output_writes",
            getattr(self.backend, "supports_writes", False),
        ))
        mode_enabled = bool(connected and getattr(
            self.backend, "supports_charging_mode_writes", False
        ))
        self.ac_button.setEnabled(ac_enabled)
        self.dc_button.setEnabled(dc_enabled)
        self.mode_combo.setEnabled(mode_enabled)
        self.image_label.set_controls_enabled(ac_enabled or dc_enabled)

    def _format_runtime(self, minutes):
        if self.app_settings.runtime_display_units != "hours":
            return self.runtime_estimator.format_minutes(minutes)
        if minutes is None:
            return "--"
        try:
            hours = max(0.0, float(minutes) / 60.0)
        except (TypeError, ValueError):
            return "--"
        text = f"{hours:.2f}".rstrip("0").rstrip(".")
        if text.startswith("0."):
            text = text[1:]
        return f"{text}H"

    def _set_ac_output(self, checked: bool):
        self.backend.set_ac_output(checked)

    def _set_dc_output(self, checked: bool):
        self.backend.set_dc_output(checked)

    def _set_ac_output_from_image(self, enabled: bool):
        self.backend.set_ac_output(enabled)
        self.refresh()

    def _set_dc_output_from_image(self, enabled: bool):
        self.backend.set_dc_output(enabled)
        self.refresh()

    def _set_mode(self, mode: str):
        self.backend.set_charging_mode(mode)

    def _load_model_image(self, model: str):
        profile = EL30V2_VISUAL_PROFILE if model == "EL30V2" else None
        self.image_label.set_model(model, profile)

    def _capacity_for_model(self, model: str) -> float:
        if model == "EL30V2":
            return EL30V2_CAPACITY_WH
        return 0.0

    def _format_temperature(self, celsius):
        if celsius is None:
            return "--"
        c = float(celsius)
        f = c * 9.0 / 5.0 + 32.0
        units = self.app_settings.temperature_units
        if units == "celsius":
            return f"{c:.1f} °C"
        if units == "both":
            return f"{f:.1f} °F / {c:.1f} °C"
        return f"{f:.1f} °F"

    def refresh(self):
        t = self.backend.get_telemetry()
        self.current_model = t.model

        self.model_label.setText(t.model)

        self.connection_label.setText(
            "● Connected" if t.connected else "● Disconnected"
        )
        self.connection_label.setProperty("connected", t.connected)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

        self.soc_value.setText(f"{t.soc}%" if t.connected else "--%")
        self.soc_bar.setValue(t.soc if t.connected else 0)

        total_output_watts = (
            max(0, t.ac_output_power)
            + max(0, t.dc_output_power)
        )
        total_input_watts = (
            max(0, t.ac_input_power)
            + max(0, t.dc_input_power)
        )

        if t.connected:
            self.runtime_estimator.add_output_sample(total_output_watts)

            capacity_wh = self._capacity_for_model(t.model)
            estimate = self.runtime_estimator.estimate_minutes(
                capacity_wh=capacity_wh,
                soc_percent=t.soc,
                current_output_watts=total_output_watts,
                method=self.app_settings.runtime_method,
                average_minutes=self.app_settings.average_minutes,
            )
            self.runtime_value.setText(self._format_runtime(estimate))
        else:
            self.runtime_value.setText("--")

        self.ac_input_row.set_value(
            f"{t.ac_input_power:.0f} W" if t.connected else "--"
        )
        self.ac_output_row.set_value(
            f"{t.ac_output_power:.0f} W" if t.connected else "--"
        )

        self.dc_input_row.set_value(
            f"{t.dc_input_power:.0f} W" if t.connected else "--"
        )
        self.dc_output_row.set_value(
            f"{t.dc_output_power:.0f} W" if t.connected else "--"
        )

        self.battery_voltage_row.set_value(
            format_optional(t.battery_voltage, 2, "V")
            if t.connected else "--"
        )
        self.battery_current_row.set_value(
            format_optional(t.battery_current, 1, "A")
            if t.connected else "--"
        )
        self.battery_flow_row.set_value(
            t.battery_flow if t.connected else "--"
        )
        self.lifetime_energy_row.set_value(
            f"{t.lifetime_energy_kwh:.1f} kWh"
            if t.connected and t.lifetime_energy_kwh is not None else "--"
        )

        self.temperature_value.setText(
            self._format_temperature(t.temperature_c) if t.connected else "--"
        )
        self.fan_state_row.set_value(t.fan_state if t.connected else "--")

        self.fault_label.setText(
            "⚠ Fault Active" if t.connected and t.fault_active
            else ("● No Faults" if t.connected else "● Fault Status Unknown")
        )
        self.fault_label.setProperty("fault", bool(t.connected and t.fault_active))
        self.fault_label.setProperty("known", bool(t.connected))
        self.fault_label.style().unpolish(self.fault_label)
        self.fault_label.style().polish(self.fault_label)

        self._update_control_enabled_state(t.connected)

        self.ac_button.blockSignals(True)
        self.ac_button.setChecked(t.ac_output_enabled)
        self.ac_button.setText(
            "AC OUTPUT ON"
            if t.ac_output_enabled
            else "AC OUTPUT OFF"
        )
        self.ac_button.blockSignals(False)

        self.dc_button.blockSignals(True)
        self.dc_button.setChecked(t.dc_output_enabled)
        self.dc_button.setText(
            "DC OUTPUT ON"
            if t.dc_output_enabled
            else "DC OUTPUT OFF"
        )
        self.dc_button.blockSignals(False)

        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentText(t.charging_mode)
        self.mode_combo.blockSignals(False)

        self._load_model_image(t.model)

        self.image_label.set_state(
            DeviceVisualState(
                soc=t.soc if t.connected else 0,
                input_watts=int(round(total_input_watts))
                if t.connected else 0,
                output_watts=int(round(total_output_watts))
                if t.connected else 0,
                time_remaining=self.runtime_value.text(),
                dc_output_enabled=t.dc_output_enabled,
                ac_output_enabled=t.ac_output_enabled,
                power_enabled=t.connected,
            )
        )

        self.footer.setText(
            getattr(
                self.backend,
                "status_message",
                "Community BLE backend",
            )
        )

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: #11151a;
                color: #e9eef5;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 14px;
            }}

            QMenuBar {{
                background: #11151a;
                color: #e9eef5;
            }}

            QMenuBar::item:selected, QMenu::item:selected {{
                background: #2b3540;
            }}

            QMenu {{
                background: #181e25;
                color: #e9eef5;
                border: 1px solid #2a333d;
            }}

            #appTitle {{
                font-size: 26px;
                font-weight: 700;
            }}

            #modelLabel {{
                color: #9ba9b8;
                font-size: 16px;
            }}

            #connectionLabel {{
                font-weight: 600;
                color: #ef6a6a;
            }}

            #connectionLabel[connected="true"] {{
                color: #59d18c;
            }}

            #faultLabel {{
                font-weight: 700;
                color: #8d99a6;
            }}

            #faultLabel[known="true"] {{
                color: #59d18c;
            }}

            #faultLabel[fault="true"] {{
                color: #ff6b6b;
            }}

            #panel {{
                background: #181e25;
                border: 1px solid #2a333d;
                border-radius: 14px;
            }}

            #infoGroup {{
                background: #202731;
                border: 1px solid #2e3945;
                border-radius: 10px;
            }}

            #groupIcon {{
                background: transparent;
                border: none;
            }}

            #groupTitle {{
                background: transparent;
                font-size: 17px;
                font-weight: 700;
                color: {PANEL_ACCENT};
            }}

            #metricRow,
            #metricRowLabel,
            #metricRowValue {{
                background: transparent;
                border: none;
            }}

            #metricRowLabel {{
                color: #9ba9b8;
            }}

            #metricRowValue {{
                font-size: 17px;
                font-weight: 650;
                color: #e9eef5;
            }}

            #sectionLabel {{
                color: #c8d2dc;
                font-size: 14px;
                font-weight: 650;
            }}

            #socValue {{
                font-size: 46px;
                font-weight: 750;
            }}

            #runtimeValue {{
                font-size: 28px;
                font-weight: 700;
            }}

            #secondaryValue {{
                background: transparent;
                font-size: 24px;
                font-weight: 700;
            }}

            QProgressBar {{
                background: #252d36;
                border: none;
                border-radius: 9px;
            }}

            QProgressBar::chunk {{
                background: #52c7ff;
                border-radius: 9px;
            }}

            QPushButton#stateButton {{
                background: #2b3540;
                border: 1px solid #3b4855;
                border-radius: 8px;
                padding: 12px 16px;
                font-weight: 700;
            }}

            QPushButton#stateButton:hover {{
                background: #34404d;
            }}

            QPushButton#stateButton:checked {{
                background: #166f4b;
                border-color: #2da870;
            }}

            /*
             * Buttons are disabled whenever the connected backend does not
             * advertise the corresponding write capability. Qt's :disabled rule has higher visual
             * priority than the generic :checked rule. Give the combined
             * checked+disabled state its own ON styling so live state remains
             * visible even though clicking is disabled.
             */
            QPushButton#stateButton:checked:disabled {{
                background: #166f4b;
                color: #d9f5e7;
                border-color: #2da870;
            }}

            QPushButton#stateButton:disabled {{
                background: #252b32;
                color: #77818b;
                border-color: #303840;
            }}

            QPushButton {{
                background: #2b3540;
                border: 1px solid #3b4855;
                border-radius: 8px;
                padding: 9px 14px;
            }}

            QComboBox {{
                background: #2b3540;
                border: 1px solid #3b4855;
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 120px;
            }}

            QComboBox:disabled {{
                color: #77818b;
                background: #252b32;
            }}

            QGroupBox {{
                border: 1px solid #2e3945;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: 650;
            }}

            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}

            #footer {{
                color: #788594;
                font-size: 12px;
            }}
        """)
