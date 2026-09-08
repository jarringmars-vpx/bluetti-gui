from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from devices.image_resolver import resolve_model_image


@dataclass
class DeviceVisualState:
    soc: int = 0
    input_watts: int = 0
    output_watts: int = 0
    time_remaining: str = "--"
    dc_output_enabled: bool = False
    ac_output_enabled: bool = False
    power_enabled: bool = True


class DeviceVisualWidget(QWidget):
    """
    Renders a BLUETTI model image with optional model-specific live overlays.

    The source image is never modified. All LCD replacements and illumination
    effects are painted onto an in-memory copy.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = ""
        self._profile: Optional[dict[str, Any]] = None
        self._state = DeviceVisualState()
        self._base_pixmap = QPixmap()
        self.setMinimumSize(360, 250)

    def set_model(self, model: str, visual_profile: Optional[dict[str, Any]] = None):
        if model == self._model and visual_profile == self._profile:
            return

        self._model = model
        self._profile = visual_profile
        self._load_image()
        self.update()

    def set_state(self, state: DeviceVisualState):
        self._state = state
        self.update()

    def _load_image(self):
        path = resolve_model_image(self._model)
        self._base_pixmap = QPixmap(str(path)) if path else QPixmap()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor("#181e25"))

        if self._base_pixmap.isNull():
            painter.setPen(QColor("#8492a0"))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                f"{self._model or 'Unknown model'}\n\nNo model image found",
            )
            return

        rendered = QPixmap(self._base_pixmap)

        if self._profile:
            self._paint_dynamic_front_panel(rendered)

        target = self._scaled_target_rect(rendered)
        painter.drawPixmap(target, rendered, rendered.rect())

    def _scaled_target_rect(self, pixmap: QPixmap) -> QRectF:
        available = self.rect().adjusted(8, 8, -8, -8)
        scaled = pixmap.size()
        scaled.scale(available.size(), Qt.KeepAspectRatio)

        x = available.x() + (available.width() - scaled.width()) // 2
        y = available.y() + (available.height() - scaled.height()) // 2
        return QRectF(x, y, scaled.width(), scaled.height())

    @staticmethod
    def _normalized_rect(spec: dict[str, float], width: int, height: int) -> QRectF:
        return QRectF(
            spec["x"] * width,
            spec["y"] * height,
            spec["width"] * width,
            spec["height"] * height,
        )

    def _paint_dynamic_front_panel(self, pixmap: QPixmap):
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        width = pixmap.width()
        height = pixmap.height()

        fields = self._profile.get("display", {}).get("fields", {})

        values = {
            "soc": f"{self._state.soc}",
            "input_watts": f"{self._state.input_watts}",
            "output_watts": f"{self._state.output_watts}",
            "time_remaining": self._state.time_remaining,
        }

        for name, value in values.items():
            spec = fields.get(name)
            if spec:
                self._paint_display_field(
                    painter, width, height, spec, value
                )

        indicator_states = {
            "dc_output": self._state.dc_output_enabled,
            "ac_output": self._state.ac_output_enabled,
            "power": self._state.power_enabled,
        }

        for name, enabled in indicator_states.items():
            spec = self._profile.get("indicators", {}).get(name)
            if spec and enabled:
                self._paint_indicator_glow(
                    painter, width, height, spec
                )

        painter.end()

    def _paint_display_field(
        self,
        painter: QPainter,
        image_width: int,
        image_height: int,
        spec: dict[str, Any],
        value: str,
    ):
        rect = self._normalized_rect(spec, image_width, image_height)

        background = QColor(spec.get("background", "#07100d"))
        background.setAlpha(spec.get("background_alpha", 235))
        painter.fillRect(rect, background)

        painter.setPen(QPen(QColor(spec.get("color", "#e9fbff"))))

        font = QFont(spec.get("font_family", "Segoe UI"))
        font.setBold(spec.get("bold", True))
        font.setPixelSize(
            max(8, int(spec.get("font_ratio", 0.020) * image_height))
        )
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, value)

    def _paint_indicator_glow(
        self,
        painter: QPainter,
        image_width: int,
        image_height: int,
        spec: dict[str, Any],
    ):
        cx = spec["x"] * image_width
        cy = spec["y"] * image_height
        radius = spec.get("radius", 0.015) * min(image_width, image_height)

        glow = QColor(spec.get("color", "#38ff70"))
        glow.setAlpha(spec.get("alpha", 90))

        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(
            QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        )

        core = QColor(spec.get("color", "#38ff70"))
        core.setAlpha(spec.get("core_alpha", 145))
        painter.setBrush(core)

        inner = radius * 0.52
        painter.drawEllipse(
            QRectF(cx - inner, cy - inner, inner * 2, inner * 2)
        )
