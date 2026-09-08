r"""
BLUETTI GUI v0.2.15 persistent CommunityBackend smoke test.

Run from the GUI repository root:

    C:\Python310\python.exe tools\test_community_backend_v0.2.15.py

READ ONLY - NO WRITES.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from backends.community_backend import CommunityBackend


def main():
    backend = CommunityBackend(
        model="EL30V2",
        poll_seconds=5.0,
        scan_seconds=8.0,
    )

    print("BLUETTI CommunityBackend v0.2.15 persistent-session smoke test")
    print("READ ONLY - NO WRITES")
    print(f"Repo root: {REPO_ROOT}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            t = backend.get_telemetry()

            print(
                f"status={backend.status_message}\n"
                f"connected={t.connected} model={t.model} soc={t.soc}%\n"
                f"AC in={t.ac_input_power}W  DC in={t.dc_input_power}W\n"
                f"AC out={t.ac_output_power}W DC out={t.dc_output_power}W\n"
                f"AC={t.ac_output_enabled} DC={t.dc_output_enabled} "
                f"mode={t.charging_mode} temp={t.temperature_c}\n"
                f"address={'resolved' if backend.address else 'not resolved'}\n"
                + "-" * 72
            )

            time.sleep(5)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        backend.close()
        time.sleep(1.0)


if __name__ == "__main__":
    main()
