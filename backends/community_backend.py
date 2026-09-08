from __future__ import annotations

import asyncio
import os
import re
import threading
import time
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

    v0.2.15 keeps one BLE/GATT connection and one encrypted session open while
    telemetry is polled repeatedly. It reconnects only when the link is truly
    lost or a read fails.

    The GUI-facing API remains the same as v0.2.12-v0.2.14.
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
            self._status_message = f"{control} control is read-only in v0.2.15."

    def _worker_main(self):
        try:
            asyncio.run(self._async_worker())
        except Exception as exc:
            self._record_failure(f"Backend worker stopped: {exc}")

    async def _async_worker(self):
        while not self._stop_event.is_set():
            reader = None
            client = None

            try:
                if self.model != "EL30V2":
                    raise RuntimeError(
                        f"v0.2.15 CommunityBackend currently supports only EL30V2, "
                        f"not {self.model}."
                    )

                device = await self._resolve_device()

                self._set_status(f"Connecting to {self.model} over Community BLE...")
                reader, client = await self._open_persistent_session(device)

                self._set_status(
                    f"Community BLE connected — live data from {self.model}"
                )
                await self._poll_session(reader, client)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._record_failure(str(exc))
            finally:
                await self._close_session(reader, client)

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
            from bleak_retry_connector import (
                BleakClientWithServiceCache,
                establish_connection,
            )
            from bluetti_bt_lib import DeviceReader, DeviceReaderConfig
            from bluetti_bt_lib.devices import EL30V2
            from bluetti_bt_lib.const import NOTIFY_UUID
        except ImportError as exc:
            raise RuntimeError(
                f"Community BLE dependency import failed: {exc}"
            ) from exc

        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            getattr(device, "name", None) or self.model,
            max_attempts=10,
        )

        loop = asyncio.get_running_loop()

        reader = DeviceReader(
            getattr(device, "address", self._address),
            EL30V2(),
            loop.create_future,
            config=DeviceReaderConfig(
                timeout=self.read_timeout,
                use_encryption=True,
            ),
            ble_client=client,
        )

        reader.client = client

        await client.start_notify(NOTIFY_UUID, reader._notification_handler)
        reader.has_notifier = True

        started = time.monotonic()
        while not reader.encryption.is_ready_for_commands:
            if self._stop_event.is_set():
                raise RuntimeError("Backend stopping.")

            if not client.is_connected:
                raise RuntimeError(
                    "Bluetooth connection was lost during encryption handshake."
                )

            if time.monotonic() - started > self.read_timeout:
                raise TimeoutError(
                    "Encryption handshake did not finish before timeout."
                )

            await asyncio.sleep(0.25)

        return reader, client

    async def _poll_session(self, reader, client):
        while not self._stop_event.is_set():
            cycle_started = time.monotonic()

            if not client.is_connected:
                raise RuntimeError("Bluetooth connection was lost.")

            data = await self._read_polling_registers(reader)

            if not data:
                raise RuntimeError("Persistent Community BLE read returned no data.")

            telemetry = self._normalize(data)

            with self._lock:
                self._telemetry = telemetry
                self._last_error = ""
                self._status_message = (
                    f"Community BLE connected — live data from {self.model}"
                )

            elapsed = time.monotonic() - cycle_started
            delay = max(0.0, self.poll_seconds - elapsed)
            await self._sleep_interruptibly(delay)

    async def _read_polling_registers(self, reader) -> dict[str, Any]:
        parsed_data: dict[str, Any] = {}

        for register in reader.bluetti_device.get_polling_registers():
            response = await reader._async_send_command(register)

            if not response:
                raise RuntimeError(
                    f"No response reading register block starting at "
                    f"{register.starting_address}."
                )

            body = register.parse_response(response)
            parsed = reader.bluetti_device.parse(register.starting_address, body)
            parsed_data.update(parsed)

        pack_registers = reader.bluetti_device.get_pack_polling_registers()

        for pack in range(1, reader.bluetti_device.max_packs + 1):
            selector = reader.bluetti_device.get_pack_selector(pack)
            response = await reader._async_send_command(selector)

            if not response:
                raise RuntimeError(f"No response selecting battery pack {pack}.")

            await asyncio.sleep(3)

            for register in pack_registers:
                response = await reader._async_send_command(register)

                if not response:
                    raise RuntimeError(
                        f"No response reading pack {pack}, register "
                        f"{register.starting_address}."
                    )

                body = register.parse_response(response)
                parsed = reader.bluetti_device.parse(
                    register.starting_address,
                    body,
                    pack_num=pack,
                )
                parsed_data.update(parsed)

        return parsed_data

    async def _close_session(self, reader, client):
        if reader is not None and client is not None:
            if getattr(reader, "has_notifier", False):
                try:
                    from bluetti_bt_lib.const import NOTIFY_UUID
                    await client.stop_notify(NOTIFY_UUID)
                except Exception:
                    pass
                reader.has_notifier = False

        if client is not None:
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:
                pass

        if reader is not None:
            try:
                reader.encryption.reset()
                reader.encrypted_buffer.clear()
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
