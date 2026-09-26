AP300 / Hub A1 Live Register Change Monitor v0.9.3
================================================

Purpose
-------
Read-only live change monitor for a Hub A1 / HA system and its AP300 members.

Modes
-----
1. HA
   - Slaves 0 and 4
   - R154-R175 (the HA register area established by v0.7)
2. AP300 Top
   - Slave 1 only
   - Known-good/known-semantic EL30V2 register set
3. AP300 Bottom
   - Slave 2 only
   - Same EL30V2 register set
4. All
   - HA slaves 0 and 4, then AP300 Top, then AP300 Bottom

Display / logging
-----------------
- Initial baseline prints every selected register.
- Later polling prints only registers whose values change.
- Each value is shown in 16-bit HEX, unsigned decimal, and two-byte ASCII.
- Changes include device name, slave, register, old value, new value, and time.
- BLE/library diagnostics and read errors go to the timestamped log.
- A timeout/read failure does not erase the previous good value.
- The old Ctrl+C instruction/status line from v0.7 has been removed.

Safety
------
READ ONLY. No Modbus register writes are performed.

Standalone Community Library
----------------------------
v0.9.3 removes the bundled vendor copy of bluetti_bt_lib.

The BUILD machine must have the authoritative Community Library at:
  C:\Users\clay\bluetti-bt-lib\bluetti_bt_lib

The build script prints the actual bluetti_bt_lib.__file__ path before
PyInstaller runs, providing a visible check that the standalone repository
is being used.

The resulting EXE remains standalone for the TEST machine; the laptop does
not need the source repository or Python installed.

Expected EXE:
  dist\AP300 HA Live Change Monitor v0.9.3.exe

v0.9.3 architecture change:
- Removed vendor\bluetti_bt_lib from the build kit.
- Scanner builds now use the same authoritative standalone bluetti-bt-lib
  repository as the BLUETTI GUI build.
- No second editable Community Library copy is maintained by this kit.


v0.9.3 change: Ctrl+G is now watched continuously and latched independently of the Modbus polling cycle, so a brief Ctrl+G press is not missed during Bluetooth reads. The menu opens at the next safe device boundary.


v0.9.3 hotkey fix:
- Ctrl+G replaces F2 for Monitor Settings.
- Ctrl+G is consumed from the Windows console input buffer so it does not invoke a built-in console editing function.
- The keyboard listener pauses while the Monitor Settings input prompt is active.


v0.9.3 additions
----------------
Ctrl+G Monitor Settings now includes A = Add Register(s) to Monitor.
Accepted input includes a single register with optional R prefix, ranges, and comma-separated mixtures.
Examples: 6009, R6009, 6003-6009, R6003-R6004,R6009.
Added registers apply to the target(s) selected at startup and remain session-only.
Reversed ranges are rejected. Duplicate register numbers are removed.
