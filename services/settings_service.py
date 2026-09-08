from PySide6.QtCore import QSettings
from models.settings import AppSettings


class SettingsService:
    ORGANIZATION = "BLUETTICommunity"
    APPLICATION = "BLUETTIMonitor"

    def __init__(self):
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)

    def load(self) -> AppSettings:
        method = self._settings.value("runtime/method", "average", type=str)
        minutes = self._settings.value("runtime/average_minutes", 15, type=int)
        return AppSettings(
            runtime_method=method,
            average_minutes=minutes,
        )

    def save(self, settings: AppSettings) -> None:
        self._settings.setValue("runtime/method", settings.runtime_method)
        self._settings.setValue("runtime/average_minutes", settings.average_minutes)
        self._settings.sync()
