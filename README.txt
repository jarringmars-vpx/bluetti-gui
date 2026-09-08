BLUETTI GUI v0.1

Requirements
------------
Python 3.10
PySide6

Run
---
From Windows Command Prompt:

cd /d C:\path\to\bluetti_gui_v0_1
C:\Python310\python.exe app.py

Device image convention
-----------------------
The GUI uses the exact model name returned by the device.

Example:
    Model returned: EL30V2
    File expected: Images\Bluetti_Models\EL30V2.png

If that file is missing, the program tries:
    Images\Bluetti_Models\Unknown.png

If neither exists, the GUI displays instructions in the image area rather
than failing.

Current backend
---------------
v0.1 uses MockBackend so the GUI can be developed without repeatedly
opening BLE sessions.

Next step
---------
Create CommunityBackend using bluetti_bt_lib DeviceReader and translate
EL30V2 registers into the normalized Telemetry model.
