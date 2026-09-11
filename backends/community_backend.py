from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CommunityTelemetry:
    model: str = "EL30V2"
    connected: bool = False
    soc: int = 0

    ac_input_power: float = 0.0
    dc_input_power: float = 0.0
    ac_output_power: float = 0.0
    dc_output_power: float = 0.0

    battery_voltage: Optional[float] = None
    battery_current: Optional[float] = None
    battery_flow: str = "Unknown"

    temperature_c: Optional[float] = None

    ac_output_enabled: bool = False
    dc_output_enabled: bool = False
    charging_mode: str = "Standard"


class CommunityBackend:
    """
    Persistent encrypted BLUETTI community-library backend.

    v0.2.25 adds continuous per-scan console tracing. Every targeted poll
    prints its start time, raw register data, completion time, elapsed time,
    and the idle gap since the previous scan completed. Polling behavior and
    intervals are otherwise unchanged from v0.2.20.

    A transient read failure does not tear down an otherwise healthy
    authenticated BLE session. Reconnection is reserved for actual session
    loss or sustained failures.

    The GUI-facing control API remains read-only in this version.
    """

    supports_writes = False

    def __init__(
        self,
        model: str = "EL30V2",
        poll_seconds: float = 5.0,
        scan_seconds: float = 8.0,
        read_timeout: int = 60,
        reconnect_seconds: float = 2.0,
    ):
        self.model = model
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.scan_seconds = max(1.0, float(scan_seconds))
        self.read_timeout = int(read_timeout)
        self.reconnect_seconds = max(0.5, float(reconnect_seconds))

        # Polling groups are logical GUI/backend capabilities, not raw
        # register knowledge exposed to widgets. The main dashboard currently
        # needs these groups. Future screens can activate/deactivate groups.
        self._active_poll_groups = {
            "control_state",
            "power_flow",
            "battery_summary",
            "temperature",
            "settings",
        }
        self._poll_group_intervals = {
            "control_state": 0.35,
            "power_flow": 0.75,
            "battery_summary": 1.0,
            "temperature": 2.5,
            "settings": 10.0,
        }
        self._max_transient_failures = 3

        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        self._telemetry = CommunityTelemetry(model=model)

        configured = os.environ.get("BLUETTI_BLE_ADDRESS", "").strip()
        self._configured_address = configured or None
        self._address = self._configured_address

        self._status_message = (
            f"Connecting to {model} over Community BLE..."
            if self._address
            else f"Searching for {model} over Bluetooth..."
        )
        self._last_error = ""

        self._worker = threading.Thread(
            target=self._worker_main,
            name="BluettiCommunityBackend",
            daemon=True,
        )
        self._worker.start()

    @property
    def status_message(self) -> str:
        with self._lock:
            return self._status_message

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    @property
    def address(self) -> Optional[str]:
        with self._lock:
            return self._address

    @property
    def active_poll_groups(self) -> set[str]:
        with self._lock:
            return set(self._active_poll_groups)

    def set_poll_group_active(self, group: str, active: bool):
        """
        Activate/deactivate a logical telemetry polling group.

        GUI screens should call this when their visibility changes. Widgets
        never need to know register addresses.
        """
        valid = {"control_state", "power_flow", "battery_summary", "temperature", "settings"}
        if group not in valid:
            raise ValueError(
                f"Unknown Community polling group: {group}. "
                f"Valid groups: {', '.join(sorted(valid))}"
            )

        with self._lock:
            if active:
                self._active_poll_groups.add(group)
            else:
                self._active_poll_groups.discard(group)

    def set_active_poll_groups(self, groups):
        """Replace the active logical polling-group set atomically."""
        requested = set(groups)
        valid = {"control_state", "power_flow", "battery_summary", "temperature", "settings"}
        unknown = requested - valid
        if unknown:
            raise ValueError(
                "Unknown Community polling group(s): "
                + ", ".join(sorted(unknown))
            )

        with self._lock:
            self._active_poll_groups = requested

    def get_telemetry(self) -> CommunityTelemetry:
        with self._lock:
            t = self._telemetry
            return CommunityTelemetry(
                model=t.model,
                connected=t.connected,
                soc=t.soc,
                ac_input_power=t.ac_input_power,
                dc_input_power=t.dc_input_power,
                ac_output_power=t.ac_output_power,
                dc_output_power=t.dc_output_power,
                battery_voltage=t.battery_voltage,
                battery_current=t.battery_current,
                battery_flow=t.battery_flow,
                temperature_c=t.temperature_c,
                ac_output_enabled=t.ac_output_enabled,
                dc_output_enabled=t.dc_output_enabled,
                charging_mode=t.charging_mode,
            )

    def close(self):
        self._stop_event.set()

    def set_ac_output(self, enabled: bool):
        self._set_read_only_notice("AC Output")

    def set_dc_output(self, enabled: bool):
        self._set_read_only_notice("DC Output")

    def set_charging_mode(self, mode: str):
        self._set_read_only_notice("Charging Mode")

    def _set_read_only_notice(self, control: str):
        with self._lock:
            self._status_message = f"{control} control is read-only in v0.2.25."

    def _worker_main(self):
        try:
            asyncio.run(self._async_worker())
        except Exception as exc:
            self._record_failure(f"Backend worker stopped: {exc}")

    async def _async_worker(self):
        while not self._stop_event.is_set():
            session = None

            try:
                if self.model != "EL30V2":
                    raise RuntimeError(
                        f"v0.2.25 CommunityBackend currently supports only EL30V2, "
                        f"not {self.model}."
                    )

                device = await self._resolve_device()

                self._set_status(f"Connecting to {self.model} over Community BLE...")
                session = await self._open_persistent_session(device)

                self._set_status(
                    f"Community BLE connected — live data from {self.model}"
                )
                await self._poll_session(session)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._record_failure(str(exc))
            finally:
                await self._close_session(session)

            if self._stop_event.is_set():
                break

            if self._configured_address is None:
                with self._lock:
                    self._address = None

            self._set_status(
                f"Community BLE disconnected — reconnecting to {self.model}..."
            )
            await self._sleep_interruptibly(self.reconnect_seconds)

    async def _resolve_device(self):
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise RuntimeError(
                "bleak is not installed in this Python environment."
            ) from exc

        if self._address:
            self._set_status(f"Finding {self.model} Bluetooth device...")
            device = await BleakScanner.find_device_by_address(
                self._address,
                timeout=self.scan_seconds,
            )
            if device is None:
                raise RuntimeError(
                    f"{self.model} was not found at the configured Bluetooth address."
                )
            return device

        self._set_status(f"Searching for {self.model} over Bluetooth...")

        discovered = await BleakScanner.discover(
            timeout=self.scan_seconds,
            return_adv=True,
        )

        target = self.model.upper()
        candidates = []

        for device, adv in discovered.values():
            names = [
                (getattr(device, "name", None) or "").strip(),
                (getattr(adv, "local_name", None) or "").strip(),
            ]
            names = [name for name in names if name]

            if not names:
                continue

            exact = any(name.upper().startswith(target) for name in names)
            fuzzy = any(target in name.upper() for name in names)

            if exact or fuzzy:
                rssi = getattr(adv, "rssi", None)
                if not isinstance(rssi, (int, float)):
                    rssi = -9999
                candidates.append((1 if exact else 0, rssi, device))

        if not candidates:
            raise RuntimeError(f"No {self.model} Bluetooth device found.")

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        device = candidates[0][2]

        with self._lock:
            self._address = getattr(device, "address", None)

        if not self._address:
            raise RuntimeError(
                f"{self.model} was discovered but had no usable BLE address."
            )

        return device

    async def _open_persistent_session(self, device):
        try:
            from bluetti_bt_lib.bluetooth.device_session import (
                DeviceSession,
                DeviceSessionConfig,
            )
            from bluetti_bt_lib.devices import EL30V2
        except ImportError as exc:
            raise RuntimeError(
                f"Community BLE dependency import failed: {exc}"
            ) from exc

        loop = asyncio.get_running_loop()

        session = DeviceSession(
            getattr(device, "address", self._address),
            EL30V2(),
            loop.create_future,
            config=DeviceSessionConfig(
                timeout=self.read_timeout,
                use_encryption=True,
                command_timeout=0.5,
            ),
        )

        await session.connect()
        return session

    async def _poll_session(self, session):
        """
        Demand-driven scheduler for active telemetry groups.

        control_state:
            R2011-R2012 (AC state, DC state)
        power_flow:
            R140-R149 (DC out, AC out, PV/DC in, AC/grid in)
        battery_summary:
            R102 only (SOC)
        temperature:
            R1153 only (primary temperature, raw / 10 C)
        settings:
            R2020 only (charging mode); lowest-priority/infrequent polling.

        No full session.read() is used in the normal dashboard loop.

        Fast blocks use DeviceSession.read_registers(), keeping register
        knowledge inside the backend rather than GUI widgets.
        """
        next_due = {
            "control_state": 0.0,
            "power_flow": 0.0,
            "battery_summary": 0.0,
            "temperature": 0.0,
            "settings": 0.0,
        }
        consecutive_failures = 0
        previous_scan_completed = None

        while not self._stop_event.is_set():
            if not session.is_connected:
                raise RuntimeError("Bluetooth connection was lost.")

            if not session.is_ready:
                raise RuntimeError("Encrypted Community BLE session is not ready.")

            with self._lock:
                active_groups = set(self._active_poll_groups)

            now = time.monotonic()
            due = [
                group
                for group in active_groups
                if now >= next_due.get(group, 0.0)
            ]

            if not due:
                await self._sleep_interruptibly(0.05)
                continue

            # Fastest groups first so controls remain responsive.
            due.sort(
                key=lambda group: {
                    "control_state": 0,
                    "power_flow": 1,
                    "battery_summary": 2,
                    "temperature": 3,
                    "settings": 4,
                }.get(group, 99)
            )

            for group in due:
                if self._stop_event.is_set():
                    return

                scan_names = {
                    "control_state": "AC/DC Output",
                    "power_flow": "Power Flow",
                    "battery_summary": "Battery SOC",
                    "temperature": "Temperature",
                    "settings": "Charging Mode",
                }
                scan_name = scan_names.get(group, group)

                poll_started = time.monotonic()
                start_timestamp = self._console_timestamp()
                gap_text = (
                    "first scan"
                    if previous_scan_completed is None
                    else f"gap={poll_started - previous_scan_completed:.3f}s"
                )

                # Deliberately leave the line open. On a normal read the raw
                # values and completion timing are appended to this same line.
                print(
                    f"{start_timestamp} {scan_name} Scan Started: "
                    f"[{gap_text}] ",
                    end="",
                    flush=True,
                )

                values = None
                scan_diagnostics = []
                try:
                    if group == "control_state":
                        values = await session.read_registers(2011, 2)
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_control_state_block(values)

                    elif group == "power_flow":
                        values = await session.read_registers(140, 10)
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_power_block(values)

                    elif group == "battery_summary":
                        values = await session.read_registers(102, 1)
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_battery_summary_block(values)

                    elif group == "temperature":
                        values = await session.read_registers(1153, 1)
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_temperature_block(values)

                    elif group == "settings":
                        values = await session.read_registers(2020, 1)
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_settings_block(values)

                    completed_at = time.monotonic()
                    completed_timestamp = self._console_timestamp()
                    poll_elapsed = completed_at - poll_started
                    previous_scan_completed = completed_at

                    diagnostic_text = (
                        " | ".join(scan_diagnostics) + " | "
                        if scan_diagnostics
                        else ""
                    )
                    print(
                        f"{diagnostic_text}"
                        f"Raw={self._format_raw_registers(values)} | "
                        f"Scan Completed at {completed_timestamp} | "
                        f"elapsed={poll_elapsed:.3f}s",
                        flush=True,
                    )

                    consecutive_failures = 0
                    with self._lock:
                        self._last_error = ""
                        self._telemetry.connected = True
                        self._status_message = (
                            f"Community BLE connected — live data from "
                            f"{self.model}"
                        )

                except Exception as exc:
                    try:
                        scan_diagnostics = session.consume_scan_diagnostics()
                    except Exception:
                        scan_diagnostics = []

                    completed_at = time.monotonic()
                    completed_timestamp = self._console_timestamp()
                    poll_elapsed = completed_at - poll_started
                    previous_scan_completed = completed_at

                    diagnostic_text = (
                        " | ".join(scan_diagnostics) + " | "
                        if scan_diagnostics
                        else ""
                    )
                    print(
                        f"{diagnostic_text}"
                        f"ERROR={type(exc).__name__}: {exc} | "
                        f"Scan Ended at {completed_timestamp} | "
                        f"elapsed={poll_elapsed:.3f}s | "
                        f"connected={session.is_connected} "
                        f"ready={session.is_ready}",
                        flush=True,
                    )

                    # A command timeout or malformed/short response does not
                    # imply link loss. DeviceSession already retries the
                    # command/block on the same authenticated session.
                    if not session.is_connected or not session.is_ready:
                        raise RuntimeError(
                            f"Community BLE session lost while polling "
                            f"{group}: {exc}"
                        ) from exc

                    consecutive_failures += 1
                    with self._lock:
                        self._last_error = (
                            f"Transient {group} read failure: {exc}"
                        )
                        self._status_message = (
                            f"Community BLE connected — retrying {group}"
                        )
                        self._telemetry.connected = True

                    if consecutive_failures >= self._max_transient_failures:
                        raise RuntimeError(
                            f"{consecutive_failures} consecutive Community "
                            f"BLE read failures while session remained ready; "
                            f"last group={group}: {exc}"
                        ) from exc

                finally:
                    next_due[group] = (
                        time.monotonic()
                        + self._poll_group_intervals[group]
                    )

            await self._sleep_interruptibly(0.02)

    @staticmethod
    def _console_timestamp() -> str:
        """Wall-clock timestamp with millisecond precision for console traces."""
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    @staticmethod
    def _format_raw_registers(values: dict[int, int] | None) -> str:
        """Format targeted raw register values in address order."""
        if not values:
            return "{}"
        return "{" + ", ".join(
            f"R{address}=0x{int(value) & 0xFFFF:04X}({int(value)})"
            for address, value in sorted(values.items())
        ) + "}"

    def _apply_control_state_block(self, values: dict[int, int]):
        with self._lock:
            self._telemetry.ac_output_enabled = bool(values[2011])
            self._telemetry.dc_output_enabled = bool(values[2012])
            self._telemetry.connected = True

    def _apply_settings_block(self, values: dict[int, int]):
        with self._lock:
            self._telemetry.charging_mode = self._charging_mode(values[2020])
            self._telemetry.connected = True

    def _apply_power_block(self, values: dict[int, int]):
        with self._lock:
            self._telemetry.dc_output_power = float(values[140])
            self._telemetry.ac_output_power = float(values[142])
            self._telemetry.dc_input_power = float(values[144])
            self._telemetry.ac_input_power = float(values[146])
            self._telemetry.connected = True

    def _apply_battery_summary_block(self, values: dict[int, int]):
        with self._lock:
            soc = int(values[102])
            self._telemetry.soc = max(0, min(100, soc))
            self._telemetry.connected = True

    def _apply_temperature_block(self, values: dict[int, int]):
        with self._lock:
            self._telemetry.temperature_c = float(values[1153]) / 10.0
            self._telemetry.connected = True

    async def _close_session(self, session):
        if session is None:
            return

        try:
            await session.disconnect()
        except Exception:
            pass

    async def _sleep_interruptibly(self, seconds: float):
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end and not self._stop_event.is_set():
            await asyncio.sleep(min(0.25, max(0.0, end - time.monotonic())))

    def _normalize(self, data: dict[str, Any]) -> CommunityTelemetry:
        soc = int(round(self._number(data.get("total_battery_percent"), 0.0)))

        return CommunityTelemetry(
            model=self.model,
            connected=True,
            soc=max(0, min(100, soc)),
            ac_input_power=self._number(data.get("ac_input_power"), 0.0),
            dc_input_power=self._number(data.get("dc_input_power"), 0.0),
            ac_output_power=self._number(data.get("ac_output_power"), 0.0),
            dc_output_power=self._number(data.get("dc_output_power"), 0.0),
            battery_voltage=None,
            battery_current=None,
            battery_flow="Unknown",
            temperature_c=self._optional_number(data.get("temperature")),
            ac_output_enabled=self._boolean(data.get("ctrl_ac")),
            dc_output_enabled=self._boolean(data.get("ctrl_dc")),
            charging_mode=self._charging_mode(data.get("ctrl_charging_mode")),
        )

    @staticmethod
    def _boolean(value: Any) -> bool:
        if value is True:
            return True
        if value is False or value is None:
            return False

        text = str(value).strip().lower()
        return text in {"1", "true", "on", "yes", "enabled"}

    @staticmethod
    def _optional_number(value: Any) -> Optional[float]:
        if value is None:
            return None
        return CommunityBackend._number(value, None)

    @staticmethod
    def _number(value: Any, default):
        if value is None:
            return default

        if isinstance(value, bool):
            return float(int(value))

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)

        if not match:
            return default

        try:
            return float(match.group(0))
        except ValueError:
            return default

    @staticmethod
    def _charging_mode(value: Any) -> str:
        if value is None:
            return "Standard"

        if isinstance(value, (int, float)):
            return {
                0: "Standard",
                1: "Silent",
                2: "Turbo",
            }.get(int(value), str(value))

        text = str(value).strip()
        lowered = text.lower()

        if "silent" in lowered:
            return "Silent"
        if "turbo" in lowered:
            return "Turbo"
        if "standard" in lowered or "normal" in lowered:
            return "Standard"

        tail = text.split(".")[-1].replace("_", " ").strip()
        if tail:
            return tail.title()

        return "Standard"

    def _set_status(self, message: str):
        with self._lock:
            self._status_message = message

    def _record_failure(self, message: str):
        with self._lock:
            previous = self._telemetry
            self._telemetry = CommunityTelemetry(
                model=previous.model or self.model,
                connected=False,
                soc=previous.soc,
                ac_input_power=previous.ac_input_power,
                dc_input_power=previous.dc_input_power,
                ac_output_power=previous.ac_output_power,
                dc_output_power=previous.dc_output_power,
                battery_voltage=previous.battery_voltage,
                battery_current=previous.battery_current,
                battery_flow=previous.battery_flow,
                temperature_c=previous.temperature_c,
                ac_output_enabled=previous.ac_output_enabled,
                dc_output_enabled=previous.dc_output_enabled,
                charging_mode=previous.charging_mode,
            )
            self._last_error = message
            self._status_message = f"Community BLE: {message}"
