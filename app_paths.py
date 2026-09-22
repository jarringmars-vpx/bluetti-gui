from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the directory containing bundled read-only application resources."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def user_data_dir() -> Path:
    """Return a user-writable per-user data directory on Windows."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "BLUETTI Monitor"
    return Path.home() / ".bluetti-monitor"


def default_log_dir() -> Path:
    return user_data_dir() / "logs"
