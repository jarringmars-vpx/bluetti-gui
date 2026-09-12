from dataclasses import dataclass, field


DEFAULT_PANEL_ORDER = ["ac", "dc", "battery", "temperature", "charging_mode"]
DEFAULT_DIAGNOSTIC_CATEGORIES = {
    "control_state": False,
    "power_flow": False,
    "battery_summary": False,
    "temperature": False,
    "settings": False,
    "lifetime_energy": False,
    "fault_status": False,
    "retry_timeout": True,
    "unexpected": True,
    "unsolicited": True,
    "connection": True,
}


@dataclass
class AppSettings:
    runtime_method: str = "average"
    average_minutes: int = 15
    temperature_units: str = "fahrenheit"  # fahrenheit | celsius | both
    runtime_display_units: str = "minutes"  # minutes | hours

    auto_connect: bool = True
    auto_reconnect: bool = True
    preferred_backend: str = "community"
    setup_complete: bool = False
    device_model: str = "EL30V2"
    device_name: str = ""
    device_address: str = ""

    panel_order: list[str] = field(default_factory=lambda: list(DEFAULT_PANEL_ORDER))

    diagnostics_enabled: bool = False
    diagnostic_categories: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_DIAGNOSTIC_CATEGORIES)
    )
    diagnostics_to_console: bool = False
    diagnostics_to_file: bool = False
    diagnostics_log_directory: str = "logs"
    diagnostic_message_format: str = "raw"  # raw | registers | both
    diagnostic_registers_per_group: int = 10
