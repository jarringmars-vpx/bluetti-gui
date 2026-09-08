from dataclasses import dataclass


@dataclass
class AppSettings:
    runtime_method: str = "average"
    average_minutes: int = 15
