from abc import ABC, abstractmethod
from models.telemetry import Telemetry

class BaseBackend(ABC):
    @abstractmethod
    def get_telemetry(self) -> Telemetry:
        raise NotImplementedError

    @abstractmethod
    def set_ac_output(self, enabled: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_dc_output(self, enabled: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_charging_mode(self, mode: str) -> None:
        raise NotImplementedError
