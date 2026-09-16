from __future__ import annotations

import asyncio
import importlib
import os
import queue as thread_queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
DEVICE_NAME_UUID = "00002a00-0000-1000-8000-00805f9b34fb"


@dataclass
class OfficialTelemetry:
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
    fan_state: str = "Unknown"
    lifetime_energy_kwh: Optional[float] = None
    fault_active: bool = False
    ac_output_enabled: bool = False
    dc_output_enabled: bool = False
    charging_mode: str = "Standard"


@dataclass
class OfficialDeviceInfo:
    model: str = "EL30V2"
    device_name: str = ""
    address: str = ""
    device_serial: str = ""
    communication_board_serial: str = ""
    firmware_version: str = ""
    protocol: str = "Official encrypted BLE"
    backend: str = "Official BLUETTI Library"
    authenticated: bool = False
    wifi_status: str = ""
    wifi_ssid: str = ""
    wifi_ip: str = ""
    wifi_gateway: str = ""
    wifi_subnet_mask: str = ""
    wifi_rssi: Optional[int] = None
    wifi_mac: str = ""
    ble_mac: str = ""


class OfficialBackend:
    """First GUI integration of BLUETTI's official native crypt path.

    v0.2.51 keeps the Community-style optimistic AC/DC/charging-mode feedback
    from v0.2.50 and shortens Official transaction failure recovery. Expanded
    Official now uses the same 0.5-second command timeout used by the mature
    Community path, so an autonomous/unmatched EL30V2 frame cannot stall a poll
    or control readback for multiple seconds. Authorization-file handling remains
    as introduced in v0.2.48.

    BLUETTI_OFFICIAL_DIR may still be used as an advanced local override for the
    authorization working directory.
    """

    supports_writes = False
    supports_ac_output_writes = False
    supports_dc_output_writes = False
    supports_charging_mode_writes = False

    def __init__(
        self,
        model: str = "EL30V2",
        address: Optional[str] = None,
        device_name: str = "",
        auto_start: bool = True,
        auto_reconnect: bool = True,
        diagnostic_config: Optional[dict] = None,
        poll_seconds: float = 2.0,
        scan_seconds: float = 8.0,
        command_timeout: float = 0.5,
        reconnect_seconds: float = 2.0,
        expanded_validator: bool = False,
    ):
        self.model = model or "EL30V2"
        self._address = (address or "").strip() or None
        self._device_name = device_name or ""
        self.auto_reconnect = bool(auto_reconnect)
        self.poll_seconds = max(0.5, float(poll_seconds))
        self.scan_seconds = max(1.0, float(scan_seconds))
        self.command_timeout = max(0.5, float(command_timeout))
        self.reconnect_seconds = max(0.5, float(reconnect_seconds))
        self._diagnostic_config = dict(diagnostic_config or {})
        self.expanded_validator = bool(expanded_validator)

        # Writes are intentionally available ONLY in Expanded Validator mode.
        # The public write surface is hard-limited to the three controls already
        # validated on EL30V2: R2011 AC, R2012 DC, and R2020 Charging Mode.
        self.supports_writes = self.expanded_validator
        self.supports_ac_output_writes = self.expanded_validator
        self.supports_dc_output_writes = self.expanded_validator
        self.supports_charging_mode_writes = self.expanded_validator
        self._control_queue = thread_queue.Queue()

        # Desired values waiting for write/readback verification. While a control
        # is pending, older FC03 polling results for that same register must not
        # overwrite the optimistic GUI state. Otherwise the button visibly flips
        # ON -> OFF -> ON even though the command is simply still in flight.
        self._pending_controls = {}

        # After a write verifies, the EL30V2 can briefly report the previous control
        # state again on subsequent polls before settling. Keep the requested state
        # latched in the GUI until we observe it consistently, with a short timeout
        # so genuine later device changes are still reflected.
        self._control_holds = {}
        self._control_hold_seconds = 5.0
        self._control_hold_required_matches = 2

        # Expanded Official currently uses individual FC03 transactions because the
        # V4 validator entries are single-register. Keep the most visible/control
        # telemetry on a faster cadence and stagger slower-changing telemetry.
        #
        # poll_seconds remains the user's/general backend cadence hint, but Expanded
        # mode is allowed to refresh high-priority controls/power more frequently.
        self._fast_poll_seconds = min(self.poll_seconds, 1.0)
        self._soc_poll_seconds = max(self._fast_poll_seconds, min(self.poll_seconds, 2.0))
        self._battery_poll_seconds = max(1.5, self._fast_poll_seconds)
        self._thermal_poll_seconds = 4.0
        self._fault_poll_seconds = 4.0
        self._pv_generation_poll_seconds = 10.0

        # The Official native module is installed in the active Python environment.
        # BLUETTI's library expects the device authorization CSV in the application's
        # working directory. Use the repository root (beside app.py) as that directory
        # regardless of where the user launched Python from.
        repo_root = Path(__file__).resolve().parent.parent
        self.official_dir = Path(
            os.environ.get("BLUETTI_OFFICIAL_DIR", str(repo_root))
        ).resolve()

        # Expanded Validator artifacts remain development/research files and are not
        # part of the public GUI repository. Keep their location separate from the
        # authorization CSV location.
        default_research_dir = Path.home() / "bluetti-official-library-tests"
        self.official_research_dir = Path(
            os.environ.get("BLUETTI_OFFICIAL_RESEARCH_DIR", str(default_research_dir))
        ).resolve()

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._telemetry = OfficialTelemetry(model=self.model)
        self._device_info = OfficialDeviceInfo(
            model=self.model,
            device_name=self._device_name,
            address=self._address or "",
            ble_mac=self._address or "",
        )
        if self.expanded_validator:
            self._device_info.protocol = "Official encrypted BLE (expanded validator)"
            self._device_info.backend = "Official BLUETTI Library — Expanded Validator"
        self._last_error = ""
        self._status_message = (
            "Official BLUETTI expanded-validator backend ready"
            if self.expanded_validator
            else "Official BLUETTI backend ready"
        )
        self._worker = None

        if auto_start:
            self._start_worker()

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

    def configure_diagnostics(self, config: dict):
        with self._lock:
            self._diagnostic_config = dict(config or {})

    def get_telemetry(self) -> OfficialTelemetry:
        with self._lock:
            t = self._telemetry
            return OfficialTelemetry(**t.__dict__)

    def get_device_info(self) -> OfficialDeviceInfo:
        with self._lock:
            return OfficialDeviceInfo(**self._device_info.__dict__)

    def set_active_poll_groups(self, groups):
        # Present for compatibility with the GUI's demand-driven backend API.
        # Backend polling remains internal; widgets consume normalized telemetry only.
        return None

    def set_ac_output(self, enabled: bool):
        self._enqueue_control_write(2011, 1 if enabled else 0, "AC output")

    def set_dc_output(self, enabled: bool):
        self._enqueue_control_write(2012, 1 if enabled else 0, "DC output")

    def set_charging_mode(self, mode: str):
        mapping = {
            "standard": 0,
            "silent": 1,
            "turbo": 2,
        }
        key = str(mode or "").strip().lower()
        if key not in mapping:
            self._set_status(f"Official Expanded: unsupported charging mode {mode!r}")
            return
        self._enqueue_control_write(2020, mapping[key], "Charging Mode")

    def _enqueue_control_write(self, register: int, value: int, label: str):
        if not self.expanded_validator:
            self._set_status(
                "Official Stock backend is read-only; select Expanded Validator for controls"
            )
            return

        with self._lock:
            connected = bool(self._telemetry.connected)

        if not connected:
            self._set_status(f"Official Expanded: cannot change {label} while disconnected")
            return

        # Only these three validated controls are ever accepted by the GUI.
        allowed = {
            2011: {0, 1},
            2012: {0, 1},
            2020: {0, 1, 2},
        }
        if register not in allowed or int(value) not in allowed[register]:
            self._set_status(
                f"Official Expanded: rejected unsupported control write R{register}={value}"
            )
            return

        # Match the Community backend's optimistic-control behavior exactly:
        # mark the requested value pending and immediately update normalized
        # telemetry so the on-screen control responds at click time. While the
        # command is pending, normal polls for this register are suppressed.
        # After verified readback, the short hold below rejects stale rebound
        # polls until normal device telemetry has caught up.
        with self._lock:
            self._pending_controls[int(register)] = int(value)
            if int(register) == 2011:
                self._telemetry.ac_output_enabled = bool(value)
            elif int(register) == 2012:
                self._telemetry.dc_output_enabled = bool(value)
            elif int(register) == 2020:
                self._telemetry.charging_mode = {
                    0: "Standard",
                    1: "Silent",
                    2: "Turbo",
                }.get(int(value), f"Unknown ({value})")

        self._control_queue.put((int(register), int(value), str(label)))
        self._set_status(f"Official Expanded: queued {label} change")

    def close(self):
        self._stop_event.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=3.0)

    def _start_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_main,
            name="BluettiOfficialBackend",
            daemon=True,
        )
        self._worker.start()

    def _worker_main(self):
        try:
            asyncio.run(self._async_worker())
        except Exception as exc:
            self._record_failure(str(exc))

    async def _async_worker(self):
        while not self._stop_event.is_set():
            try:
                await self._run_session()
                if not self.auto_reconnect:
                    return
            except Exception as exc:
                self._record_failure(str(exc))
                if not self.auto_reconnect or self._stop_event.is_set():
                    return
                await self._sleep_interruptibly(self.reconnect_seconds)

    async def _run_session(self):
        if not self._address:
            raise RuntimeError("No saved BLE address is configured for the Official backend")

        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("bleak is not installed in this Python environment") from exc

        crypto_module = self._load_official_crypto_module()
        crypto = self._create_crypto_instance(crypto_module)
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        self._set_status(f"Connecting to {self.model} with Official BLUETTI library" + (" — Expanded Validator..." if self.expanded_validator else "..."))
        client = BleakClient(self._address)
        try:
            await client.connect()
            if not client.is_connected:
                raise RuntimeError("Official BLE connection failed")

            try:
                raw_name = await client.read_gatt_char(DEVICE_NAME_UUID)
                device_name = bytes(raw_name).decode("ascii", errors="replace").rstrip("\x00")
            except Exception:
                device_name = self._device_name

            def notification_handler(sender, data):
                try:
                    queue.put_nowait(bytes(data))
                except Exception:
                    pass

            await client.start_notify(NOTIFY_UUID, notification_handler)
            self._set_status("Official BLE connected — authenticating...")

            await self._authenticate(client, crypto, queue)
            self._drain_queue(queue)

            with self._lock:
                self._device_name = device_name or self._device_name
                self._device_info.device_name = self._device_name
                self._device_info.address = self._address or ""
                self._device_info.ble_mac = self._address or ""
                self._device_info.authenticated = True
                self._last_error = ""
                self._status_message = ("Official BLUETTI encrypted connection established — Expanded Validator" if self.expanded_validator else "Official BLUETTI encrypted connection established")

            # Stock V1.0.0-W validator-safe identity reads that we already proved
            # in the Official research project. Identity is static, so read it
            # once per successful BLE/authentication session.
            try:
                model_words = await self._read_register(client, crypto, queue, 110, 6)
                decoded_model = self._decode_word_swapped_ascii(
                    [model_words.get(address, 0) for address in range(110, 116)]
                )
                if decoded_model:
                    with self._lock:
                        self.model = decoded_model
                        self._telemetry.model = decoded_model
                        self._device_info.model = decoded_model
            except Exception:
                # Identity is helpful but must never prevent live telemetry.
                pass

            try:
                serial_words = await self._read_register(client, crypto, queue, 116, 4)
                serial_number = self._decode_reversed_word_integer(
                    [serial_words.get(address, 0) for address in range(116, 120)]
                )
                if serial_number:
                    with self._lock:
                        self._device_info.device_serial = str(serial_number)
            except Exception:
                pass

            if self.expanded_validator:
                now = time.monotonic()
                next_fast = now
                next_soc = now
                next_battery = now
                next_thermal = now
                next_fault = now
                next_pv = now

                fast_addresses = (140, 142, 144, 146, 2011, 2012, 2020)
                battery_addresses = (6003, 6004, 6009)
                thermal_addresses = (1153, 6350)
                fault_addresses = (133, 137)

                while not self._stop_event.is_set():
                    if not client.is_connected:
                        raise RuntimeError("Official BLE connection was lost")

                    # Controls always have priority over polling.
                    await self._process_pending_writes(client, crypto, queue)

                    now = time.monotonic()
                    updates = {}

                    if now >= next_fast:
                        updates.update(
                            await self._read_expanded_addresses(
                                client, crypto, queue, fast_addresses
                            )
                        )
                        # Target cadence: if reads overrun, do not add an extra
                        # full sleep; schedule from the previous target and catch up.
                        next_fast = max(
                            next_fast + self._fast_poll_seconds,
                            time.monotonic(),
                        )

                    now = time.monotonic()
                    if now >= next_soc:
                        soc = await self._read_register(client, crypto, queue, 102, 1)
                        if 102 not in soc:
                            raise RuntimeError("Official R102 read returned no SOC value")
                        updates["soc"] = max(0, min(100, int(soc[102])))
                        next_soc = max(
                            next_soc + self._soc_poll_seconds,
                            time.monotonic(),
                        )

                    now = time.monotonic()
                    if now >= next_battery:
                        updates.update(
                            await self._read_expanded_addresses(
                                client, crypto, queue, battery_addresses
                            )
                        )
                        next_battery = max(
                            next_battery + self._battery_poll_seconds,
                            time.monotonic(),
                        )

                    now = time.monotonic()
                    if now >= next_thermal:
                        updates.update(
                            await self._read_expanded_addresses(
                                client, crypto, queue, thermal_addresses
                            )
                        )
                        next_thermal = max(
                            next_thermal + self._thermal_poll_seconds,
                            time.monotonic(),
                        )

                    now = time.monotonic()
                    if now >= next_fault:
                        updates.update(
                            await self._read_expanded_addresses(
                                client, crypto, queue, fault_addresses
                            )
                        )
                        next_fault = max(
                            next_fault + self._fault_poll_seconds,
                            time.monotonic(),
                        )

                    now = time.monotonic()
                    if now >= next_pv:
                        pv_raw = await self._safe_read_one(client, crypto, queue, 154)
                        if pv_raw is not None:
                            updates["lifetime_energy_kwh"] = float(pv_raw) / 10.0
                        next_pv = max(
                            next_pv + self._pv_generation_poll_seconds,
                            time.monotonic(),
                        )

                    if updates:
                        with self._lock:
                            # Final stale-control guard. A fast-poll batch can read
                            # R2011/R2012 immediately before a user control request,
                            # then finish after the optimistic state has already been
                            # applied. Re-check pending/hold state at the actual
                            # telemetry commit so that an in-flight pre-click value
                            # cannot overwrite the newer requested state.
                            now_commit = time.monotonic()
                            control_fields = {
                                "ac_output_enabled": 2011,
                                "dc_output_enabled": 2012,
                                "charging_mode": 2013,
                            }
                            for field_name, register in control_fields.items():
                                if field_name not in updates:
                                    continue

                                desired = self._pending_controls.get(register)
                                hold = self._control_holds.get(register)
                                if desired is None and hold is not None:
                                    if now_commit < float(hold.get("expires", 0.0)):
                                        desired = int(hold["value"])

                                if desired is not None:
                                    # The optimistic/held value already lives in
                                    # self._telemetry. Never commit a contradictory
                                    # value captured by a poll that began earlier.
                                    if register in (2011, 2012):
                                        polled = 1 if bool(updates[field_name]) else 0
                                    else:
                                        mode_to_value = {
                                            "Standard": 0,
                                            "Silent": 1,
                                            "Turbo": 2,
                                        }
                                        polled = mode_to_value.get(
                                            str(updates[field_name]), -1
                                        )
                                    if int(polled) != int(desired):
                                        updates.pop(field_name, None)

                            self._telemetry.connected = True
                            for field_name, value in updates.items():
                                setattr(self._telemetry, field_name, value)
                            self._last_error = ""
                            self._status_message = (
                                f"Official BLUETTI connected — Expanded Validator — live telemetry from {self.model}"
                            )

                    # Do not append a fixed two-second sleep after doing all the
                    # work. Sleep only until the next scheduled item, while still
                    # servicing queued controls every 50 ms.
                    next_due = min(
                        next_fast,
                        next_soc,
                        next_battery,
                        next_thermal,
                        next_fault,
                        next_pv,
                    )
                    delay = max(0.0, next_due - time.monotonic())
                    await self._sleep_with_write_processing(
                        client, crypto, queue, min(delay, 0.10)
                    )

            else:
                # Stock Official remains intentionally simple/read-only.
                poll_index = 0
                while not self._stop_event.is_set():
                    if not client.is_connected:
                        raise RuntimeError("Official BLE connection was lost")

                    soc = await self._read_register(client, crypto, queue, 102, 1)
                    if 102 not in soc:
                        raise RuntimeError("Official R102 read returned no SOC value")

                    pv_generation = None
                    if poll_index == 0 or poll_index % 5 == 0:
                        pv_raw = await self._safe_read_one(client, crypto, queue, 154)
                        if pv_raw is not None:
                            pv_generation = float(pv_raw) / 10.0

                    with self._lock:
                        self._telemetry.connected = True
                        self._telemetry.soc = max(0, min(100, int(soc[102])))
                        if pv_generation is not None:
                            self._telemetry.lifetime_energy_kwh = pv_generation
                        self._last_error = ""
                        self._status_message = (
                            f"Official BLUETTI connected — live SOC/PV from {self.model}"
                        )

                    poll_index += 1
                    await self._sleep_interruptibly(self.poll_seconds)
        finally:
            with self._lock:
                self._telemetry.connected = False
                self._device_info.authenticated = False
            try:
                if client.is_connected:
                    await client.stop_notify(NOTIFY_UUID)
            except Exception:
                pass
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:
                pass

    def _load_official_crypto_module(self):
        directory = self.official_dir
        if not directory.exists():
            raise RuntimeError(
                f"Official authorization directory was not found: {directory}. "
                "The BLUETTI Official backend requires a device authorization CSV "
                "obtained from BLUETTI. Place the CSV beside app.py in the GUI "
                "repository root. Set BLUETTI_OFFICIAL_DIR only if you intentionally "
                "use another authorization working directory."
            )

        csv_files = list(directory.glob("*.csv"))
        if not csv_files:
            raise RuntimeError(
                f"No BLUETTI authorization CSV was found in {directory}. "
                "Request the Official Library authorization file from BLUETTI and "
                "place the CSV in this directory."
            )

        if self.expanded_validator:
            sandbox = self.official_research_dir / "sandbox_native_el30v2_expanded_v4"
            native = sandbox / "_bluetti_crypt.pyd"
            if not native.exists():
                raise RuntimeError(
                    f"Expanded validator sandbox was not found: {native}. "
                    "Build/copy the validated EL30V2 expanded sandbox into the Official "
                    "research directory before selecting Expanded Validator."
                )

            # Native extension modules are process-global once imported. If a Stock
            # Official session already loaded _bluetti_crypt, require a restart
            # rather than attempting an unsafe unload/reload of the extension.
            loaded_native = sys.modules.get("_bluetti_crypt")
            if loaded_native is not None:
                loaded_path = str(getattr(loaded_native, "__file__", "") or "")
                if str(sandbox).lower() not in loaded_path.lower():
                    raise RuntimeError(
                        "Stock Official _bluetti_crypt is already loaded in this GUI "
                        "process. Restart the GUI after selecting Expanded Validator."
                    )

            loaded_wrapper = sys.modules.get("bluetti_crypt")
            if loaded_wrapper is not None and loaded_native is None:
                raise RuntimeError(
                    "bluetti_crypt is already loaded without the expanded native "
                    "module. Restart the GUI after selecting Expanded Validator."
                )

            sandbox_text = str(sandbox)
            added = False
            try:
                if sandbox_text not in sys.path:
                    sys.path.insert(0, sandbox_text)
                    added = True

                # Force the native module to resolve from the expanded sandbox
                # before the stock wrapper imports it.
                if "_bluetti_crypt" not in sys.modules:
                    importlib.import_module("_bluetti_crypt")

                if "bluetti_crypt" in sys.modules:
                    return sys.modules["bluetti_crypt"]
                return importlib.import_module("bluetti_crypt")
            except ImportError as exc:
                raise RuntimeError(
                    f"The expanded BLUETTI crypt sandbox could not be loaded: {exc}"
                ) from exc
            finally:
                if added:
                    try:
                        sys.path.remove(sandbox_text)
                    except ValueError:
                        pass

        # Stock mode: import BLUETTI's installed crypt package unchanged.
        loaded_native = sys.modules.get("_bluetti_crypt")
        if loaded_native is not None:
            loaded_path = str(getattr(loaded_native, "__file__", "") or "")
            if "sandbox_native_el30v2_expanded_v4" in loaded_path.lower():
                raise RuntimeError(
                    "Expanded Validator _bluetti_crypt is already loaded in this GUI "
                    "process. Restart the GUI after selecting Stock Official."
                )

        try:
            return importlib.import_module("bluetti_crypt")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The BLUETTI Official crypt module is not installed in this Python "
                "environment. Install the BLUETTI-provided Official Python crypt "
                "package/module before using the Official backend."
            ) from exc
        except ImportError as exc:
            raise RuntimeError(
                f"The BLUETTI Official crypt module could not be loaded: {exc}"
            ) from exc

    def _create_crypto_instance(self, module):
        old_cwd = Path.cwd()
        try:
            os.chdir(self.official_dir)
            return module.BluettiCrypt()
        finally:
            os.chdir(old_cwd)

    async def _authenticate(self, client, crypto, queue):
        sn_request_sent = False
        for _ in range(30):
            try:
                data = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("Timed out waiting for Official authentication data") from exc

            response, status = crypto.ble_crypt_link_handler(data)

            if status == 3:
                if not sn_request_sent:
                    request = self._make_read_request(11006, 4)
                    encrypted = bytes(crypto.encrypt_data(request))
                    if not encrypted:
                        raise RuntimeError(
                            "Official native validator rejected Communication Board SN request"
                        )
                    await client.write_gatt_char(WRITE_UUID, encrypted)
                    sn_request_sent = True
                continue

            if status == 4:
                return

            if response:
                await client.write_gatt_char(WRITE_UUID, bytes(response))

        raise RuntimeError("Official authentication did not reach status 4")

    async def _read_register(self, client, crypto, queue, start: int, count: int):
        self._drain_queue(queue)
        request = self._make_read_request(start, count)
        encrypted = bytes(crypto.encrypt_data(request))
        if not encrypted:
            raise RuntimeError(
                f"Official native validator rejected R{start} count {count}"
            )

        await client.write_gatt_char(WRITE_UUID, encrypted)
        deadline = asyncio.get_running_loop().time() + self.command_timeout

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeError(f"Timed out waiting for Official R{start} response")
            packet = await asyncio.wait_for(queue.get(), timeout=remaining)
            decrypted = bytes(crypto.decrypt_data(packet))
            values = self._parse_read_response(decrypted, start, count)
            if values is not None:
                return values
            # Ignore valid autonomous/foreign frames in this first Official
            # backend instead of treating them as the requested response.

    async def _process_pending_writes(self, client, crypto, queue):
        if not self.expanded_validator:
            return

        # Process all controls currently waiting. Writes and reads execute on this
        # same async worker, so the notification queue and native crypto context
        # are never used concurrently.
        while True:
            try:
                register, value, label = self._control_queue.get_nowait()
            except thread_queue.Empty:
                return

            try:
                self._set_status(
                    f"Official Expanded: sending {label} change (R{register}={value})..."
                )
                verified = await self._write_register_verified(
                    client, crypto, queue, register, value
                )
                if not verified:
                    raise RuntimeError(
                        f"readback did not confirm R{register}={value}"
                    )

                self._apply_verified_control(register, value)
                with self._lock:
                    if self._pending_controls.get(register) == value:
                        self._pending_controls.pop(register, None)
                    self._control_holds[register] = {
                        "value": int(value),
                        "matches": 0,
                        "expires": time.monotonic() + self._control_hold_seconds,
                    }
                self._set_status(f"Official Expanded: {label} change verified")
            except Exception as exc:
                # The EL30V2 may apply an FC06 write even when an autonomous frame
                # makes the immediate FC03 verification indeterminate. Do not let
                # that ambiguous verification undo the optimistic GUI state. Move
                # the requested value into the same stale-poll hold used after a
                # verified write. Normal polling continues; contradictory values
                # are suppressed until telemetry catches up or the safety timeout
                # expires. Matching polls release the hold normally.
                with self._lock:
                    if self._pending_controls.get(register) == value:
                        self._pending_controls.pop(register, None)
                    self._control_holds[register] = {
                        "value": int(value),
                        "matches": 0,
                        "expires": time.monotonic() + self._control_hold_seconds,
                    }
                    self._last_error = f"{label} verification indeterminate: {exc}"
                    self._status_message = (
                        f"Official Expanded: {label} verification indeterminate — "
                        "holding requested state while polling continues"
                    )

    async def _write_register_verified(
        self,
        client,
        crypto,
        queue,
        register: int,
        value: int,
    ) -> bool:
        """Send exactly one FC06 request and verify using FC03 readback.

        EL30V2 testing on Expanded V4 proved that the write is applied even though
        no conventional FC06 echo is returned. Therefore we do not spend 300 ms
        waiting for an echo and we never blindly retransmit the write.

        Perform one prompt FC03 readback after the short processing interval.
        If an autonomous/unmatched frame prevents that readback from being
        determined within the 0.5-second transaction timeout, abandon this
        verification attempt and let normal polling continue immediately. The
        FC06 write is never retransmitted.
        """
        self._drain_queue(queue)

        request = self._make_write_single_request(register, value)
        encrypted = bytes(crypto.encrypt_data(request))
        if not encrypted:
            raise RuntimeError(
                f"Official native validator rejected FC06 R{register}={value}"
            )

        await client.write_gatt_char(WRITE_UUID, encrypted)

        # Small processing delay, far shorter than the old 300 ms echo wait.
        await asyncio.sleep(0.05)

        values = await self._read_register(client, crypto, queue, register, 1)
        return values.get(register) == int(value)

    def _apply_verified_control(self, register: int, value: int):
        with self._lock:
            if register == 2011:
                self._telemetry.ac_output_enabled = bool(value)
            elif register == 2012:
                self._telemetry.dc_output_enabled = bool(value)
            elif register == 2020:
                self._telemetry.charging_mode = {
                    0: "Standard",
                    1: "Silent",
                    2: "Turbo",
                }.get(int(value), f"Unknown ({value})")

    @staticmethod
    def _make_write_single_request(register: int, value: int) -> bytes:
        payload = bytes([
            0x01,
            0x06,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])
        crc = OfficialBackend._crc16(payload)
        return payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    @staticmethod
    def _parse_write_single_response(frame: bytes, register: int, value: int) -> bool:
        if len(frame) != 8:
            return False
        if frame[0] != 0x01 or frame[1] != 0x06:
            return False
        if not OfficialBackend._valid_crc(frame):
            return False
        rx_register = int.from_bytes(frame[2:4], "big")
        rx_value = int.from_bytes(frame[4:6], "big")
        return rx_register == int(register) and rx_value == int(value)

    async def _sleep_with_write_processing(
        self, client, crypto, queue, seconds: float
    ):
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end and not self._stop_event.is_set():
            await self._process_pending_writes(client, crypto, queue)
            await asyncio.sleep(min(0.05, max(0.0, end - time.monotonic())))

    async def _safe_read_one(self, client, crypto, queue, address: int):
        try:
            values = await self._read_register(client, crypto, queue, address, 1)
            return values.get(address)
        except Exception:
            return None

    async def _read_expanded_addresses(
        self,
        client,
        crypto,
        queue,
        addresses,
    ):
        """Read only the requested Expanded-V4 telemetry addresses.

        Keeping this subset-based lets the scheduler prioritize live power/control
        values without repeatedly polling slower-changing thermal/fault data.
        """
        raw = {}
        for address in addresses:
            await self._process_pending_writes(client, crypto, queue)
            raw[address] = await self._safe_read_one(
                client, crypto, queue, int(address)
            )

        values = {}

        if raw.get(140) is not None:
            values["dc_output_power"] = float(raw[140])
        if raw.get(142) is not None:
            values["ac_output_power"] = float(raw[142])
        if raw.get(144) is not None:
            values["dc_input_power"] = float(raw[144])
        if raw.get(146) is not None:
            values["ac_input_power"] = float(raw[146])

        if raw.get(1153) is not None:
            values["temperature_c"] = float(raw[1153]) / 10.0

        def filtered_control_value(register: int, polled_value: int):
            now = time.monotonic()
            with self._lock:
                if register in self._pending_controls:
                    return None

                hold = self._control_holds.get(register)
                if hold is None:
                    return int(polled_value)

                desired = int(hold["value"])
                if int(polled_value) == desired:
                    hold["matches"] = int(hold.get("matches", 0)) + 1
                    if hold["matches"] >= self._control_hold_required_matches:
                        self._control_holds.pop(register, None)
                        return desired
                    # Keep displaying the desired state while accumulating stable
                    # confirmations.
                    return None

                # Ignore a brief stale rebound to the previous state after a
                # verified write. Once the grace period expires, release the hold
                # so a real device-side reversal is reflected.
                if now < float(hold["expires"]):
                    hold["matches"] = 0
                    return None

                self._control_holds.pop(register, None)
                return int(polled_value)

        if raw.get(2011) is not None:
            filtered = filtered_control_value(2011, raw[2011])
            if filtered is not None:
                values["ac_output_enabled"] = bool(filtered)

        if raw.get(2012) is not None:
            filtered = filtered_control_value(2012, raw[2012])
            if filtered is not None:
                values["dc_output_enabled"] = bool(filtered)

        if raw.get(2020) is not None:
            filtered = filtered_control_value(2020, raw[2020])
            if filtered is not None:
                values["charging_mode"] = {
                    0: "Standard",
                    1: "Silent",
                    2: "Turbo",
                }.get(int(filtered), f"Unknown ({filtered})")

        if raw.get(6003) is not None:
            values["battery_voltage"] = float(raw[6003]) / 100.0
        if raw.get(6004) is not None:
            values["battery_current"] = float(raw[6004]) / 10.0
        if raw.get(6009) is not None:
            values["battery_flow"] = {
                0: "Idle",
                1: "Charging",
                2: "Discharging",
            }.get(int(raw[6009]), f"Unknown ({raw[6009]})")

        if raw.get(6350) is not None:
            values["fan_state"] = "Off" if int(raw[6350]) == 0 else "Active"

        fault_values = [
            raw[address]
            for address in (133, 137)
            if address in raw and raw[address] is not None
        ]
        if fault_values:
            values["fault_active"] = any(int(value) != 0 for value in fault_values)

        return values

    @staticmethod
    def _parse_read_response(frame: bytes, start: int, count: int):
        expected_bytes = count * 2
        if len(frame) < 5 or frame[0] != 0x01 or frame[1] != 0x03:
            return None
        if frame[2] != expected_bytes:
            return None
        expected_len = 3 + expected_bytes + 2
        if len(frame) != expected_len:
            return None
        if not OfficialBackend._valid_crc(frame):
            return None

        values = {}
        body = frame[3:3 + expected_bytes]
        for i in range(count):
            values[start + i] = int.from_bytes(body[i * 2:i * 2 + 2], "big")
        return values

    @staticmethod
    def _decode_word_swapped_ascii(words) -> str:
        data = bytearray()
        for word in words:
            value = int(word) & 0xFFFF
            data.extend((value & 0xFF, (value >> 8) & 0xFF))
        return bytes(data).decode("ascii", errors="ignore").rstrip("\x00 ").strip()

    @staticmethod
    def _decode_reversed_word_integer(words) -> int:
        value = 0
        for word in reversed(list(words)):
            value = (value << 16) | (int(word) & 0xFFFF)
        return value

    @staticmethod
    def _make_read_request(start: int, count: int) -> bytes:
        payload = bytes([
            0x01,
            0x03,
            (start >> 8) & 0xFF,
            start & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ])
        crc = OfficialBackend._crc16(payload)
        return payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    @staticmethod
    def _crc16(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @staticmethod
    def _valid_crc(frame: bytes) -> bool:
        if len(frame) < 3:
            return False
        expected = int.from_bytes(frame[-2:], "little")
        return OfficialBackend._crc16(frame[:-2]) == expected

    @staticmethod
    def _drain_queue(queue):
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _sleep_interruptibly(self, seconds: float):
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end and not self._stop_event.is_set():
            await asyncio.sleep(min(0.25, max(0.0, end - time.monotonic())))

    def _set_status(self, message: str):
        with self._lock:
            self._status_message = message

    def _record_failure(self, message: str):
        with self._lock:
            self._telemetry.connected = False
            self._device_info.authenticated = False
            self._last_error = message
            self._status_message = f"Official BLUETTI: {message}"
