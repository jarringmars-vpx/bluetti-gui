from __future__ import annotations

import asyncio
import os
import re
import threading
import queue
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
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
    lifetime_energy_kwh: Optional[float] = None

    temperature_c: Optional[float] = None
    fan_state: str = "Unknown"
    fan_raw: Optional[int] = None

    fault_active: bool = False
    fault_summary: str = "No Faults"

    ac_output_enabled: bool = False
    dc_output_enabled: bool = False
    charging_mode: str = "Standard"


@dataclass
class CommunityDeviceInfo:
    model: str = "EL30V2"
    device_name: str = ""
    ble_address: str = ""
    device_serial: str = ""
    communication_board_serial: str = ""
    firmware_version: str = "Not available"
    protocol: str = "IoT v2 / encrypted BLE"
    backend: str = "Community"
    authenticated: bool = False
    wifi_status: str = "Unknown"
    wifi_ssid: str = ""
    wifi_ip: str = ""
    wifi_gateway: str = ""
    wifi_subnet_mask: str = ""
    wifi_rssi: Optional[int] = None
    wifi_mac: str = ""
    ble_mac: str = ""


class CommunityBackend:
    """
    Persistent encrypted BLUETTI community-library backend.

    v0.2.34 timestamps every console/file diagnostic line; v0.2.34 adds optional decoded register formatting for autonomous/unexpected diagnostics; v0.2.31 corrected R154 PV Generation scaling and enabled charging-mode writes; v0.2.30 added fan state, fault/status polling, and
    persistent-session AC/DC writes with immediate read-back verification.
    Routine polling traces can be hidden, while retries/timeouts, unexpected
    responses, and unsolicited/out-of-band messages can independently be sent
    to the console and/or a timestamped log file.

    A transient read failure does not tear down an otherwise healthy
    authenticated BLE session. Reconnection is reserved for actual session
    loss or sustained failures.

    AC and DC output writes are enabled through the existing persistent encrypted session.
    """

    supports_writes = True
    supports_ac_output_writes = True
    supports_dc_output_writes = True
    supports_charging_mode_writes = True

    def __init__(
        self,
        model: str = "EL30V2",
        poll_seconds: float = 5.0,
        scan_seconds: float = 8.0,
        read_timeout: int = 60,
        reconnect_seconds: float = 2.0,
        address: Optional[str] = None,
        device_name: str = "",
        auto_start: bool = True,
        auto_reconnect: bool = True,
        diagnostic_config: Optional[dict] = None,
    ):
        self.model = model
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.scan_seconds = max(1.0, float(scan_seconds))
        self.read_timeout = int(read_timeout)
        self.reconnect_seconds = max(0.5, float(reconnect_seconds))
        self.auto_reconnect = bool(auto_reconnect)
        self._device_name = device_name or ""
        self._diagnostic_config = diagnostic_config or {}
        self._diagnostic_file = None
        self._diagnostic_file_path = None
        self._diagnostic_lock = threading.RLock()

        # Polling groups are logical GUI/backend capabilities, not raw
        # register knowledge exposed to widgets. The main dashboard currently
        # needs these groups. Future screens can activate/deactivate groups.
        self._active_poll_groups = {
            "control_state",
            "power_flow",
            "battery_summary",
            "temperature",
            "fault_status",
            "lifetime_energy",
            "settings",
        }
        self._poll_group_intervals = {
            "control_state": 0.35,
            "power_flow": 0.75,
            "battery_summary": 1.0,
            "temperature": 2.5,
            "fault_status": 2.0,
            "lifetime_energy": 60.0,
            "settings": 10.0,
        }
        self._max_transient_failures = 3

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._control_queue: queue.Queue[tuple[str, Any, str]] = queue.Queue()

        configured = (address or os.environ.get("BLUETTI_BLE_ADDRESS", "")).strip()
        self._configured_address = configured or None
        self._address = self._configured_address

        self._telemetry = CommunityTelemetry(model=model)
        self._device_info = CommunityDeviceInfo(
            model=model,
            device_name=self._device_name,
            ble_address=self._configured_address or "",
        )

        self._status_message = (
            f"Connecting to {model} over Community BLE..."
            if self._address
            else f"Searching for {model} over Bluetooth..."
        )
        self._last_error = ""

        self._worker = None
        if auto_start:
            self.start()

    def start(self):
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._worker_main,
            name="BluettiCommunityBackend",
            daemon=True,
        )
        self._worker.start()

    def configure_diagnostics(self, config: dict):
        with self._diagnostic_lock:
            self._diagnostic_config = dict(config or {})
            if self._diagnostic_file is not None:
                try:
                    self._diagnostic_file.flush()
                    self._diagnostic_file.close()
                except Exception:
                    pass
                self._diagnostic_file = None
                self._diagnostic_file_path = None

    def get_device_info(self) -> CommunityDeviceInfo:
        with self._lock:
            d = self._device_info
            return CommunityDeviceInfo(**d.__dict__)

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
        valid = {"control_state", "power_flow", "battery_summary", "temperature", "fault_status", "lifetime_energy", "settings"}
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
        valid = {"control_state", "power_flow", "battery_summary", "temperature", "fault_status", "lifetime_energy", "settings"}
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
                lifetime_energy_kwh=t.lifetime_energy_kwh,
                temperature_c=t.temperature_c,
                fan_state=t.fan_state,
                fan_raw=t.fan_raw,
                fault_active=t.fault_active,
                fault_summary=t.fault_summary,
                ac_output_enabled=t.ac_output_enabled,
                dc_output_enabled=t.dc_output_enabled,
                charging_mode=t.charging_mode,
            )

    def close(self):
        self._stop_event.set()
        with self._diagnostic_lock:
            if self._diagnostic_file is not None:
                try:
                    self._diagnostic_file.flush()
                    self._diagnostic_file.close()
                except Exception:
                    pass
                self._diagnostic_file = None

    def set_ac_output(self, enabled: bool):
        self._queue_output_write("ctrl_ac", bool(enabled), "AC Output")

    def set_dc_output(self, enabled: bool):
        self._queue_output_write("ctrl_dc", bool(enabled), "DC Output")

    def set_charging_mode(self, mode: str):
        mode_values = {
            "Standard": 0,
            "Silent": 1,
            "Turbo": 2,
        }
        if mode not in mode_values:
            with self._lock:
                self._status_message = f"Unsupported Charging Mode: {mode}"
            return
        self._queue_control_write(
            "ctrl_charging_mode",
            mode_values[mode],
            "Charging Mode",
            readback_register=2020,
            readback_count=1,
        )

    def _queue_output_write(self, field: str, value: bool, label: str):
        self._queue_control_write(
            field,
            bool(value),
            label,
            readback_register=2011,
            readback_count=2,
        )

    def _queue_control_write(
        self,
        field: str,
        value: Any,
        label: str,
        *,
        readback_register: int,
        readback_count: int,
    ):
        with self._lock:
            if not self._telemetry.connected:
                self._status_message = f"Cannot change {label}: device is not connected."
                return
            if field in ("ctrl_ac", "ctrl_dc"):
                detail = "ON" if bool(value) else "OFF"
            elif field == "ctrl_charging_mode":
                detail = self._charging_mode(value)
            else:
                detail = str(value)
            self._status_message = f"Sending {label} {detail}..."
        self._control_queue.put(
            (field, value, label, int(readback_register), int(readback_count))
        )

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
                        f"v0.2.34 CommunityBackend currently supports only EL30V2, "
                        f"not {self.model}."
                    )

                device = await self._resolve_device()

                self._set_status(f"Connecting to {self.model} over Community BLE...")
                session = await self._open_persistent_session(device)
                await self._refresh_device_info(session, device)

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

            if self._stop_event.is_set() or not self.auto_reconnect:
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
            R102 (SOC), R6003-R6004 (battery voltage/current magnitude),
            and R6009 (battery flow state)
        temperature:
            R1153 (primary temperature, raw / 10 C) and R6350 (fan/cooling bitfield)
        fault_status:
            R133 and R137 individually (validated fault/event candidates)
        lifetime_energy:
            R154 (PV Generation, raw tenths of kWh)
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
            "fault_status": 0.0,
            "lifetime_energy": 0.0,
            "settings": 0.0,
        }
        consecutive_failures = 0
        previous_scan_completed = None

        while not self._stop_event.is_set():
            if not session.is_connected:
                raise RuntimeError("Bluetooth connection was lost.")

            if not session.is_ready:
                raise RuntimeError("Encrypted Community BLE session is not ready.")

            await self._process_pending_control_write(session)

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
                    "fault_status": 4,
                    "settings": 5,
                    "lifetime_energy": 6,
                }.get(group, 99)
            )

            for group in due:
                if self._stop_event.is_set():
                    return

                scan_names = {
                    "control_state": "AC/DC Output",
                    "power_flow": "Power Flow",
                    "battery_summary": "Battery Summary",
                    "temperature": "Temperature/Fan",
                    "fault_status": "Fault Status",
                    "lifetime_energy": "PV Generation",
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
                start_message = (
                    f"{start_timestamp} {scan_name} Scan Started: [{gap_text}]"
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
                        # Keep SOC in this logical group, but also populate the
                        # Battery panel from the validated EL30V2 battery
                        # registers. R6004 is a magnitude; R6009 supplies the
                        # charging/discharging direction separately.
                        values = {}
                        values.update(await session.read_registers(102, 1))
                        values.update(await session.read_registers(6003, 2))
                        values.update(await session.read_registers(6009, 1))
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_battery_summary_block(values)

                    elif group == "temperature":
                        values = {}
                        values.update(await session.read_registers(1153, 1))
                        values.update(await session.read_registers(6350, 1))
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_temperature_block(values)

                    elif group == "fault_status":
                        values = {}
                        values.update(await session.read_registers(133, 1))
                        values.update(await session.read_registers(137, 1))
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_fault_status_block(values)

                    elif group == "lifetime_energy":
                        values = await session.read_registers(154, 1)
                        scan_diagnostics = session.consume_scan_diagnostics()
                        self._apply_lifetime_energy_block(values)

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
                    self._emit_diagnostic(
                        group,
                        f"{start_message} | {diagnostic_text}"
                        f"Raw={self._format_raw_registers(values)} | "
                        f"Scan Completed at {completed_timestamp} | "
                        f"elapsed={poll_elapsed:.3f}s",
                    )
                    self._emit_session_diagnostics(scan_diagnostics)

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
                    self._emit_diagnostic(
                        "retry_timeout",
                        f"{start_message} | {diagnostic_text}"
                        f"ERROR={type(exc).__name__}: {exc} | "
                        f"Scan Ended at {completed_timestamp} | "
                        f"elapsed={poll_elapsed:.3f}s | "
                        f"connected={session.is_connected} ready={session.is_ready}",
                    )
                    self._emit_session_diagnostics(scan_diagnostics)

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

            # EL30V2 validated battery telemetry:
            #   R6003 = pack voltage, raw / 100 V
            #   R6004 = current magnitude, raw / 10 A
            #   R6009 = flow state: 0 idle, 1 charging, 2 discharging
            self._telemetry.battery_voltage = float(values[6003]) / 100.0
            self._telemetry.battery_current = float(values[6004]) / 10.0
            self._telemetry.battery_flow = {
                0: "Idle",
                1: "Charging",
                2: "Discharging",
            }.get(int(values[6009]), f"Unknown ({int(values[6009])})")
            self._telemetry.connected = True

    def _apply_temperature_block(self, values: dict[int, int]):
        with self._lock:
            self._telemetry.temperature_c = float(values[1153]) / 10.0
            raw = int(values.get(6350, 0)) & 0xFFFF
            self._telemetry.fan_raw = raw
            self._telemetry.fan_state = "Off" if raw == 0 else "Active"
            self._telemetry.connected = True

    def _apply_lifetime_energy_block(self, values: dict[int, int]):
        with self._lock:
            # R154 matches the BLUETTI app's "PV Generation" value and is
            # stored in tenths of a kWh (for example raw 31 = 3.1 kWh).
            self._telemetry.lifetime_energy_kwh = float(values[154]) / 10.0
            self._telemetry.connected = True

    def _apply_fault_status_block(self, values: dict[int, int]):
        with self._lock:
            r133 = int(values.get(133, 0)) & 0xFFFF
            r137 = int(values.get(137, 0)) & 0xFFFF
            active = bool(r133 or r137)
            self._telemetry.fault_active = active
            self._telemetry.fault_summary = "Fault Active" if active else "No Faults"
            self._telemetry.connected = True

    async def _process_pending_control_write(self, session):
        try:
            field, value, label, readback_register, readback_count = (
                self._control_queue.get_nowait()
            )
        except queue.Empty:
            return

        try:
            await session.write(field, value)
            readback = await session.read_registers(readback_register, readback_count)
            try:
                scan_diagnostics = session.consume_scan_diagnostics()
            except Exception:
                scan_diagnostics = []

            if field in ("ctrl_ac", "ctrl_dc"):
                self._apply_control_state_block(readback)
                actual = (
                    self._telemetry.ac_output_enabled
                    if field == "ctrl_ac"
                    else self._telemetry.dc_output_enabled
                )
                if actual != bool(value):
                    raise RuntimeError(
                        f"{label} read-back did not match requested state "
                        f"(requested={bool(value)}, actual={actual})"
                    )
                requested_text = "ON" if bool(value) else "OFF"
                actual_text = "ON" if actual else "OFF"
                diagnostic_category = "control_state"

            elif field == "ctrl_charging_mode":
                self._apply_settings_block(readback)
                actual_raw = int(readback[2020])
                if actual_raw != int(value):
                    raise RuntimeError(
                        f"{label} read-back did not match requested mode "
                        f"(requested={self._charging_mode(value)}, "
                        f"actual={self._charging_mode(actual_raw)})"
                    )
                requested_text = self._charging_mode(value)
                actual_text = self._charging_mode(actual_raw)
                diagnostic_category = "settings"

            else:
                raise RuntimeError(f"Unsupported queued write field: {field}")

            self._emit_diagnostic(
                diagnostic_category,
                f"{self._console_timestamp()} {label} WRITE "
                f"requested={requested_text} readback={actual_text} "
                f"Raw={self._format_raw_registers(readback)}",
            )
            self._emit_session_diagnostics(scan_diagnostics)
            with self._lock:
                self._status_message = f"{label} {actual_text} confirmed."
                self._last_error = ""
        except Exception as exc:
            try:
                scan_diagnostics = session.consume_scan_diagnostics()
            except Exception:
                scan_diagnostics = []
            self._emit_diagnostic(
                "retry_timeout",
                f"{self._console_timestamp()} {label} WRITE ERROR={type(exc).__name__}: {exc}",
            )
            self._emit_session_diagnostics(scan_diagnostics)
            with self._lock:
                self._last_error = f"{label} write failed: {exc}"
                self._status_message = f"{label} write failed; polling will verify current state."
            if not session.is_connected or not session.is_ready:
                raise

    async def _refresh_device_info(self, session, device):
        """Read static identity/network information once per successful connection."""
        info = CommunityDeviceInfo(
            model=self.model,
            device_name=(getattr(device, "name", None) or self._device_name or ""),
            ble_address=(getattr(device, "address", None) or self._address or ""),
            authenticated=bool(session.is_ready),
        )
        try:
            identity = await session.read_registers(110, 10)
            info.model = self._decode_ascii_words(identity, 110, 6, swap_bytes=True) or self.model
            info.device_serial = self._decode_serial_words(identity, 116, 4)
        except Exception as exc:
            self._emit_diagnostic("connection", f"Device identity read unavailable: {exc}")
        try:
            board = await session.read_registers(11006, 4)
            info.communication_board_serial = self._decode_serial_words(board, 11006, 4)
        except Exception as exc:
            self._emit_diagnostic("connection", f"Communication-board SN unavailable: {exc}")
        try:
            net = await session.read_registers(11020, 13)
            info.wifi_ip = self._decode_ipv4(net, 11020)
            info.wifi_gateway = self._decode_ipv4(net, 11022)
            info.wifi_subnet_mask = self._decode_ipv4(net, 11024)
            raw_rssi = int(net.get(11026, 0)) & 0xFFFF
            info.wifi_rssi = raw_rssi - 0x10000 if raw_rssi & 0x8000 else raw_rssi
            info.wifi_mac = self._decode_mac(net, 11027)
            info.ble_mac = self._decode_ble_mac(net, 11030)
            info.wifi_status = "Connected" if info.wifi_rssi not in (None, 0) and info.wifi_ip not in ("", "0.0.0.0") else "Not connected"
        except Exception as exc:
            self._emit_diagnostic("connection", f"Network information unavailable: {exc}")
        try:
            ssid_regs = await session.read_registers(12002, 6)
            info.wifi_ssid = self._decode_ascii_words(ssid_regs, 12002, 6, swap_bytes=True)
        except Exception:
            pass
        with self._lock:
            self._device_info = info
            self._device_name = info.device_name

    def _emit_session_diagnostics(self, messages):
        for message in messages or []:
            upper = str(message).upper()
            if "ORPHAN_RX" in upper:
                category = "unsolicited"
            elif "UNEXPECTED" in upper or "MALFORMED" in upper or "FOREIGN" in upper:
                category = "unexpected"
            elif "TIMEOUT" in upper or "RETRY" in upper:
                category = "retry_timeout"
            else:
                category = "unexpected"
            rendered = self._format_session_diagnostic(category, str(message))
            self._emit_diagnostic(category, rendered)

    def _format_session_diagnostic(self, category: str, message: str) -> str:
        if category not in ("unexpected", "unsolicited"):
            return message

        config = self._diagnostic_config or {}
        mode = str(config.get("message_format") or "raw").lower()
        if mode == "raw":
            return message

        register_view = self._build_register_view(message)
        if not register_view:
            return message
        if mode == "registers":
            # Keep the useful request/timestamp prefix but omit the very long raw
            # ResponseHex/DataHex fields.
            prefix = message.split(" ResponseHex=", 1)[0]
            if " DataHex=" in prefix:
                prefix = prefix.split(" DataHex=", 1)[0]
            return prefix + "\n" + register_view
        if mode == "both":
            return message + "\n" + register_view
        return message

    def _build_register_view(self, message: str) -> str:
        marker = "DataHex="
        if marker not in message:
            return ""
        data_text = message.split(marker, 1)[1].strip()
        # DataHex is the final field in current DeviceSession diagnostics.
        tokens = []
        for token in data_text.split():
            try:
                value = int(token, 16)
            except ValueError:
                break
            if not 0 <= value <= 0xFF:
                break
            tokens.append(value)
        if len(tokens) < 2:
            return ""

        words = []
        pair_count = len(tokens) // 2
        for i in range(pair_count):
            hi = tokens[i * 2]
            lo = tokens[i * 2 + 1]
            words.append((hi << 8) | lo)

        group_size = int((self._diagnostic_config or {}).get("registers_per_group") or 10)
        group_size = max(1, min(group_size, 32))
        lines = [f"REGISTER_VIEW words={len(words)} bytes={len(tokens)} group={group_size}"]
        for start in range(0, len(words), group_size):
            chunk = words[start:start + group_size]
            end = start + len(chunk) - 1
            hex_values = " ".join(f"{word:04X}" for word in chunk)
            dec_values = " ".join(f"{word:5d}" for word in chunk)
            ascii_values = []
            for word in chunk:
                pair = word.to_bytes(2, "big")
                ascii_values.append("".join(chr(b) if 32 <= b <= 126 else "." for b in pair))
            ascii_text = " ".join(ascii_values)
            label = f"W{start:03d}-{end:03d}"
            lines.append(f"{label} HEX   {hex_values}")
            lines.append(f"{label} DEC   {dec_values}")
            lines.append(f"{label} ASCII {ascii_text}")
        if len(tokens) % 2:
            lines.append(f"TRAILING_BYTE HEX={tokens[-1]:02X} DEC={tokens[-1]}")
        return "\n".join(lines)

    def _emit_diagnostic(self, category: str, message: str):
        config = self._diagnostic_config or {}
        if not config.get("enabled", True):
            return
        categories = config.get("categories", {}) or {}
        if not categories.get(category, False):
            return
        line = message.rstrip()
        timestamp = self._console_timestamp()
        # Prefix every physical output line, including multiline register views,
        # so copied console/file excerpts always retain timing context.
        stamped_line = "\n".join(
            f"{timestamp} {part}" for part in line.splitlines()
        )
        if config.get("to_console", False):
            print(stamped_line, flush=True)
        if config.get("to_file", False):
            try:
                with self._diagnostic_lock:
                    if self._diagnostic_file is None:
                        directory = Path(config.get("log_directory") or "logs")
                        directory.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        self._diagnostic_file_path = directory / f"bluetti_gui_diagnostics_{stamp}.txt"
                        self._diagnostic_file = self._diagnostic_file_path.open("a", encoding="utf-8", buffering=1)
                        started = self._console_timestamp()
                        self._diagnostic_file.write(f"{started} [system] BLUETTI GUI diagnostics started\n")
                    categorized_line = "\n".join(
                        f"{timestamp} [{category}] {part}" for part in line.splitlines()
                    )
                    self._diagnostic_file.write(f"{categorized_line}\n")
                    self._diagnostic_file.flush()
            except Exception as exc:
                print(f"{self._console_timestamp()} Diagnostics log write failed: {exc}", flush=True)

    @staticmethod
    def _decode_serial_words(values, start, count):
        words = [int(values[start + i]) & 0xFFFF for i in range(count)]
        raw = b"".join(word.to_bytes(2, "big") for word in reversed(words))
        return str(int.from_bytes(raw, "big"))

    @staticmethod
    def _decode_ascii_words(values, start, count, swap_bytes=False):
        raw = bytearray()
        for i in range(count):
            word = int(values[start + i]) & 0xFFFF
            b = word.to_bytes(2, "big")
            raw.extend(b[::-1] if swap_bytes else b)
        return bytes(raw).replace(b"\x00", b"").decode("ascii", "ignore").strip()

    @staticmethod
    def _decode_ipv4(values, start):
        octets = []
        for i in range(2):
            word = int(values[start + i]) & 0xFFFF
            octets.extend([word & 0xFF, (word >> 8) & 0xFF])
        return ".".join(str(x) for x in octets)

    @staticmethod
    def _decode_mac(values, start):
        octets = []
        for i in range(3):
            word = int(values[start + i]) & 0xFFFF
            octets.extend([word & 0xFF, (word >> 8) & 0xFF])
        return ":".join(f"{x:02X}" for x in octets)

    @staticmethod
    def _decode_ble_mac(values, start):
        octets = []
        for i in range(3):
            word = int(values[start + i]) & 0xFFFF
            octets.extend([word & 0xFF, (word >> 8) & 0xFF])
        octets.reverse()
        return ":".join(f"{x:02X}" for x in octets)

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
            lifetime_energy_kwh=self._optional_number(data.get("power_generation")),
            temperature_c=self._optional_number(data.get("temperature")),
            fan_state="Unknown",
            fan_raw=None,
            fault_active=False,
            fault_summary="No Faults",
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
        # Do not carry a stale output-control request across a disconnect/reconnect.
        try:
            while True:
                self._control_queue.get_nowait()
        except queue.Empty:
            pass
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
                lifetime_energy_kwh=previous.lifetime_energy_kwh,
                temperature_c=previous.temperature_c,
                fan_state=previous.fan_state,
                fan_raw=previous.fan_raw,
                fault_active=previous.fault_active,
                fault_summary=previous.fault_summary,
                ac_output_enabled=previous.ac_output_enabled,
                dc_output_enabled=previous.dc_output_enabled,
                charging_mode=previous.charging_mode,
            )
            self._last_error = message
            self._status_message = f"Community BLE: {message}"
