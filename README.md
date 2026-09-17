BLUETTI Desktop GUI v0.2.54
===========================

Requirements
------------
- Windows 10/11
- Python 3.10 (project reference: C:\Python310\python.exe)
- PySide6
- BLE support compatible with the selected backend
- For Community backend development, the configured bluetti_bt_lib checkout
- For Official backend use, the required BLUETTI official crypt/library components
  and a valid authorization CSV

Run
---
From the repository root:

    C:\Python310\python.exe app.py

Repository / authorization CSV
------------------------------
The Official BLUETTI authorization CSV is expected in the repository root,
alongside app.py.

The application must derive this location from the application/repository
location. Do not hard-code a specific Windows user path.

Authorization CSV files are local credentials and are excluded from the
public Git repository. Do not commit or publish their contents.

Backends
--------
The GUI is backend-agnostic and supports normalized telemetry/control through
the available backend implementations.

Community backend:
- Mature reference implementation for EL30V2 BLE behavior.
- Uses immediate optimistic AC/DC control-state updates.
- Uses fast recovery and stale-state protection around device polling.

Official backend / Expanded Validator:
- Uses the Official BLUETTI library/crypt path.
- As of v0.2.53, uses the same immediate optimistic AC/DC user experience.
- Indeterminate/unexpected BLE responses are abandoned quickly so polling can
  continue rather than imposing long recovery pauses.
- A final telemetry-commit guard prevents a poll that started before a button
  click from overwriting the newer optimistic AC/DC state with stale data.

Important EL30V2 BLE behavior
-----------------------------
The EL30V2 can emit unsolicited/autonomous BLE messages while application
requests are in progress. Prior research found that these messages can look
like valid Modbus-related traffic, but their complete meaning/start address
was not reliably determined.

Current project policy:
- Do not spend normal GUI development time reverse-engineering these messages.
- If a response cannot be associated confidently with the current poll/write
  verification, treat that result as indeterminate and move on promptly.
- Keep recovery fast (approximately 0.5 seconds where applicable).
- Do not use a multi-second sleep after an ambiguous transaction.

AC/DC control-state behavior
----------------------------
Expected behavior with either backend:

    User clicks AC/DC
        -> GUI changes immediately (optimistic state)
        -> EL30V2 command is issued
        -> contradictory stale polling data is suppressed
        -> fresh matching telemetry becomes authoritative

v0.2.53 fixes an Official-backend race where a polling batch could capture the
old AC/DC state before a click and commit that stale value after the click.
The Official backend now re-checks protected control state at the final
telemetry commit point.

Device images
-------------
Model images are stored under:

    Images\Bluetti_Models\

Use the exact model name returned by the device, for example:

    Images\Bluetti_Models\EL30V2.webp

The image resolver may support additional image extensions and an Unknown
fallback according to the current source.

Troubleshooting BLE connection failures
---------------------------------------
If the EL30V2 is discoverable but the GUI hangs while connecting or GATT
operations fail, test raw WinRT/Bleak before changing GUI polling code.

On the project's Dell Wireless 1705 / Qualcomm Atheros Bluetooth system,
uninstalling/reinstalling the Bluetooth adapter/driver restored GATT
connectivity during the September 14, 2026 outage.

Current baseline
----------------
v0.2.54 adds a BLE-sniffer research diagnostic to the Community backend. After
a successful encrypted IoT-v2 connection, the negotiated session AES key is
written through the existing Connection / device-info diagnostics category.
The change does not alter polling, command timing, encryption, or session
behavior. v0.2.53 remains the immediately preceding known-good functional
baseline.

Versioning
----------
Increment the GUI version for every meaningful update.

Update package naming:

    BLUETTI_GUI_v<version>_update.zip

Prefer complete modified files in update packages rather than manual patching
of core GUI files.
