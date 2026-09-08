from dataclasses import dataclass

@dataclass
class Telemetry:
    model: str = "EL30V2"
    connected: bool = True

    soc: int = 72
    battery_voltage: float = 16.4
    battery_current: float = 3.8
    battery_flow: str = "Charging"

    ac_output_power: int = 84
    dc_output_power: int = 12
    pv_input_power: int = 146
    ac_input_power: int = 0

    temperature_c: float = 31.7

    ac_output_enabled: bool = True
    dc_output_enabled: bool = True
    charging_mode: str = "Standard"
