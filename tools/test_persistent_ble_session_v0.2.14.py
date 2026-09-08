"""
BLUETTI GUI v0.2.14 - persistent encrypted BLE session experiment.

This is a read-only research harness. It deliberately does NOT call
DeviceReader.read(), because read() always stops notifications, disconnects,
and resets the encryption keys in its finally/cleanup path.

Instead it:
  1. discovers the EL30V2 once,
  2. establishes one BLE connection,
  3. starts notifications once,
  4. waits for the normal encryption handshake once,
  5. repeatedly reads the normal polling registers over that same connection,
  6. disconnects only on Ctrl+C, failure, or timeout.

No writes are performed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bleak import BleakScanner
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from bluetti_bt_lib import DeviceReader, DeviceReaderConfig
from bluetti_bt_lib.devices import EL30V2
from bluetti_bt_lib.const import NOTIFY_UUID


MODEL = "EL30V2"
POLL_SECONDS = 5.0
HANDSHAKE_TIMEOUT = 60.0


async def find_device():
    fixed_address = os.environ.get("BLUETTI_BLE_ADDRESS", "").strip()
    if fixed_address:
        print(f"Finding configured BLE address {fixed_address} ...")
        device = await BleakScanner.find_device_by_address(fixed_address, timeout=10)
        if device is None:
            raise RuntimeError("Configured BLE address was not found.")
        return device

    print(f"Scanning once for {MODEL} ...")
    devices = await BleakScanner.discover(timeout=8.0, return_adv=True)

    candidates = []
    for device, adv in devices.values():
        names = [
            getattr(device, "name", None),
            getattr(adv, "local_name", None),
        ]
        names = [n for n in names if n]

        if any(MODEL.upper() in n.upper() for n in names):
            candidates.append((device, adv, names))

    if not candidates:
        raise RuntimeError(f"No {MODEL} advertisement found.")

    candidates.sort(
        key=lambda item: getattr(item[1], "rssi", -9999) or -9999,
        reverse=True,
    )

    device, adv, names = candidates[0]
    print(f"Found: {names[0]}  address={device.address}")
    return device


async def wait_for_encryption(reader: DeviceReader):
    started = time.monotonic()

    while not reader.encryption.is_ready_for_commands:
        if time.monotonic() - started > HANDSHAKE_TIMEOUT:
            raise TimeoutError("Encryption handshake did not finish in time.")
        await asyncio.sleep(0.25)

    print("Encrypted session ready.")


async def read_polling_registers(reader: DeviceReader) -> dict:
    parsed_data = {}

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

    # EL30V2 currently has no expansion packs, but retain the library's
    # normal pack-read behavior for completeness if the device definition
    # ever reports pack polling registers.
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


def value(data, key, default=None):
    return data.get(key, default)


async def main():
    print("BLUETTI persistent BLE session experiment v0.2.14")
    print("READ ONLY - NO WRITES")
    print(f"Repo root: {REPO_ROOT}")
    print(f"Poll interval: {POLL_SECONDS:.0f} seconds")
    print("Press Ctrl+C to stop.\n")

    device = await find_device()

    print("Connecting once ...")
    client = await establish_connection(
        BleakClientWithServiceCache,
        device,
        device.name or MODEL,
        max_attempts=10,
    )
    print("BLE connected.")

    loop = asyncio.get_running_loop()
    reader = DeviceReader(
        device.address,
        EL30V2(),
        loop.create_future,
        config=DeviceReaderConfig(timeout=60, use_encryption=True),
        ble_client=client,
    )

    # Because we bypass DeviceReader.read(), set the already-connected client
    # explicitly and start the reader's existing notification handler once.
    reader.client = client

    try:
        await client.start_notify(NOTIFY_UUID, reader._notification_handler)
        reader.has_notifier = True
        print("Notifications started.")

        # Starting notifications allows the existing BluettiEncryption
        # notification handler to complete the challenge/key exchange.
        await wait_for_encryption(reader)

        cycle = 0
        while True:
            cycle += 1
            started = time.monotonic()

            if not client.is_connected:
                raise RuntimeError("BLE connection was lost.")

            data = await read_polling_registers(reader)

            elapsed = time.monotonic() - started
            print(
                f"#{cycle:03d}  connected={client.is_connected}  "
                f"SOC={value(data, 'total_battery_percent', '--')}%  "
                f"ACin={value(data, 'ac_input_power', '--')}W  "
                f"DCin={value(data, 'dc_input_power', '--')}W  "
                f"ACout={value(data, 'ac_output_power', '--')}W  "
                f"DCout={value(data, 'dc_output_power', '--')}W  "
                f"AC={value(data, 'ctrl_ac', '--')}  "
                f"DC={value(data, 'ctrl_dc', '--')}  "
                f"mode={value(data, 'ctrl_charging_mode', '--')}  "
                f"temp={value(data, 'temperature', '--')}  "
                f"read={elapsed:.2f}s"
            )

            delay = max(0.0, POLL_SECONDS - elapsed)
            await asyncio.sleep(delay)

    finally:
        if reader.has_notifier:
            try:
                await client.stop_notify(NOTIFY_UUID)
            except Exception:
                pass
            reader.has_notifier = False

        if client.is_connected:
            await client.disconnect()

        reader.encryption.reset()
        reader.encrypted_buffer.clear()
        print("\nBLE disconnected and encryption state cleared.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        print(f"\nTEST FAILED: {type(exc).__name__}: {exc}")
        raise
