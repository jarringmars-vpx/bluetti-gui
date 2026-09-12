from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings

from models.settings import (
    AppSettings,
    DEFAULT_DIAGNOSTIC_CATEGORIES,
    DEFAULT_PANEL_ORDER,
)


class SettingsService:
    ORGANIZATION = "BLUETTICommunity"
    APPLICATION = "BLUETTIMonitor"

    def __init__(self):
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)

    def load(self) -> AppSettings:
        method = self._settings.value("runtime/method", "average", type=str)
        minutes = self._settings.value("runtime/average_minutes", 15, type=int)
        temperature_units = self._settings.value(
            "display/temperature_units", "fahrenheit", type=str
        )
        runtime_display_units = self._settings.value(
            "runtime/display_units", "minutes", type=str
        )

        panel_order = self._json_list(
            self._settings.value("dashboard/panel_order", ""),
            DEFAULT_PANEL_ORDER,
        )
        panel_order = self._normalize_panel_order(panel_order)

        diagnostic_categories = dict(DEFAULT_DIAGNOSTIC_CATEGORIES)
        saved_categories = self._json_dict(
            self._settings.value("diagnostics/categories", "")
        )
        for key in diagnostic_categories:
            if key in saved_categories:
                diagnostic_categories[key] = bool(saved_categories[key])

        return AppSettings(
            runtime_method=method,
            average_minutes=minutes,
            temperature_units=temperature_units,
            runtime_display_units=runtime_display_units,
            auto_connect=self._settings.value(
                "connection/auto_connect", True, type=bool
            ),
            auto_reconnect=self._settings.value(
                "connection/auto_reconnect", True, type=bool
            ),
            preferred_backend=self._settings.value(
                "connection/backend", "community", type=str
            ),
            setup_complete=self._settings.value(
                "setup/first_run_complete", False, type=bool
            ),
            device_model=self._settings.value(
                "device/model", "EL30V2", type=str
            ),
            device_name=self._settings.value("device/name", "", type=str),
            device_address=self._settings.value("device/address", "", type=str),
            panel_order=panel_order,
            diagnostics_enabled=self._settings.value(
                "diagnostics/enabled", False, type=bool
            ),
            diagnostic_categories=diagnostic_categories,
            diagnostics_to_console=self._settings.value(
                "diagnostics/to_console", False, type=bool
            ),
            diagnostics_to_file=self._settings.value(
                "diagnostics/to_file", False, type=bool
            ),
            diagnostics_log_directory=self._settings.value(
                "diagnostics/log_directory", "logs", type=str
            ),
            diagnostic_message_format=self._settings.value(
                "diagnostics/message_format", "raw", type=str
            ),
            diagnostic_registers_per_group=self._settings.value(
                "diagnostics/registers_per_group", 10, type=int
            ),
        )

    def save(self, settings: AppSettings) -> None:
        self._settings.setValue("runtime/method", settings.runtime_method)
        self._settings.setValue(
            "runtime/average_minutes", settings.average_minutes
        )
        self._settings.setValue(
            "display/temperature_units", settings.temperature_units
        )
        self._settings.setValue(
            "runtime/display_units", settings.runtime_display_units
        )

        self._settings.setValue("connection/auto_connect", settings.auto_connect)
        self._settings.setValue(
            "connection/auto_reconnect", settings.auto_reconnect
        )
        self._settings.setValue("connection/backend", settings.preferred_backend)

        self._settings.setValue(
            "setup/first_run_complete", settings.setup_complete
        )
        self._settings.setValue("device/model", settings.device_model)
        self._settings.setValue("device/name", settings.device_name)
        self._settings.setValue("device/address", settings.device_address)

        self._settings.setValue(
            "dashboard/panel_order", json.dumps(settings.panel_order)
        )

        self._settings.setValue(
            "diagnostics/enabled", settings.diagnostics_enabled
        )
        self._settings.setValue(
            "diagnostics/categories",
            json.dumps(settings.diagnostic_categories, sort_keys=True),
        )
        self._settings.setValue(
            "diagnostics/to_console", settings.diagnostics_to_console
        )
        self._settings.setValue(
            "diagnostics/to_file", settings.diagnostics_to_file
        )
        self._settings.setValue(
            "diagnostics/log_directory", settings.diagnostics_log_directory
        )
        self._settings.setValue(
            "diagnostics/message_format", settings.diagnostic_message_format
        )
        self._settings.setValue(
            "diagnostics/registers_per_group", settings.diagnostic_registers_per_group
        )
        self._settings.sync()

    def mark_device_configured(
        self, model: str, name: str, address: str, backend: str = "community"
    ) -> AppSettings:
        settings = self.load()
        settings.setup_complete = True
        settings.device_model = model or "EL30V2"
        settings.device_name = name or ""
        settings.device_address = address or ""
        settings.preferred_backend = backend or "community"
        self.save(settings)
        return settings

    def forget_device(self) -> AppSettings:
        settings = self.load()
        settings.setup_complete = False
        settings.device_name = ""
        settings.device_address = ""
        self.save(settings)
        return settings

    def reset_dashboard_layout(self) -> AppSettings:
        settings = self.load()
        settings.panel_order = list(DEFAULT_PANEL_ORDER)
        self.save(settings)
        return settings

    @staticmethod
    def _json_list(value, default):
        try:
            parsed = json.loads(str(value)) if value else None
            return parsed if isinstance(parsed, list) else list(default)
        except (TypeError, ValueError, json.JSONDecodeError):
            return list(default)

    @staticmethod
    def _json_dict(value):
        try:
            parsed = json.loads(str(value)) if value else None
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _normalize_panel_order(order):
        known = list(DEFAULT_PANEL_ORDER)
        clean = [item for item in order if item in known]
        for item in known:
            if item not in clean:
                clean.append(item)
        return clean
