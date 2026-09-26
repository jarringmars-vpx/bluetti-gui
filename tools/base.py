from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakScanner
from bluetti_bt_lib.bluetooth.device_session import DeviceSession, DeviceSessionConfig
from bluetti_bt_lib.devices.ap300 import AP300
from bluetti_bt_lib.registers import ReadableRegisters
from bluetti_bt_lib.registers.DeviceRegister import modbus_crc

VERSION = "0.4"
TOP = ("TOP", "AP3002543130827887", "FC:01:2C:C7:5E:FA")
BOTTOM = ("BOTTOM", "AP3002549130711401", "E8:06:90:AA:9E:02")
PASSIVE_SECONDS = 0
POST_PROBE_SECONDS = 0
SLAVES = range(0, 5)
MEMBER_SLAVES = (1, 2, 3)
STATUS_SLAVES = (0, 1, 2, 4)
SNAPSHOTS = 5
SNAPSHOT_INTERVAL = 2.0


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


class CaptureSession(DeviceSession):
    def __init__(self, *args, capture=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.capture = capture
        self.passive_observe_only = False

    @staticmethod
    def _encrypted_expected_len(data: bytes):
        # Secure frames are: 2-byte plaintext length + 4-byte IV seed + AES-CBC
        # ciphertext padded to a 16-byte boundary.
        if len(data) < 2:
            return None
        plain_len = int.from_bytes(data[:2], "big")
        padded = ((plain_len + 15) // 16) * 16
        return 6 + padded

    async def _notification_handler(self, sender, data):
        raw = bytes(data)
        self.capture("RAW_RX", f"len={len(raw)} hex={raw.hex(' ').upper()}")
        before_ready = self.encryption.is_ready_for_commands

        # During the passive experiment, do NOT feed post-handshake unsolicited
        # bytes into DeviceSession's command-response assembler.  v0.2 showed that
        # an incomplete 18-byte notification could be concatenated with the next
        # repeated notification and create a bogus 17,510-byte expected frame.
        if self.passive_observe_only and before_ready:
            expected = self._encrypted_expected_len(raw)
            if expected is None:
                self.capture("PASSIVE_RX", "too short to contain encrypted length header")
            elif len(raw) == expected:
                self.capture("PASSIVE_RX", f"self-contained encrypted frame candidate expected_len={expected}")
                try:
                    key, iv = self.encryption.getKeyIv()
                    plain = self.encryption.aes_decrypt(raw, key, iv)
                    self.capture("PASSIVE_DEC", f"len={len(plain)} hex={plain.hex(' ').upper()}")
                except Exception as exc:
                    self.capture("PASSIVE_DEC_ERR", f"{type(exc).__name__}: {exc}")
            elif len(raw) < expected:
                self.capture("PASSIVE_RX", f"incomplete/repeated fragment: header_plain_len={int.from_bytes(raw[:2], 'big')} expected_encrypted_len={expected} received={len(raw)}")
            else:
                self.capture("PASSIVE_RX", f"oversize notification: expected_encrypted_len={expected} received={len(raw)}")
            return

        await super()._notification_handler(sender, data)
        if not before_ready and self.encryption.is_ready_for_commands:
            self.capture("STATE", "Encryption handshake completed; secure session ready")
        for diagnostic in self.consume_scan_diagnostics():
            self.capture("DECRYPTED", diagnostic)


def banner(cap, title: str):
    cap("", "=" * 72)
    cap("PHASE", title)
    cap("", "=" * 72)


def words_to_ascii(values: list[int]) -> str:
    raw = b"".join(v.to_bytes(2, "big") for v in values)
    # Keep printable ASCII; NUL/FF padding becomes spaces and is stripped.
    text = "".join(chr(b) if 32 <= b <= 126 else " " for b in raw)
    return " ".join(text.split())


def make_read(start: int, count: int, slave: int) -> ReadableRegisters:
    reg = ReadableRegisters(start, count)
    reg.cmd[0] = slave
    crc = modbus_crc(reg.cmd[:-2])
    reg.cmd[-2:] = crc.to_bytes(2, "little")
    return reg


async def raw_read(session: CaptureSession, cap, slave: int, start: int, count: int):
    reg = make_read(start, count, slave)
    cap("TX_PLAIN", f"slave={slave} R{start}-R{start+count-1} request={bytes(reg.cmd).hex(' ').upper()}")
    try:
        async with session.command_lock:
            response = await session._async_send_command(reg)
        cap("RX_PLAIN", f"slave={slave} R{start}-R{start+count-1} response={bytes(response).hex(' ').upper()}")
        body = reg.parse_response(response)
        if len(body) != count * 2:
            cap("PROBE_ERR", f"slave={slave} R{start}-R{start+count-1} expected {count*2} data bytes, got {len(body)}")
            return None
        values = [int.from_bytes(body[i:i+2], "big") for i in range(0, len(body), 2)]
        cap("WORDS", " ".join(f"R{start+i}=0x{v:04X}({v})" for i, v in enumerate(values)))
        return values
    except Exception as exc:
        cap("PROBE_ERR", f"slave={slave} R{start}-R{start+count-1}: {type(exc).__name__}: {exc}")
        return None
    finally:
        for diagnostic in session.consume_scan_diagnostics():
            cap("DIAG", diagnostic)


async def choose_target(cap):
    choice = sys.argv[1].strip().upper() if len(sys.argv) > 1 else input("Test [T]op, [B]ottom, or [H]A/Hub A1: ").strip().upper()
    if choice in {"T", "TOP"}:
        return TOP
    if choice in {"B", "BOTTOM"}:
        return BOTTOM
    if choice not in {"H", "HA", "HUB", "HUB A1", "HUBA1"}:
        raise SystemExit("Choose TOP/T, BOTTOM/B, or HA/H.")

    banner(cap, "HA DISCOVERY - scanning for Hub A1 advertisement")
    devices = await BleakScanner.discover(timeout=12.0)
    candidates = []
    for d in devices:
        name = (d.name or "").strip()
        cap("SCAN_SEEN", f"name={name!r} address={d.address}")
        upper = name.upper()
        if upper == "HA" or upper.startswith("HA") or "HUB" in upper:
            candidates.append(d)

    if not candidates:
        raise RuntimeError("No HA/Hub A1 candidate was discovered. Confirm both AP300s are connected to the Hub A1 and retry.")
    if len(candidates) == 1:
        selected = candidates[0]
    else:
        print("\nHA/Hub candidates:")
        for i, d in enumerate(candidates, 1):
            print(f"  {i}. {d.name!r}  {d.address}")
        while True:
            try:
                idx = int(input("Select HA device number: ")) - 1
                selected = candidates[idx]
                break
            except (ValueError, IndexError):
                print("Invalid selection.")
    return ("HA", selected.name or "HA", selected.address)


async def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Start with a temporary generic name; rename logically in the log once target is chosen.
    logfile = app_dir() / f"AP300_Startup_Capture_PENDING_{stamp}.txt"
    fh = logfile.open("w", encoding="utf-8", buffering=1)
    t0 = time.monotonic()

    def cap(kind, msg):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3] + f"  +{time.monotonic()-t0:8.3f}s  {kind:<11} {msg}"
        print(line)
        fh.write(line + "\n")

    class LogHandler(logging.Handler):
        def emit(self, record):
            try:
                cap("LIB", self.format(record))
            except Exception:
                pass

    h = LogHandler()
    h.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(h)
    session = None

    try:
        cap("START", f"AP300 HA topology/status comparison v{VERSION} - READ ONLY / NO REGISTER WRITES")
        label, name, mac = await choose_target(cap)
        final_logfile = app_dir() / f"AP300_Startup_Capture_{label}_{stamp}.txt"
        cap("TARGET", f"unit={label} name={name!r} BLE={mac}")
        cap("PURPOSE", "Primary objective: discover all AP300 member slots and identify the HA aggregate telemetry endpoint.")
        cap("PURPOSE", "Member discovery always checks slaves 1, 2, and 3; aggregate candidates 0 and 4 are compared using operational telemetry.")

        if label != "HA":
            cap("SCAN", f"Looking for {mac}")
            dev = await BleakScanner.find_device_by_address(mac, timeout=12)
            if dev is None:
                raise RuntimeError(f"Device not found: {mac}")
            cap("SCAN", f"Found name={dev.name!r} address={dev.address}")

        loop = asyncio.get_running_loop()
        session = CaptureSession(
            mac,
            AP300(),
            loop.create_future,
            config=DeviceSessionConfig(timeout=60, use_encryption=True, command_timeout=2.0, command_retries=0),
            capture=cap,
        )

        banner(cap, "1 - CONNECTION / AUTHENTICATION")
        cap("CONNECT", "Connecting and subscribing; every raw notification is logged.")
        await session.connect()
        cap("READY", f"connected={session.is_connected} encrypted_ready={session.is_ready}")

        banner(cap, "2 - COMPLETE IDENTITY DISCOVERY, SLAVES 0 THROUGH 4")
        cap("INFO", "Discovery always completes all addresses. Member slots 1, 2, and 3 are evaluated independently.")
        cap("INFO", "An empty slave 1 does NOT imply that no AP300 is attached; valid members may exist at slave 2 and/or 3.")

        identities = {}
        for slave in SLAVES:
            cap("SLAVE", f"--- identity probe slave/member {slave} ---")
            dtype = await raw_read(session, cap, slave, 110, 6)
            serial = await raw_read(session, cap, slave, 116, 4)
            dtype_zero = dtype is not None and all(v == 0 for v in dtype)
            serial_zero = serial is not None and all(v == 0 for v in serial)
            valid = dtype is not None and serial is not None and not (dtype_zero and serial_zero)
            identities[slave] = (valid, dtype, serial)
            cap("IDENTITY", f"slave={slave} valid={valid} device_type_ascii={words_to_ascii(dtype) if dtype else ''!r} serial_words={serial}")
            await asyncio.sleep(0.15)

        members = [s for s in MEMBER_SLAVES if identities.get(s, (False,))[0]]
        cap("TOPOLOGY", f"discovered_AP300_member_slaves={members}")
        for slave in MEMBER_SLAVES:
            cap("MEMBER", f"slave={slave} {'PRESENT' if slave in members else 'EMPTY/NOT DETECTED'}")

        banner(cap, f"3 - AGGREGATE-ENDPOINT COMPARISON ({SNAPSHOTS} SNAPSHOTS)")
        cap("INFO", "Comparing slaves 0,1,2,4. Slave 3 is reserved for a possible third AP300 and is not treated as aggregate.")
        cap("INFO", "Reads are READ ONLY: SOC R102, power-flow R140-R146, battery R6003-R6004, controls R2011-R2012.")
        cap("INFO", "R140=DC out, R142=AC out, R144=DC/PV in, R146=AC/grid in based on the current AP300 map.")

        async def status_snapshot(slave):
            soc = await raw_read(session, cap, slave, 102, 1)
            power = await raw_read(session, cap, slave, 140, 7)
            battery = await raw_read(session, cap, slave, 6003, 2)
            controls = await raw_read(session, cap, slave, 2011, 2)
            result = {
                'soc': soc[0] if soc else None,
                'dc_out': power[0] if power else None,
                'ac_out': power[2] if power and len(power) > 2 else None,
                'dc_in': power[4] if power and len(power) > 4 else None,
                'ac_in': power[6] if power and len(power) > 6 else None,
                'bat_v_raw': battery[0] if battery else None,
                'bat_i_raw': battery[1] if battery and len(battery) > 1 else None,
                'ac_state': controls[0] if controls else None,
                'dc_state': controls[1] if controls and len(controls) > 1 else None,
            }
            cap("STATUS", f"slave={slave} " + " ".join(f"{k}={v}" for k,v in result.items()))
            return result

        all_status = {}
        for snap in range(1, SNAPSHOTS + 1):
            cap("SNAPSHOT", f"--- {snap}/{SNAPSHOTS} ---")
            for slave in STATUS_SLAVES:
                all_status.setdefault(slave, []).append(await status_snapshot(slave))
                await asyncio.sleep(0.08)
            if snap < SNAPSHOTS:
                await asyncio.sleep(SNAPSHOT_INTERVAL)

        banner(cap, "4 - COMPARISON SUMMARY")
        cap("SUMMARY", f"member_slaves_present={members}")
        for slave in STATUS_SLAVES:
            seq = all_status.get(slave, [])
            cap("SUMMARY", f"slave={slave} snapshots={seq}")
        cap("CAUTION", "Do not label slave 0 or 4 as aggregate from identity alone. Compare operational values against members 1/2.")
        cap("DONE", "Capture complete. Use the STATUS/SUMMARY lines to determine whether slave 0 or 4 represents stack-level telemetry.")

        # Close first, then rename the log so Windows does not need to rename an open file.
        if session:
            try:
                await session.disconnect()
            except Exception as exc:
                cap("ERROR", f"Disconnect: {exc}")
            session = None
        cap("LOG", f"Final log name: {final_logfile.name}")
        root.removeHandler(h)
        fh.close()
        logfile.replace(final_logfile)
        print(f"\nSaved: {final_logfile}")
        return

    finally:
        if session:
            try:
                await session.disconnect()
            except Exception as exc:
                cap("ERROR", f"Disconnect: {exc}")
        if h in root.handlers:
            root.removeHandler(h)
        if not fh.closed:
            cap("LOG", f"Saved to {logfile}")
            fh.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        input("Press Enter to close...")
        raise
