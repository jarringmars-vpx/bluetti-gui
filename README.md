BLUETTI Desktop GUI v0.2.61
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

Community-only Windows release build
------------------------------------
v0.2.55 adds the first packaging baseline for a self-contained public Windows
Community-backend release. The normal source checkout still retains the
Official backend, but the Community PyInstaller build excludes it and presents
only the Community Library option.

Build from the repository root on the Windows development PC:

    build_community_release.bat

The first-stage portable build is created at:

    dist\BLUETTI Monitor\BLUETTI Monitor.exe

The entire `dist\BLUETTI Monitor` folder must be copied when testing this
first-stage build. The clean Windows 11 test computer does not need Python.

The packaged application resolves bundled Images resources independently of
the current working directory. Diagnostic logs default to the current user's
local application-data directory so an eventual Program Files installation
does not require write access to the installation directory.

The v0.2.54 research-only session-AES-key diagnostic is intentionally removed
from v0.2.55/public packaging work. Public release builds must not expose the
negotiated BLE session key in normal diagnostics.

Versioning
----------
Increment the GUI version for every meaningful update.

Update package naming:

    BLUETTI_GUI_v<version>_update.zip

Prefer complete modified files in update packages rather than manual patching
of core GUI files.


v0.2.56 packaging correction
-----------------------------
v0.2.56 makes the Community release build explicitly freeze the local
C:\Users\clay\bluetti-bt-lib checkout used by the working development GUI.
The build now verifies that checkout before PyInstaller starts and aborts if it
is missing, preventing a superficially successful but incomplete executable.
The PyInstaller spec adds that checkout to its module search path before
collecting bluetti_bt_lib and again as an Analysis path.


v0.2.58 Windows installer packaging
-----------------------------------

v0.2.58 adds the first Windows Setup.exe build path for the Community-only
release. The frozen application is still built by build_community_release.bat.
After that succeeds, build_windows_installer.bat compiles
packaging\BLUETTI_Monitor_Community.iss with Inno Setup and writes the final
installer to installer_output\BLUETTI_Monitor_v0.2.58_Setup.exe.

The installer targets 64-bit Windows 10/11, installs under Program Files, adds
a Start Menu shortcut, offers an optional desktop shortcut, and registers a
normal Windows uninstaller. End users do not need Python, PySide6, Bleak,
bluetti_bt_lib, or Inno Setup. Inno Setup is needed only on the developer PC
to compile Setup.exe.

This remains a Community-only public packaging baseline. Official Library
components and authorization CSV files are not included in the installer.



v0.2.61 per-device connection-session logging
----------------------------------------------
v0.2.61 changes logging so each selected-device connection attempt gets one log
file named with its timestamp and advertised device name, for example
2026-09-23_10-45-32_AP3002549130711401.log. The same file remains active for
the full connection session, including early connection failures, operational
messages, polling/control diagnostics, reconnect activity, and disconnects.
Selecting a different device starts a new log file. Detailed Community-backend
diagnostics now join the same connection-session file instead of creating a
second diagnostics file. Setup scanning before a device is selected does not
create a standalone session log.

v0.2.60 AP300 field-test support and early operational logging
------------------------------------------------------------
v0.2.60 fixes the Community backend session construction so the selected model's
bundled bluetti_bt_lib device class is used instead of always constructing EL30V2.
AP300 now opens with the AP300 community device definition and initially polls only
the community library's established power-flow registers (R140/R142/R144/R146).
EL30V2 retains its validated specialized polling path.

A separate always-on, low-volume operational log now starts during the setup BLE
scan and records discovery, selection, backend/session creation, and early connection
failures even when detailed diagnostics are disabled. Installed builds write these
logs to %%LOCALAPPDATA%%\BLUETTI Monitor\logs, not Program Files. HA/HA1 names are
recognized during discovery for identification/logging, but HA1 protocol support is
not claimed in this release.
