from collections import deque
from dataclasses import dataclass
import time


@dataclass
class PowerSample:
    timestamp: float
    watts: float


class RuntimeEstimator:
    def __init__(self):
        self._samples = deque()

    def add_output_sample(self, watts: float, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._samples.append(PowerSample(now, max(0.0, float(watts))))

    def _prune(self, average_minutes: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        cutoff = now - (average_minutes * 60)

        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

    def average_watts(self, average_minutes: int, now: float | None = None) -> float:
        self._prune(average_minutes, now)

        if not self._samples:
            return 0.0

        return sum(sample.watts for sample in self._samples) / len(self._samples)

    def estimate_minutes(
        self,
        capacity_wh: float,
        soc_percent: float,
        current_output_watts: float,
        method: str = "average",
        average_minutes: int = 15,
    ) -> int | None:
        remaining_wh = max(0.0, capacity_wh * (soc_percent / 100.0))

        if method == "instantaneous":
            load_watts = max(0.0, float(current_output_watts))
        else:
            load_watts = self.average_watts(average_minutes)

        if load_watts < 1.0:
            return None

        hours = remaining_wh / load_watts
        return max(0, int(round(hours * 60)))

    @staticmethod
    def format_minutes(minutes: int | None) -> str:
        if minutes is None:
            return "--"

        hours, mins = divmod(minutes, 60)

        if hours <= 0:
            return f"{mins}m"

        return f"{hours}h {mins:02d}m"
