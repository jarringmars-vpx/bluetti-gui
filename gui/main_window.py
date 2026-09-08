from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QPushButton, QComboBox, QProgressBar, QSizePolicy
)

from backends.mock_backend import MockBackend
from devices.image_resolver import resolve_model_image


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "--", parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, text: str):
        self.value_label.setText(text)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.backend = MockBackend()
        self.setWindowTitle("BLUETTI Monitor")
        self.resize(1180, 760)

        self._build_ui()
        self._apply_styles()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

        self.refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(18)

        # Header
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

        # Main content
        content = QHBoxLayout()
        content.setSpacing(18)

        # Left: image and SOC
        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(14)

        self.image_label = QLabel("No model image")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(360, 250)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setObjectName("deviceImage")

        soc_caption = QLabel("Battery State of Charge")
        soc_caption.setObjectName("sectionLabel")
        self.soc_value = QLabel("--%")
        self.soc_value.setAlignment(Qt.AlignCenter)
        self.soc_value.setObjectName("socValue")

        self.soc_bar = QProgressBar()
        self.soc_bar.setRange(0, 100)
        self.soc_bar.setTextVisible(False)
        self.soc_bar.setFixedHeight(18)

        left_layout.addWidget(self.image_label, 1)
        left_layout.addWidget(soc_caption)
        left_layout.addWidget(self.soc_value)
        left_layout.addWidget(self.soc_bar)

        content.addWidget(left, 4)

        # Right: telemetry and controls
        right = QFrame()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(16)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.cards = {
            "battery_voltage": MetricCard("Battery Voltage"),
            "battery_current": MetricCard("Battery Current"),
            "battery_flow": MetricCard("Battery Flow"),
            "temperature": MetricCard("Temperature"),
            "ac_output_power": MetricCard("AC Output"),
            "dc_output_power": MetricCard("DC Output"),
            "pv_input_power": MetricCard("PV/DC Input"),
            "ac_input_power": MetricCard("AC/Grid Input"),
        }

        positions = [
            ("battery_voltage", 0, 0),
            ("battery_current", 0, 1),
            ("battery_flow", 0, 2),
            ("temperature", 0, 3),
            ("ac_output_power", 1, 0),
            ("dc_output_power", 1, 1),
            ("pv_input_power", 1, 2),
            ("ac_input_power", 1, 3),
        ]

        for key, row, col in positions:
            grid.addWidget(self.cards[key], row, col)

        right_layout.addLayout(grid)

        controls_title = QLabel("Controls")
        controls_title.setObjectName("sectionLabel")
        right_layout.addWidget(controls_title)

        controls = QHBoxLayout()
        controls.setSpacing(12)

        self.ac_button = QPushButton("AC Output")
        self.ac_button.setCheckable(True)
        self.ac_button.clicked.connect(self._set_ac_output)

        self.dc_button = QPushButton("DC Output")
        self.dc_button.setCheckable(True)
        self.dc_button.clicked.connect(self._set_dc_output)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Standard", "Silent", "Turbo"])
        self.mode_combo.currentTextChanged.connect(self._set_mode)

        controls.addWidget(self.ac_button)
        controls.addWidget(self.dc_button)
        controls.addStretch()
        controls.addWidget(QLabel("Charging Mode:"))
        controls.addWidget(self.mode_combo)

        right_layout.addLayout(controls)
        right_layout.addStretch()

        content.addWidget(right, 6)
        root.addLayout(content, 1)

        footer = QLabel("Mock backend active — BLE connection will be added next.")
        footer.setObjectName("footer")
        root.addWidget(footer)

    def _set_ac_output(self, checked: bool):
        self.backend.set_ac_output(checked)

    def _set_dc_output(self, checked: bool):
        self.backend.set_dc_output(checked)

    def _set_mode(self, mode: str):
        self.backend.set_charging_mode(mode)

    def _load_model_image(self, model: str):
        path = resolve_model_image(model)
        if path is None:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(
                f"{model}\n\nAdd:\nImages/Bluetti_Models/{model}.png"
            )
            return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"Unable to load:\n{path.name}")
            return

        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.image_label.setText("")
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "current_model"):
            self._load_model_image(self.current_model)

    def refresh(self):
        t = self.backend.get_telemetry()
        self.current_model = t.model

        self.model_label.setText(t.model)
        self.connection_label.setText("● Connected" if t.connected else "● Disconnected")
        self.connection_label.setProperty("connected", t.connected)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

        self.soc_value.setText(f"{t.soc}%")
        self.soc_bar.setValue(t.soc)

        self.cards["battery_voltage"].set_value(f"{t.battery_voltage:.2f} V")
        self.cards["battery_current"].set_value(f"{t.battery_current:.1f} A")
        self.cards["battery_flow"].set_value(t.battery_flow)
        self.cards["temperature"].set_value(f"{t.temperature_c:.1f} °C")
        self.cards["ac_output_power"].set_value(f"{t.ac_output_power} W")
        self.cards["dc_output_power"].set_value(f"{t.dc_output_power} W")
        self.cards["pv_input_power"].set_value(f"{t.pv_input_power} W")
        self.cards["ac_input_power"].set_value(f"{t.ac_input_power} W")

        self.ac_button.blockSignals(True)
        self.ac_button.setChecked(t.ac_output_enabled)
        self.ac_button.setText("AC Output ON" if t.ac_output_enabled else "AC Output OFF")
        self.ac_button.blockSignals(False)

        self.dc_button.blockSignals(True)
        self.dc_button.setChecked(t.dc_output_enabled)
        self.dc_button.setText("DC Output ON" if t.dc_output_enabled else "DC Output OFF")
        self.dc_button.blockSignals(False)

        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentText(t.charging_mode)
        self.mode_combo.blockSignals(False)

        self._load_model_image(t.model)

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #11151a;
                color: #e9eef5;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 14px;
            }

            #appTitle {
                font-size: 26px;
                font-weight: 700;
            }

            #modelLabel {
                color: #9ba9b8;
                font-size: 16px;
            }

            #connectionLabel {
                font-weight: 600;
                color: #ef6a6a;
            }

            #connectionLabel[connected="true"] {
                color: #59d18c;
            }

            #panel {
                background: #181e25;
                border: 1px solid #2a333d;
                border-radius: 14px;
            }

            #metricCard {
                background: #202731;
                border: 1px solid #2e3945;
                border-radius: 10px;
            }

            #metricTitle {
                color: #9ba9b8;
                font-size: 12px;
            }

            #metricValue {
                font-size: 20px;
                font-weight: 650;
            }

            #sectionLabel {
                color: #c8d2dc;
                font-size: 14px;
                font-weight: 650;
            }

            #socValue {
                font-size: 46px;
                font-weight: 750;
            }

            #deviceImage {
                color: #8492a0;
                border: 1px dashed #394653;
                border-radius: 10px;
                padding: 10px;
            }

            QProgressBar {
                background: #252d36;
                border: none;
                border-radius: 9px;
            }

            QProgressBar::chunk {
                background: #52c7ff;
                border-radius: 9px;
            }

            QPushButton {
                background: #2b3540;
                border: 1px solid #3b4855;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #34404d;
            }

            QPushButton:checked {
                background: #166f4b;
                border-color: #2da870;
            }

            QComboBox {
                background: #2b3540;
                border: 1px solid #3b4855;
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 120px;
            }

            #footer {
                color: #788594;
                font-size: 12px;
            }
        """)
