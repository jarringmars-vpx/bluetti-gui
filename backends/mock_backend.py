import math
import time
from backends.base_backend import BaseBackend
from models.telemetry import Telemetry

class MockBackend(BaseBackend):
    def __init__(self):
        self._telemetry = Telemetry()
        self._start = time.time()

    def get_telemetry(self) -> Telemetry:
        # Small movement makes it obvious that polling is alive.
        elapsed = time.time() - self._start
        self._telemetry.pv_input_power = int(145 + 8 * math.sin(elapsed / 4.0))
        self._telemetry.temperature_c = round(31.7 + 0.4 * math.sin(elapsed / 8.0), 1)
        return self._telemetry

    def set_ac_output(self, enabled: bool) -> None:
        self._telemetry.ac_output_enabled = bool(enabled)

    def set_dc_output(self, enabled: bool) -> None:
        self._telemetry.dc_output_enabled = bool(enabled)

    def set_charging_mode(self, mode: str) -> None:
        if mode not in {"Standard", "Silent", "Turbo"}:
            raise ValueError(f"Unsupported charging mode: {mode}")
        self._telemetry.charging_mode = mode
