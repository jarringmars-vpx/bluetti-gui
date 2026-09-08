r"""
Standalone v0.2.12 CommunityBackend smoke test.

Run from the bluetti-gui repository root:

    C:\Python310\python.exe tools\test_community_backend_v0.2.12.py

This does not open the GUI and performs no writes.
"""

from __future__ import annotations

import time

from backends.community_backend import CommunityBackend


def main():
    backend = CommunityBackend(
        model="EL30V2",
        poll_seconds=10.0,
        scan_seconds=8.0,
    )

    print("BLUETTI CommunityBackend v0.2.12 smoke test")
    print("READ ONLY - NO WRITES")
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


if __name__ == "__main__":
    main()
