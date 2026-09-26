from __future__ import annotations

import asyncio
import logging
import msvcrt
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bleak import BleakScanner
from bluetti_bt_lib.bluetooth.device_session import DeviceSession, DeviceSessionConfig
from bluetti_bt_lib.devices.ap300 import AP300
from bluetti_bt_lib.registers import ReadableRegisters
from bluetti_bt_lib.registers.DeviceRegister import modbus_crc

VERSION = "0.9.2"
POLL_DELAY_SECONDS = 0.35
MAX_BLOCK = 16

# Confirmed HA aggregate scan area from v0.7. HA aggregate values are exposed on
# slaves 0 and 4. Do not query the AP300/EL30V2 register set on these slaves.
HA_REGISTERS = tuple(range(154, 176))
HA_SLAVES = (0, 4)

# AP300 member routing established during HA testing.
TOP_SLAVE = 1
BOTTOM_SLAVE = 2

# Known-good / known-semantic EL30V2 register set used as the AP300 hypothesis.
# Multi-register identity fields are expanded so every 16-bit register can be
# independently monitored and represented as HEX / decimal / ASCII.
AP300_REGISTERS = tuple(sorted(set(
    [102] + list(range(104, 108)) + list(range(110, 120)) +
    [140, 142, 144, 146, 154, 1153, 1314] +
    [2011, 2012] + list(range(2014, 2022)) +
    list(range(11006, 11010))
)))


@dataclass(frozen=True)
class Target:
    device: str
    slave: int
    registers: tuple[int, ...]

# Short labels approved for live scanner output.
AP300_LABELS = {
    102: "Battery SOC",
    **{r: "Time Remaining" for r in range(104, 108)},
    **{r: "Device Type" for r in range(110, 116)},
    **{r: "Device Serial" for r in range(116, 120)},
    140: "DC Out Watts", 142: "AC Out Watts", 144: "DC In Watts",
    146: "AC In Watts", 154: "Unknown", 1153: "Temperature",
    1314: "AC In Volts", 2011: "AC Out On/Off", 2012: "DC Out On/Off",
    2014: "DC Eco On/Off", 2015: "DC Eco Mode", 2016: "DC Eco Min Watts",
    2017: "AC Eco On/Off", 2018: "AC Eco Mode", 2019: "AC Eco Min Watts",
    2020: "Charging Mode", 2021: "Power Lifting",
    **{r: "Comm Board Serial" for r in range(11006, 11010)},
}
HA_LABELS = {r: "Unknown" for r in HA_REGISTERS}
HA_LABELS[161] = "Inverter On/Off"
HA_LABELS[171] = "HA AC Out On/Off"


def register_label(target: Target, reg: int) -> str:
    return (HA_LABELS if target.device == "HA" else AP300_LABELS).get(reg, "Unknown")


def ctrl_g_available() -> bool:
    """Consume Ctrl+G from the Windows console input buffer when present."""
    if sys.platform != "win32" or not msvcrt.kbhit():
        return False
    ch = msvcrt.getwch()
    return ch == "\x07"  # Ctrl+G / BEL


async def watch_ctrl_g(request_event: asyncio.Event, stop_event: asyncio.Event, pause_event: asyncio.Event):
    """Continuously consume and latch Ctrl+G independently of Modbus polling."""
    while not stop_event.is_set():
        if not pause_event.is_set() and ctrl_g_available():
            request_event.set()
        await asyncio.sleep(0.03)


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


class MonitorSession(DeviceSession):
    pass


def make_read(start: int, count: int, slave: int) -> ReadableRegisters:
    reg = ReadableRegisters(start, count)
    reg.cmd[0] = slave
    crc = modbus_crc(reg.cmd[:-2])
    reg.cmd[-2:] = crc.to_bytes(2, "little")
    return reg


def ascii_byte(value: int) -> str:
    return chr(value) if 32 <= value <= 126 else "."


def value_formats(value: int) -> str:
    hi = (value >> 8) & 0xFF
    lo = value & 0xFF
    return f"HEX=0x{value:04X}  DEC={value:<5}  ASCII='{ascii_byte(hi)}{ascii_byte(lo)}'"


def groups(registers: tuple[int, ...]):
    """Yield contiguous register runs, split at MAX_BLOCK."""
    regs = sorted(set(registers))
    if not regs:
        return
    run = [regs[0]]
    for reg in regs[1:]:
        if reg == run[-1] + 1 and len(run) < MAX_BLOCK:
            run.append(reg)
        else:
            yield run
            run = [reg]
    yield run


async def read_block(session: MonitorSession, slave: int, start: int, count: int, log):
    reg = make_read(start, count, slave)
    try:
        async with session.command_lock:
            response = await session._async_send_command(reg)
        body = reg.parse_response(response)
        if len(body) != count * 2:
            log("READ_ERR", f"slave={slave} R{start}-R{start+count-1} expected_bytes={count*2} got={len(body)}")
            return None
        return [int.from_bytes(body[i:i+2], "big") for i in range(0, len(body), 2)]
    except Exception as exc:
        log("READ_ERR", f"slave={slave} R{start}-R{start+count-1} {type(exc).__name__}: {exc}")
        return None


async def read_register_set(session: MonitorSession, target: Target, log, registers=None):
    values: dict[int, int] = {}
    regs = target.registers if registers is None else tuple(sorted(registers))
    for run in groups(regs):
        block = await read_block(session, target.slave, run[0], len(run), log)
        if block is not None:
            for reg, value in zip(run, block):
                values[reg] = value
        await asyncio.sleep(0.01)
    return values


async def choose_ha(log):
    print("Scanning for Hub A1 / HA...")
    devices = await BleakScanner.discover(timeout=12.0)
    candidates = []
    for d in devices:
        name = (d.name or "").strip()
        log("SCAN_SEEN", f"name={name!r} address={d.address}")
        upper = name.upper()
        if upper == "HA" or upper.startswith("HA") or "HUB" in upper:
            candidates.append(d)
    if not candidates:
        raise RuntimeError("No HA/Hub A1 candidate was discovered.")
    if len(candidates) == 1:
        return candidates[0].name or "HA", candidates[0].address
    print("\nHA/Hub candidates:")
    for i, d in enumerate(candidates, 1):
        print(f"  {i}. {d.name!r}  {d.address}")
    while True:
        try:
            idx = int(input("Select HA device number: ")) - 1
            selected = candidates[idx]
            return selected.name or "HA", selected.address
        except (ValueError, IndexError):
            print("Invalid selection.")


def choose_mode() -> str:
    print("Select scan target:")
    print("  1. HA")
    print("  2. AP300 Top")
    print("  3. AP300 Bottom")
    print("  4. All")
    choices = {"1": "HA", "2": "AP300 Top", "3": "AP300 Bottom", "4": "All"}
    while True:
        choice = input("Selection: ").strip()
        if choice in choices:
            return choices[choice]
        print("Invalid selection.")


def targets_for(mode: str) -> list[Target]:
    ha = [Target("HA", slave, HA_REGISTERS) for slave in HA_SLAVES]
    top = Target("AP300 Top", TOP_SLAVE, AP300_REGISTERS)
    bottom = Target("AP300 Bottom", BOTTOM_SLAVE, AP300_REGISTERS)
    if mode == "HA":
        return ha
    if mode == "AP300 Top":
        return [top]
    if mode == "AP300 Bottom":
        return [bottom]
    return ha + [top, bottom]


def print_initial(target: Target, values: dict[int, int], log):
    print(f"\n{target.device}  SLAVE {target.slave}")
    print("-" * 78)
    for reg in target.registers:
        if reg in values:
            text = f"{target.device:<12} SLAVE {target.slave}  R{reg:<5} [{register_label(target, reg)}]  {value_formats(values[reg])}"
        else:
            text = f"{target.device:<12} SLAVE {target.slave}  R{reg:<5} [{register_label(target, reg)}]  <no response>"
        print(text)
        log("INITIAL", text)


def print_change(scan_no: int, target: Target, reg: int, old: int, new: int, log):
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    header = f"{stamp}  {target.device}  SLAVE {target.slave}  R{reg} [{register_label(target, reg)}]"
    old_line = f"    OLD: {value_formats(old)}"
    new_line = f"    NEW: {value_formats(new)}"
    print(header)
    print(old_line)
    print(new_line)
    log("CHANGE", f"scan={scan_no} device={target.device!r} slave={target.slave} R{reg} label={register_label(target, reg)!r} old=[{value_formats(old)}] new=[{value_formats(new)}]")


def parse_register_spec(raw: str) -> list[int]:
    """Parse R6009, 6003-6009, and comma-separated mixtures."""
    text = raw.strip()
    if not text:
        raise ValueError("No register numbers were entered.")

    result: set[int] = set()
    for item in text.split(","):
        token = item.strip().replace(" ", "")
        if not token:
            raise ValueError("Empty item in register list.")

        if "-" in token:
            if token.count("-") != 1:
                raise ValueError(f"Invalid range: {item.strip()!r}")
            left, right = token.split("-", 1)
            if left[:1].lower() == "r":
                left = left[1:]
            if right[:1].lower() == "r":
                right = right[1:]
            if not left.isdigit() or not right.isdigit():
                raise ValueError(f"Invalid range: {item.strip()!r}")
            start, end = int(left), int(right)
            if start > end:
                raise ValueError(f"Reversed range is not allowed: {item.strip()!r}")
            if start < 0 or end > 65535:
                raise ValueError("Register numbers must be between 0 and 65535.")
            result.update(range(start, end + 1))
        else:
            if token[:1].lower() == "r":
                token = token[1:]
            if not token.isdigit():
                raise ValueError(f"Invalid register: {item.strip()!r}")
            reg = int(token)
            if reg < 0 or reg > 65535:
                raise ValueError("Register numbers must be between 0 and 65535.")
            result.add(reg)

    return sorted(result)


async def monitor_settings(session, targets, available, enabled, previous, log, keyboard_pause):
    """Pause polling and let the user toggle one or more register monitors."""
    # Pause the background console-key consumer while normal input() owns the console.
    keyboard_pause.set()
    await asyncio.sleep(0.05)

    entries = []
    while True:
        print("\n" + "=" * 78)
        print("MONITOR SETTINGS - polling paused")
        print("Toggle one or more entries by number (example: 3,7,12).")
        print("A = add register(s) to monitor for the currently selected target(s).")
        print("    Examples: 6009 | R6009 | 6003-6009 | R6003-R6004, R6009")
        print("Press Enter with no selection to resume scanning.")
        print("=" * 78)
        entries.clear()
        n = 1
        for target in targets:
            key = (target.device, target.slave)
            print(f"\n{target.device}  SLAVE {target.slave}")
            for reg in sorted(available[key]):
                state = "MONITOR" if reg in enabled[key] else "SILENCED"
                print(f"  {n:>3}. [{state:<8}] R{reg:<5} {register_label(target, reg)}")
                entries.append((target, reg))
                n += 1
        raw = input("\nToggle number(s), A to add registers, or Enter to resume: ").strip()
        if raw.lower() == "a":
            spec = input("Register(s) to add: ").strip()
            try:
                regs_to_add = parse_register_spec(spec)
            except ValueError as exc:
                print(f"Invalid register specification: {exc}")
                continue

            newly_added: dict[Target, list[int]] = {}
            for target in targets:
                key = (target.device, target.slave)
                for reg in regs_to_add:
                    if reg not in available[key]:
                        available[key].add(reg)
                        newly_added.setdefault(target, []).append(reg)
                    enabled[key].add(reg)

            print("Added to current session: " + ", ".join(f"R{r}" for r in regs_to_add))
            log("MONITOR", f"session registers added={regs_to_add} targets={[(t.device, t.slave) for t in targets]}")

            # Establish a baseline immediately for newly added registers. Existing
            # registers that were merely re-enabled keep their existing baseline.
            for target, regs in newly_added.items():
                vals = await read_register_set(session, target, log, regs)
                key = (target.device, target.slave)
                previous.setdefault(key, {}).update(vals)
                for reg in regs:
                    if reg in vals:
                        text = f"{target.device:<12} SLAVE {target.slave}  R{reg:<5} [{register_label(target, reg)}]  {value_formats(vals[reg])}"
                    else:
                        text = f"{target.device:<12} SLAVE {target.slave}  R{reg:<5} [{register_label(target, reg)}]  <no response>"
                    print(text)
                    log("ADDED", text)
            continue
        if not raw:
            print("\nMonitoring resumed.\n")
            log("MONITOR", "settings closed; polling resumed")
            keyboard_pause.clear()
            return
        try:
            nums = sorted(set(int(x.strip()) for x in raw.split(",") if x.strip()))
            if not nums or any(x < 1 or x > len(entries) for x in nums):
                raise ValueError
        except ValueError:
            print("Invalid selection. Use comma-separated entry numbers.")
            continue

        reenabled = {}
        for num in nums:
            target, reg = entries[num - 1]
            key = (target.device, target.slave)
            if reg in enabled[key]:
                enabled[key].remove(reg)
                log("MONITOR", f"device={target.device!r} slave={target.slave} R{reg} label={register_label(target, reg)!r} SILENCED")
            else:
                enabled[key].add(reg)
                reenabled.setdefault(target, []).append(reg)
                log("MONITOR", f"device={target.device!r} slave={target.slave} R{reg} label={register_label(target, reg)!r} REENABLED")

        # Re-enabled registers get a fresh baseline so changes that happened while
        # silenced are not reported as live changes.
        for target, regs in reenabled.items():
            vals = await read_register_set(session, target, log, regs)
            key = (target.device, target.slave)
            previous.setdefault(key, {}).update(vals)
            for reg in regs:
                if reg in vals:
                    log("REBASE", f"device={target.device!r} slave={target.slave} R{reg} value=[{value_formats(vals[reg])}]")


async def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = app_dir() / f"AP300_HA_Live_Change_Monitor_v0.9.3_{stamp}.txt"
    fh = logfile.open("w", encoding="utf-8", buffering=1)
    t0 = time.monotonic()

    def log(kind, msg):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3] + f"  +{time.monotonic()-t0:8.3f}s  {kind:<11} {msg}"
        fh.write(line + "\n")

    class FileLogHandler(logging.Handler):
        def emit(self, record):
            try:
                log("LIB", self.format(record))
            except Exception:
                pass

    handler = FileLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    session = None
    hotkey_task = None
    hotkey_stop = None
    try:
        print("=" * 78)
        print("AP300 / Hub A1 Live Register Change Monitor v0.9.3")
        print("READ ONLY - NO REGISTER WRITES")
        print("=" * 78)
        print("Initial poll displays all selected register values.")
        print("Later polls display only values that change.")
        print("Values are displayed as HEX, decimal, and two-byte ASCII.")
        print("During monitoring, press Ctrl+G to pause, toggle, or add register monitoring.")
        print(f"Log: {logfile}\n")

        mode = choose_mode()
        targets = targets_for(mode)
        log("START", f"v{VERSION} mode={mode!r} targets={[(t.device,t.slave) for t in targets]} read_only=True")

        name, mac = await choose_ha(log)
        print(f"Connecting to {name!r} at {mac}...")
        log("TARGET", f"name={name!r} BLE={mac}")

        loop = asyncio.get_running_loop()
        session = MonitorSession(
            mac, AP300(), loop.create_future,
            config=DeviceSessionConfig(timeout=60, use_encryption=True, command_timeout=2.0, command_retries=0),
        )
        await session.connect()
        print("Connected and authenticated.\n")
        log("READY", f"connected={session.is_connected} encrypted_ready={session.is_ready}")

        previous: dict[tuple[str, int], dict[int, int]] = {}
        print("=" * 78)
        print(f"INITIAL VALUES - {mode}")
        print("=" * 78)
        for target in targets:
            values = await read_register_set(session, target, log)
            previous[(target.device, target.slave)] = values
            print_initial(target, values, log)

        print("\n" + "=" * 78)
        print("BASELINE COMPLETE - MONITORING FOR CHANGES")
        print("=" * 78 + "\n")
        log("BASELINE", "complete")

        available = {(t.device, t.slave): set(t.registers) for t in targets}
        enabled = {(t.device, t.slave): set(t.registers) for t in targets}
        monitor_request = asyncio.Event()
        hotkey_stop = asyncio.Event()
        keyboard_pause = asyncio.Event()
        hotkey_task = asyncio.create_task(watch_ctrl_g(monitor_request, hotkey_stop, keyboard_pause))
        scan_no = 0
        while True:
            scan_no += 1
            scan_changes = 0

            if monitor_request.is_set():
                monitor_request.clear()
                await monitor_settings(session, targets, available, enabled, previous, log, keyboard_pause)

            for target in targets:
                key = (target.device, target.slave)
                current = await read_register_set(session, target, log, enabled[key])
                old = previous.get(key, {})

                for reg in sorted(set(old) & set(current)):
                    if current[reg] != old[reg]:
                        scan_changes += 1
                        print_change(scan_no, target, reg, old[reg], current[reg], log)

                # A failed read never overwrites the last successful value. Update
                # only registers that actually returned a value this cycle.
                merged = dict(old)
                merged.update(current)
                previous[key] = merged

                missing = sorted(set(enabled[key]) - set(current))
                if missing:
                    log("READ_STATE", f"scan={scan_no} device={target.device!r} slave={target.slave} missing_registers={missing}")

                # A brief Ctrl+G press is consumed and latched by watch_ctrl_g even while Bluetooth I/O
                # is in progress. Open the menu only at this safe target boundary.
                if monitor_request.is_set():
                    monitor_request.clear()
                    await monitor_settings(session, targets, available, enabled, previous, log, keyboard_pause)

            log("SCAN", f"scan={scan_no} changes={scan_changes}")
            await asyncio.sleep(POLL_DELAY_SECONDS)

    except KeyboardInterrupt:
        print("\nStopped by user.")
        log("STOP", "Stopped by user")
    finally:
        if hotkey_stop is not None:
            hotkey_stop.set()
        if hotkey_task is not None:
            try:
                await hotkey_task
            except asyncio.CancelledError:
                pass
        if session:
            try:
                await session.disconnect()
            except Exception as exc:
                log("ERROR", f"Disconnect: {type(exc).__name__}: {exc}")
        if handler in root.handlers:
            root.removeHandler(handler)
        if not fh.closed:
            fh.close()
        print(f"\nLog saved to:\n  {logfile}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
        raise
