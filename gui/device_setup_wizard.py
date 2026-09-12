from __future__ import annotations

import asyncio
import re

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar
)

KNOWN_MODELS = [
    "PR100V2", "EL100V2", "PR30V2", "EL30V2", "Handsfree 1",
    "AC200PL", "AC200L", "AC200M", "AC180T", "AC180P", "AC180",
    "AC70P", "AC70", "AC60P", "AC60", "AC50B", "AC2P", "AC2A",
    "AC300", "AC500", "AP300", "EB3A", "EP500P", "EP500", "EP600",
    "EP760", "EP800", "EP2000",
]


def infer_model(name: str) -> str:
    compact = (name or "").replace(" ", "").upper()
    for model in sorted(KNOWN_MODELS, key=len, reverse=True):
        if compact.startswith(model.replace(" ", "").upper()):
            return model
    match = re.match(r"([A-Z]+\d+[A-Z0-9]*)", compact)
    return match.group(1) if match else "Unknown"


def discovery_identifier(name: str, model: str) -> str:
    """Return the BLE-name suffix without repeating the inferred model name."""
    raw_name = (name or "").strip()
    raw_model = (model or "").strip()
    if not raw_name:
        return ""
    if raw_model and raw_model != "Unknown":
        compact_name = raw_name.replace(" ", "")
        compact_model = raw_model.replace(" ", "")
        if compact_name.upper().startswith(compact_model.upper()):
            suffix = compact_name[len(compact_model):].lstrip("-_: ")
            if suffix:
                return suffix
    return raw_name


class ScanWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            results = asyncio.run(self._scan())
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))

    async def _scan(self):
        from bleak import BleakScanner
        discovered = await BleakScanner.discover(timeout=8.0, return_adv=True)
        rows = []
        for device, adv in discovered.values():
            name = ((getattr(adv, "local_name", None) or getattr(device, "name", None) or "").strip())
            address = (getattr(device, "address", None) or "").strip()
            if not name or not address:
                continue
            model = infer_model(name)
            if model == "Unknown" and "BLUETTI" not in name.upper():
                continue
            rssi = getattr(adv, "rssi", None)
            rows.append({"name": name, "address": address, "model": model, "rssi": rssi})
        rows.sort(key=lambda x: x["rssi"] if isinstance(x["rssi"], (int, float)) else -9999, reverse=True)
        return rows


class DeviceSetupWizard(QDialog):
    """Reusable first-run / change-device wizard."""
    device_selected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BLUETTI Device Setup")
        self.setMinimumSize(620, 430)
        self._thread = None
        self._worker = None
        self._build_ui()
        self._start_scan()

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Find your BLUETTI device")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        root.addWidget(title)
        note = QLabel(
            "Make sure Bluetooth is enabled and the BLUETTI device is awake. "
            "Select the device you want this application to use."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)

        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda _: self._accept_selected())
        root.addWidget(self.list, 1)

        self.status = QLabel("Scanning for nearby BLUETTI devices...")
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        self.rescan = QPushButton("Rescan")
        self.rescan.clicked.connect(self._start_scan)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.reject)
        self.use = QPushButton("Use Selected Device")
        self.use.setEnabled(False)
        self.use.clicked.connect(self._accept_selected)
        buttons.addWidget(self.rescan)
        buttons.addStretch()
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.use)
        root.addLayout(buttons)

    def _start_scan(self):
        if self._thread and self._thread.isRunning():
            return
        self.list.clear()
        self.use.setEnabled(False)
        self.rescan.setEnabled(False)
        self.progress.show()
        self.status.setText("Scanning for nearby BLUETTI devices...")
        self._thread = QThread(self)
        self._worker = ScanWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._scan_finished)
        self._worker.failed.connect(self._scan_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _scan_finished(self, devices):
        self.progress.hide()
        self.rescan.setEnabled(True)
        if not devices:
            self.status.setText("No BLUETTI devices found. Wake the device and try Rescan.")
            return
        for item in devices:
            rssi = item.get("rssi")
            identifier = discovery_identifier(item.get("name", ""), item.get("model", "Unknown"))
            model_and_id = item["model"]
            if identifier:
                model_and_id = f"{model_and_id}--{identifier}"
            signal = f"    RSSI: {int(rssi)} dBm" if isinstance(rssi, (int, float)) else ""
            label = f"{model_and_id}    {item['address']}{signal}"
            qitem = QListWidgetItem(label)
            qitem.setData(256, item)
            self.list.addItem(qitem)
        self.status.setText(f"Found {len(devices)} BLUETTI device(s).")

    def _scan_failed(self, message):
        self.progress.hide()
        self.rescan.setEnabled(True)
        self.status.setText("Bluetooth scan failed.")
        QMessageBox.warning(self, "Bluetooth Scan", message)

    def _selection_changed(self):
        self.use.setEnabled(bool(self.list.selectedItems()))

    def _accept_selected(self):
        selected = self.list.selectedItems()
        if not selected:
            return
        data = selected[0].data(256)
        self.device_selected.emit(data)
        self.accept()

    def selected_device(self):
        selected = self.list.selectedItems()
        return selected[0].data(256) if selected else None
