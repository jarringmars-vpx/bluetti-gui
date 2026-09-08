from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from devices.image_resolver import resolve_model_image


MODEL_IMAGE_DIR = Path("Images") / "Bluetti_Models"


@dataclass
class DeviceVisualState:
    soc: int = 0
    input_watts: int = 0
    output_watts: int = 0
    time_remaining: str = "--"
    dc_output_enabled: bool = False
    ac_output_enabled: bool = False
    power_enabled: bool = True


class SevenSegmentRenderer:
    SEGMENTS = {
        "0": "abcdef",
        "1": "bc",
        "2": "abdeg",
        "3": "abcdg",
        "4": "bcfg",
        "5": "acdfg",
        "6": "acdefg",
        "7": "abc",
        "8": "abcdefg",
        "9": "abcdfg",
    }

    def __init__(self, color: QColor):
        self.color = color

    @staticmethod
    def _h_segment(x, y, length, thickness):
        cut = thickness * 0.34
        path = QPainterPath()
        path.moveTo(x + cut, y)
        path.lineTo(x + length - cut, y)
        path.lineTo(x + length, y + thickness / 2)
        path.lineTo(x + length - cut, y + thickness)
        path.lineTo(x + cut, y + thickness)
        path.lineTo(x, y + thickness / 2)
        path.closeSubpath()
        return path

    @staticmethod
    def _v_segment(x, y, length, thickness):
        cut = thickness * 0.34
        path = QPainterPath()
        path.moveTo(x, y + cut)
        path.lineTo(x + thickness / 2, y)
        path.lineTo(x + thickness, y + cut)
        path.lineTo(x + thickness, y + length - cut)
        path.lineTo(x + thickness / 2, y + length)
        path.lineTo(x, y + length - cut)
        path.closeSubpath()
        return path

    def draw_number(
        self,
        painter: QPainter,
        text: str,
        rect: QRectF,
        digit_height_ratio: float = 0.80,
        digit_width_ratio: float = 0.40,
        stroke_ratio: float = 0.068,
        spacing_ratio: float = 0.10,
    ):
        digits = [ch for ch in str(text) if ch.isdigit()]
        if not digits:
            return

        target_h = rect.height() * digit_height_ratio
        digit_w = target_h * digit_width_ratio
        spacing = digit_w * spacing_ratio
        total_w = digit_w * len(digits) + spacing * max(0, len(digits) - 1)

        if total_w > rect.width():
            scale = rect.width() / total_w
            target_h *= scale
            digit_w *= scale
            spacing *= scale
            total_w = digit_w * len(digits) + spacing * max(0, len(digits) - 1)

        start_x = rect.center().x() - total_w / 2
        start_y = rect.center().y() - target_h / 2

        thickness = max(1.5, target_h * stroke_ratio)
        vertical_length = (target_h - 3 * thickness) / 2

        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)

        for index, ch in enumerate(digits):
            x = start_x + index * (digit_w + spacing)
            y = start_y
            active = set(self.SEGMENTS.get(ch, ""))

            paths = {
                "a": self._h_segment(
                    x + thickness * 0.08,
                    y,
                    digit_w - thickness * 0.16,
                    thickness,
                ),
                "g": self._h_segment(
                    x + thickness * 0.08,
                    y + target_h / 2 - thickness / 2,
                    digit_w - thickness * 0.16,
                    thickness,
                ),
                "d": self._h_segment(
                    x + thickness * 0.08,
                    y + target_h - thickness,
                    digit_w - thickness * 0.16,
                    thickness,
                ),
                "f": self._v_segment(
                    x,
                    y + thickness * 0.55,
                    vertical_length,
                    thickness,
                ),
                "b": self._v_segment(
                    x + digit_w - thickness,
                    y + thickness * 0.55,
                    vertical_length,
                    thickness,
                ),
                "e": self._v_segment(
                    x,
                    y + target_h / 2 + thickness * 0.05,
                    vertical_length,
                    thickness,
                ),
                "c": self._v_segment(
                    x + digit_w - thickness,
                    y + target_h / 2 + thickness * 0.05,
                    vertical_length,
                    thickness,
                ),
            }

            for name in active:
                painter.drawPath(paths[name])

        painter.restore()


class DeviceVisualWidget(QWidget):
    # Desired state emitted when the photographed button is clicked.
    dc_output_requested = Signal(bool)
    ac_output_requested = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._model = ""
        self._profile: Optional[dict[str, Any]] = None
        self._state = DeviceVisualState()
        self._base_image = QImage()
        self._last_target_rect = QRectF()

        self.setMinimumSize(360, 250)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)

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
        render_asset = self._profile.get("render_image") if self._profile else None

        if render_asset:
            candidate = MODEL_IMAGE_DIR / render_asset
            if candidate.exists():
                self._base_image = QImage(str(candidate))
                return

        fallback = resolve_model_image(self._model)
        self._base_image = QImage(str(fallback)) if fallback else QImage()

    @staticmethod
    def _normalized_rect(spec: dict[str, float], width: int, height: int) -> QRectF:
        return QRectF(
            spec["x"] * width,
            spec["y"] * height,
            spec["width"] * width,
            spec["height"] * height,
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#181e25"))

        if self._base_image.isNull():
            self._last_target_rect = QRectF()
            painter.setPen(QColor("#8492a0"))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                f"{self._model or 'Unknown model'}\n\nNo model image found",
            )
            return

        rendered = self._base_image.copy()

        if self._profile:
            self._recolor_buttons(rendered)

        rendered_pixmap = QPixmap.fromImage(rendered)

        if self._profile:
            self._paint_lcd_values(rendered_pixmap)

        target = self._scaled_target_rect(rendered_pixmap)
        self._last_target_rect = target
        painter.drawPixmap(target, rendered_pixmap, rendered_pixmap.rect())

    def _scaled_target_rect(self, pixmap: QPixmap) -> QRectF:
        available = self.rect().adjusted(8, 8, -8, -8)

        source_w = pixmap.width()
        source_h = pixmap.height()

        if source_w <= 0 or source_h <= 0:
            return QRectF()

        scale = min(
            available.width() / source_w,
            available.height() / source_h,
        )

        width = source_w * scale
        height = source_h * scale
        x = available.x() + (available.width() - width) / 2
        y = available.y() + (available.height() - height) / 2

        return QRectF(x, y, width, height)

    def _widget_point_to_normalized(self, x: float, y: float):
        """
        Convert a mouse position in widget coordinates into normalized
        coordinates on the original model image.
        """
        target = self._last_target_rect

        if target.isEmpty() or not target.contains(x, y):
            return None

        nx = (x - target.left()) / target.width()
        ny = (y - target.top()) / target.height()

        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            return None

        return nx, ny

    def _hit_button(self, x: float, y: float) -> Optional[str]:
        if not self._profile:
            return None

        normalized = self._widget_point_to_normalized(x, y)
        if normalized is None:
            return None

        nx, ny = normalized

        for name, spec in self._profile.get("buttons", {}).items():
            left = spec["x"]
            top = spec["y"]
            right = left + spec["width"]
            bottom = top + spec["height"]

            if left <= nx <= right and top <= ny <= bottom:
                return name

        return None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            hit = self._hit_button(event.position().x(), event.position().y())

            if hit == "dc_output":
                self.dc_output_requested.emit(not self._state.dc_output_enabled)
                event.accept()
                return

            if hit == "ac_output":
                self.ac_output_requested.emit(not self._state.ac_output_enabled)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        hit = self._hit_button(event.position().x(), event.position().y())

        if hit in ("dc_output", "ac_output"):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)

    def _paint_lcd_values(self, pixmap: QPixmap):
        fields = self._profile.get("display", {}).get("fields", {})
        if not fields:
            return

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        w = pixmap.width()
        h = pixmap.height()

        display = self._profile.get("display", {})
        digit_color = QColor(display.get("digit_color", "#F4FBFF"))
        segment_renderer = SevenSegmentRenderer(digit_color)

        numeric_values = {
            "input_watts": max(0, int(round(self._state.input_watts))),
            "soc": max(0, min(100, int(round(self._state.soc)))),
            "output_watts": max(0, int(round(self._state.output_watts))),
        }

        for name, value in numeric_values.items():
            spec = fields.get(name)
            if not spec:
                continue

            rect = self._normalized_rect(spec, w, h)
            segment_renderer.draw_number(
                painter,
                str(value),
                rect,
                digit_height_ratio=spec.get("digit_height_ratio", 0.80),
                digit_width_ratio=spec.get("digit_width_ratio", 0.40),
                stroke_ratio=spec.get("stroke_ratio", 0.068),
                spacing_ratio=spec.get("spacing_ratio", 0.10),
            )

        runtime_spec = fields.get("time_remaining")
        if runtime_spec:
            rect = self._normalized_rect(runtime_spec, w, h)
            painter.setPen(digit_color)

            font = QFont("Arial")
            font.setBold(True)
            font.setPixelSize(
                max(8, int(runtime_spec.get("font_ratio", 0.0145) * h))
            )
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self._state.time_remaining)

        painter.end()

    def _recolor_buttons(self, image: QImage):
        buttons = self._profile.get("buttons", {})
        if not buttons:
            return

        states = {
            "dc_output": self._state.dc_output_enabled,
            "power": self._state.power_enabled,
            "ac_output": self._state.ac_output_enabled,
        }

        for name, enabled in states.items():
            spec = buttons.get(name)
            if spec and not enabled:
                self._mute_green_region(image, spec)

    def _mute_green_region(self, image: QImage, spec: dict[str, Any]):
        width = image.width()
        height = image.height()

        x0 = max(0, int(spec["x"] * width))
        y0 = max(0, int(spec["y"] * height))
        x1 = min(width, int((spec["x"] + spec["width"]) * width))
        y1 = min(height, int((spec["y"] + spec["height"]) * height))

        min_green = int(spec.get("min_green", 38))
        dominance = int(spec.get("green_dominance", 6))

        symbol_green_threshold = int(spec.get("symbol_green_threshold", 150))
        symbol_luminance_threshold = int(
            spec.get("symbol_luminance_threshold", 95)
        )

        glow_neutral_scale = float(spec.get("glow_neutral_scale", 0.22))
        glow_residual_green = float(spec.get("glow_residual_green", 0.08))

        symbol_brightness = float(spec.get("symbol_brightness", 0.62))
        symbol_green_bias = int(spec.get("symbol_green_bias", 10))

        for y in range(y0, y1):
            for x in range(x0, x1):
                c = image.pixelColor(x, y)
                r, g, b, a = c.red(), c.green(), c.blue(), c.alpha()

                if not (
                    g >= min_green
                    and g >= r + dominance
                    and g >= b + dominance
                ):
                    continue

                luminance = int(
                    0.2126 * r + 0.7152 * g + 0.0722 * b
                )

                if (
                    g >= symbol_green_threshold
                    and luminance >= symbol_luminance_threshold
                ):
                    base = int(luminance * symbol_brightness)
                    nr = base
                    ng = min(255, base + symbol_green_bias)
                    nb = base
                else:
                    base = int(luminance * glow_neutral_scale)
                    nr = base
                    ng = int(base + g * glow_residual_green)
                    nb = base

                image.setPixelColor(
                    x,
                    y,
                    QColor(
                        max(0, min(255, nr)),
                        max(0, min(255, ng)),
                        max(0, min(255, nb)),
                        a,
                    ),
                )
