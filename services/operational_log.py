from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from app_paths import default_log_dir

_lock = threading.RLock()
_log_path: Path | None = None
_session_device_name: str | None = None


def _safe_device_name(device_name: str | None) -> str:
    name = (device_name or "UnknownDevice").strip() or "UnknownDevice"
    # Keep Windows filenames safe while preserving BLUETTI advertised names.
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .") or "UnknownDevice"


def start_operational_log_session(device_name: str | None) -> Path | None:
    """Start one log file for a user-selected device connection attempt.

    Repeated calls for the same active device keep the existing session. Selecting
    a different device starts a new timestamped file immediately, before BLE
    connection succeeds or fails.
    """
    global _log_path, _session_device_name
    try:
        with _lock:
            safe_name = _safe_device_name(device_name)
            if _log_path is not None and _session_device_name == safe_name:
                return _log_path
            directory = default_log_dir()
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            _log_path = directory / f"{stamp}_{safe_name}.log"
            _session_device_name = safe_name
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with _log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{now} Log session started for device={device_name!r}\n")
            return _log_path
    except Exception:
        return None


def operational_log(message: str) -> Path | None:
    """Write low-volume connection activity into the active device session log.

    Activity before a device connection attempt (for example a setup scan) is not
    written to disk. Once a device is selected, all operational and detailed
    diagnostic activity shares that connection session's single file.
    """
    try:
        with _lock:
            if _log_path is None:
                return None
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with _log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{now} {message.rstrip()}\n")
            return _log_path
    except Exception:
        return None


def current_operational_log_path() -> Path | None:
    return _log_path
