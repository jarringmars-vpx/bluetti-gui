from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QByteArray
from PySide6.QtGui import QPixmap, QAction, QPainter
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
)

from backends.mock_backend import MockBackend
from gui.widgets.device_visual import DeviceVisualWidget, DeviceVisualState
from services.runtime_estimator import RuntimeEstimator
from services.settings_service import SettingsService
from gui.settings_window import SettingsWindow
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
    def __init__(self, title: str, icon_path: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("infoGroup")

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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.backend = MockBackend()
        self.settings_service = SettingsService()
        self.app_settings = self.settings_service.load()
        self.runtime_estimator = RuntimeEstimator()

        self.setWindowTitle("BLUETTI Monitor")
        self.resize(1220, 780)

        self._build_menu()
        self._build_ui()
        self._apply_styles()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

        self.refresh()

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

        self.connection_label = QLabel("● Connected")
        self.connection_label.setObjectName("connectionLabel")

        header.addLayout(title_box)
        header.addStretch()
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

        # The photographed AC/DC buttons invoke the same backend controls as
        # the regular dashboard buttons.
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

        ac_group = InfoGroup("AC", self._icon("ac"))
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

        dc_group = InfoGroup("DC", self._icon("dc"))
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

        battery_group = InfoGroup("Battery", self._icon("battery"))
        self.battery_voltage_row = MetricRow("Voltage")
        self.battery_current_row = MetricRow("Current")
        self.battery_flow_row = MetricRow("State")

        battery_group.layout_box.addWidget(self.battery_voltage_row)
        battery_group.layout_box.addWidget(self.battery_current_row)
        battery_group.layout_box.addWidget(self.battery_flow_row)
        battery_group.layout_box.addStretch()

        top_grid.addWidget(ac_group, 0, 0)
        top_grid.addWidget(dc_group, 0, 1)
        top_grid.addWidget(battery_group, 0, 2)

        top_grid.setColumnStretch(0, 1)
        top_grid.setColumnStretch(1, 1)
        top_grid.setColumnStretch(2, 1)

        right_layout.addLayout(top_grid)

        secondary = QHBoxLayout()
        secondary.setSpacing(14)

        thermal_group = InfoGroup(
            "Temperature",
            self._icon("temperature"),
        )
        self.temperature_value = QLabel("-- °C")
        self.temperature_value.setObjectName("secondaryValue")
        thermal_group.layout_box.addWidget(self.temperature_value)
        thermal_group.layout_box.addStretch()

        charging_group = InfoGroup(
            "Charging Mode",
            self._icon("charging_mode"),
        )
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Standard", "Silent", "Turbo"])
        self.mode_combo.currentTextChanged.connect(self._set_mode)
        charging_group.layout_box.addWidget(self.mode_combo)
        charging_group.layout_box.addStretch()

        secondary.addWidget(thermal_group, 1)
        secondary.addWidget(charging_group, 1)

        right_layout.addLayout(secondary)
        right_layout.addStretch()

        content.addWidget(right, 6)
        root.addLayout(content, 1)

        self.footer = QLabel(
            "Mock backend active — BLE connection will be added next."
        )
        self.footer.setObjectName("footer")
        root.addWidget(self.footer)

    def _open_settings(self):
        dialog = SettingsWindow(self.settings_service, self)
        dialog.settings_changed.connect(self._settings_changed)
        dialog.exec()

    def _settings_changed(self, settings):
        self.app_settings = settings
        self.refresh()

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

        self.soc_value.setText(f"{t.soc}%")
        self.soc_bar.setValue(t.soc)

        total_output_watts = (
            max(0, t.ac_output_power)
            + max(0, t.dc_output_power)
        )
        total_input_watts = (
            max(0, t.ac_input_power)
            + max(0, t.dc_input_power)
        )

        self.runtime_estimator.add_output_sample(total_output_watts)

        capacity_wh = self._capacity_for_model(t.model)

        estimate = self.runtime_estimator.estimate_minutes(
            capacity_wh=capacity_wh,
            soc_percent=t.soc,
            current_output_watts=total_output_watts,
            method=self.app_settings.runtime_method,
            average_minutes=self.app_settings.average_minutes,
        )

        self.runtime_value.setText(
            self.runtime_estimator.format_minutes(estimate)
        )

        self.ac_input_row.set_value(f"{t.ac_input_power} W")
        self.ac_output_row.set_value(f"{t.ac_output_power} W")

        self.dc_input_row.set_value(f"{t.dc_input_power} W")
        self.dc_output_row.set_value(f"{t.dc_output_power} W")

        self.battery_voltage_row.set_value(f"{t.battery_voltage:.2f} V")
        self.battery_current_row.set_value(f"{t.battery_current:.1f} A")
        self.battery_flow_row.set_value(t.battery_flow)

        self.temperature_value.setText(f"{t.temperature_c:.1f} °C")

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
                soc=t.soc,
                input_watts=int(round(total_input_watts)),
                output_watts=int(round(total_output_watts)),
                time_remaining=self.runtime_value.text(),
                dc_output_enabled=t.dc_output_enabled,
                ac_output_enabled=t.ac_output_enabled,
                power_enabled=t.connected,
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
