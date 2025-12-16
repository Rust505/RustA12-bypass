#!/usr/bin/env python3
# main.py — iOS Activation Bypass GUI (macOS, PyQt6) — Enhanced for PyInstaller & UX

import sys
import os
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QLineEdit, QGroupBox,
    QRadioButton, QButtonGroup, QMessageBox, QProgressBar, QFrame,
    QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer, QSettings, QSize
from PyQt6.QtGui import QFont, QTextCursor, QPalette, QColor, QPixmap, QIcon, QDragEnterEvent, QDropEvent

# === Resource path helper for PyInstaller ===
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = Path(sys._MEIPASS)
    except Exception:
        base_path = Path(__file__).parent
    return base_path / relative_path


# === CLI module import ===
try:
    from activator_macos import log as original_log, run as original_run, validate_guid, run_cmd, find_binary
except ImportError as e:
    app = QApplication(sys.argv)  # temporary QApplication for dialog
    QMessageBox.critical(None, "Import Error", f"Failed to import 'activator_macos.py':\n{e}\n\n"
                                               "Ensure it's in the same directory.")
    sys.exit(1)


# === Thread-safe signal communication ===
class SignalEmitter(QObject):
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int)
    success_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    device_update_signal = pyqtSignal(dict)
    stage_signal = pyqtSignal(str)


emitter = SignalEmitter()


def gui_log(msg: str, level='info'):
    emitter.log_signal.emit(msg, level)
    original_log(msg, level)


# Patch the activator logger
import activator_macos
activator_macos.log = gui_log


# === Worker thread ===
class ActivatorWorker(QThread):
    def __init__(self, auto: bool = False, guid: Optional[str] = None):
        super().__init__()
        self.auto = auto
        self.guid = guid
        self._stopped = False

    def stop(self):
        self._stopped = True
        self.requestInterruption()

    def _set_stage(self, stage_name: str):
        emitter.stage_signal.emit(stage_name)

    def run(self):
        try:
            if self._stopped:
                return

            # Progress through stage signals (approximate)
            QTimer.singleShot(300, lambda: self._set_stage("detect"))
            QTimer.singleShot(1000, lambda: self._set_stage("guid"))
            QTimer.singleShot(4000, lambda: self._set_stage("download"))
            QTimer.singleShot(9000, lambda: self._set_stage("upload"))
            QTimer.singleShot(16000, lambda: self._set_stage("reboot"))

            original_run(auto=self.auto, preset_guid=self.guid)

            if not self._stopped:
                self._set_stage("done")
                emitter.success_signal.emit()

        except Exception as e:
            if not self._stopped:
                emitter.error_signal.emit(str(e))
        finally:
            if not self._stopped:
                emitter.progress_signal.emit(100)


# === Device information panel ===
class DeviceInfoPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.update_info()

    def setup_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        # Left side: status + image
        img_container = QVBoxLayout()
        img_container.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.status_indicator = QLabel("●")
        self.status_indicator.setFont(QFont("SF Mono", 18, QFont.Weight.Bold))
        self.status_indicator.setStyleSheet("color: #999;")
        img_container.addWidget(self.status_indicator, alignment=Qt.AlignmentFlag.AlignLeft)

        self.img_label = QLabel()
        img_path = resource_path("assets/iphone.png")  # ✅ FIXED: uses resource_path
        if img_path.exists():
            pixmap = QPixmap(str(img_path))
            size = 144  # увеличено
            screen = QApplication.primaryScreen()
            if screen:
                size = int(144 * screen.devicePixelRatio())
            pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.img_label.setPixmap(pixmap)
        else:
            self.img_label.setText("📱\n\niPhone\n(not found)")
            self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.img_label.setStyleSheet("font-size: 16px; color: #888; font-weight: bold;")

        img_container.addWidget(self.img_label)
        layout.addLayout(img_container)

        # Right side: text
        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)

        title_label = QLabel("Device Information")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        info_layout.addWidget(title_label)

        self.model_label = QLabel("Model: —")
        self.ios_label = QLabel("iOS: —")
        self.activation_label = QLabel("Activation: —")
        self.udid_label = QLabel("UDID: —")

        for lbl in [self.model_label, self.ios_label, self.activation_label, self.udid_label]:
            lbl.setFont(QFont("SF Mono, Menlo, monospace", 12))
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            info_layout.addWidget(lbl)

        layout.addLayout(info_layout)
        self.setLayout(layout)

    def update_info(self, info: Optional[Dict[str, str]] = None):
        if not info or not isinstance(info, dict):
            info = {"ProductType": "—", "ProductVersion": "—", "ActivationState": "—", "UniqueDeviceID": "—"}

        # Status
        act = info.get("ActivationState", "").strip()
        if act == "Activated":
            self.status_indicator.setStyleSheet("color: #4caf50;")
            self.status_indicator.setToolTip("✅ Activated")
        elif act in ("Unactivated", "—"):
            self.status_indicator.setStyleSheet("color: #ff9800;")
            self.status_indicator.setToolTip("⚠ Not activated")
        else:
            self.status_indicator.setStyleSheet("color: #f44336;")
            self.status_indicator.setToolTip("❌ Unknown")

        # Model
        model_map = {
            "iPhone13,4": "iPhone 12 Pro Max",
            "iPhone13,3": "iPhone 12 Pro",
            "iPhone13,2": "iPhone 12",
            "iPhone14,5": "iPhone 13",
            "iPhone15,2": "iPhone 14 Pro",
            "iPhone15,3": "iPhone 14 Pro Max",
            "iPhone16,1": "iPhone 15 Pro",
            "iPhone16,2": "iPhone 15 Pro Max",
        }
        code = info.get("ProductType", "Unknown")
        name = model_map.get(code, code)
        self.model_label.setText(f"<b>Model:</b> {name}")

        # Other info
        self.ios_label.setText(f"<b>iOS:</b> {info.get('ProductVersion', '—')}")

        state = info.get("ActivationState", "—")
        color = "#4caf50" if state == "Activated" else "#ff9800"
        self.activation_label.setText(f'<span style="color:{color};"><b>Activation:</b> <b>{state}</b></span>')
        self.activation_label.setTextFormat(Qt.TextFormat.RichText)

        udid = info.get("UniqueDeviceID", "—")
        # ✅ Показываем полный UDID, но делаем его переносимым
        self.udid_label.setText(f"<b>UDID:</b> {udid}")
        self.udid_label.setWordWrap(True)
        self.udid_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)


# === Main window ===
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📱 iOS Activation Bypass (Rust505)")
        self.resize(1024, 768)
        self.thread = None

        # ✅ QSettings — only after QApplication
        self.settings = QSettings("Rust505", "iOSActivatorGUI")

        # Device update timer
        self._device_timer = QTimer()
        self._device_timer.timeout.connect(self.detect_device)
        self._device_timer.start(3000)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Device panel
        device_frame = QFrame()
        device_frame.setFrameShape(QFrame.Shape.StyledPanel)
        device_frame.setFrameShadow(QFrame.Shadow.Raised)
        device_layout = QVBoxLayout(device_frame)
        device_layout.addWidget(QLabel("📱 Connected Device"), alignment=Qt.AlignmentFlag.AlignLeft)
        self.device_panel = DeviceInfoPanel()
        device_layout.addWidget(self.device_panel)
        main_layout.addWidget(device_frame)

        # GUID mode
        mode_group = QGroupBox("GUID Input Mode")
        mode_group.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        mode_layout = QHBoxLayout()
        self.radio_auto = QRadioButton("Auto-detect (recommended)")
        self.radio_manual = QRadioButton("Manual input")
        self.radio_auto.setChecked(True)
        group = QButtonGroup()
        group.addButton(self.radio_auto)
        group.addButton(self.radio_manual)
        mode_layout.addWidget(self.radio_auto)
        mode_layout.addWidget(self.radio_manual)
        mode_group.setLayout(mode_layout)
        main_layout.addWidget(mode_group)

        # GUID field
        guid_layout = QHBoxLayout()
        guid_layout.addWidget(QLabel("GUID:"), alignment=Qt.AlignmentFlag.AlignTop)
        self.guid_edit = QLineEdit()
        self.guid_edit.setPlaceholderText("e.g. 1A2B3C4D-1234-4123-8888-ABCDEF012345")
        self.guid_edit.textChanged.connect(self._validate_guid)
        self.guid_edit.setMaximumWidth(600)
        self.guid_edit.setFont(QFont("SF Mono, Menlo, monospace", 12))
        guid_layout.addWidget(self.guid_edit)
        main_layout.addLayout(guid_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Activation")
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_activation)
        self.stop_btn.clicked.connect(self.stop_activation)
        self.start_btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.stop_btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        main_layout.addLayout(btn_layout)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFont(QFont("Segoe UI", 12))
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #bbb;
                border-radius: 5px;
                text-align: center;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                width: 20px;
            }
        """)
        main_layout.addWidget(self.progress)

        # Logs
        log_group = QGroupBox("Logs")
        log_group.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        log_layout = QVBoxLayout()
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("SF Mono, Menlo, Monaco, monospace", 11))
        self.log_view.setStyleSheet("""
            background: #1e1e1e;
            color: #e0e0e0;
            border: 1px solid #444;
            padding: 8px;
            font-size: 11pt;
        """)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        log_layout.addWidget(self.log_view)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

        # Connect signals
        emitter.log_signal.connect(self.append_log)
        emitter.progress_signal.connect(self.progress.setValue)
        emitter.success_signal.connect(self.on_success)
        emitter.error_signal.connect(self.on_error)
        emitter.device_update_signal.connect(self.device_panel.update_info)
        emitter.stage_signal.connect(self._on_stage_change)

        # Load last GUID (if exists)
        last_guid = self.settings.value("last_guid", "")
        if last_guid and validate_guid(last_guid):
            self.guid_edit.setText(last_guid.upper())

        # Check dependencies and update device
        self._check_dependencies()
        self.detect_device()

    def _check_dependencies(self):
        missing = [b for b in ['ideviceinfo', 'idevice_id', 'pymobiledevice3', 'curl'] if not find_binary(b)]
        if missing:
            msg = (
                f"⚠ Missing tools: {', '.join(missing)}\n\n"
                "Install with:\n"
                "  brew install libimobiledevice\n"
                "  pip3 install pymobiledevice3"
            )
            QMessageBox.critical(self, "Dependency Error", msg)
            self.start_btn.setEnabled(False)

    def _validate_guid(self):
        text = self.guid_edit.text().strip()
        valid = bool(text and validate_guid(text.upper()))
        self.guid_edit.setStyleSheet("" if valid else "background: #ffebee;" if len(text) > 8 else "")

    def detect_device(self):
        if self.thread and self.thread.isRunning():
            return
        try:
            code, out, _ = run_cmd(["ideviceinfo"], timeout=5)
            info = {}
            if code == 0:
                for line in out.splitlines():
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        info[k.strip()] = v.strip()
                # UDID
                udid_code, udid_out, _ = run_cmd(["idevice_id", "-l"], timeout=3)
                if udid_code == 0:
                    info["UniqueDeviceID"] = udid_out.strip() or "—"
            emitter.device_update_signal.emit(info)
        except Exception as e:
            emitter.device_update_signal.emit({})

    def _on_stage_change(self, stage: str):
        labels = {
            "detect": "🔍 Detecting device...",
            "guid": "📡 Extracting GUID...",
            "download": "📥 Downloading payload...",
            "upload": "📤 Uploading to /Downloads/...",
            "reboot": "🔄 Rebooting (×3)...",
            "done": "✅ Done!",
        }
        self.progress.setFormat(labels.get(stage, stage))

    def start_activation(self):
        if self.thread and self.thread.isRunning():
            return

        auto = self.radio_auto.isChecked()
        guid = self.guid_edit.text().strip().upper() if self.radio_manual.isChecked() else None

        if self.radio_manual.isChecked():
            if not guid:
                QMessageBox.warning(self, "Input Required", "GUID field is empty.")
                return
            if not validate_guid(guid):
                QMessageBox.warning(self, "Invalid GUID", "GUID must be UUID v4 (e.g. XXXXXXXX-XXXX-4XXX-YXXX-XXXXXXXXXXXX).")
                return

        self.log_view.clear()
        self.append_log("🚀 Starting activation process...", "info")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)
        self.progress.setFormat("Initializing...")

        self.thread = ActivatorWorker(auto=auto, guid=guid)
        self.thread.finished.connect(self._on_thread_finished)
        self.thread.start()

    def stop_activation(self):
        if self.thread and self.thread.isRunning():
            self.append_log("⏹ Stop requested...", "warn")
            self.thread.stop()
            self.thread.wait(2000)
            if self.thread.isRunning():
                self.thread.terminate()
                self.append_log("⚠ Thread forcibly terminated.", "error")
            self._on_thread_finished()

    def _on_thread_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def append_log(self, msg: str, level='info'):
        colors = {
            'success': '#4caf50',
            'error': '#f44336',
            'warn': '#ff9800',
            'step': '#2196f3',
            'info': '#64b5f6',
            'detail': '#90a4ae'
        }
        color = colors.get(level, '#e0e0e0')
        ts = time.strftime("%H:%M:%S")
        html = f'<span style="color:#78909c;">[{ts}]</span> <span style="color:{color};">{msg}</span><br>'
        self.log_view.append(html)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_view.ensureCursorVisible()

    def on_success(self):
        self.append_log("🎉 ACTIVATION SUCCESSFUL!", "success")
        # Save GUID
        guid = self.guid_edit.text().strip().upper()
        if guid and validate_guid(guid):
            self.settings.setValue("last_guid", guid)
        QMessageBox.information(self, "Success", "✅ Activation bypass completed!\n\n"
                                                 "📌 Thanks Rust505 and rhcp011235")
        self.detect_device()

    def on_error(self, err: str):
        self.append_log(f"❌ Fatal: {err}", "error")
        QMessageBox.critical(self, "Activation Failed", f"Process terminated with error:\n\n<b>{err}</b>")


# === Theme and icon ===
def enable_dark_mode(app: QApplication):
    try:
        import subprocess
        res = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                             capture_output=True, text=True)
        is_dark = res.returncode == 0 and "Dark" in res.stdout
    except:
        is_dark = True

    if is_dark:
        app.setStyle("Fusion")
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window, QColor(38, 38, 38))
        p.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.Base, QColor(28, 28, 28))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor(48, 48, 48))
        p.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.Button, QColor(68, 68, 68))
        p.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        p.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        p.setColor(QPalette.ColorRole.Link, QColor(40, 140, 240))
        p.setColor(QPalette.ColorRole.Highlight, QColor(40, 140, 240))
        p.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        app.setPalette(p)


def set_app_icon(app: QApplication):
    icon_path = resource_path("assets/app_icon.icns")  # ✅ FIXED: uses resource_path
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))


# === Entry point ===
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("iOS Activation Bypass")
    app.setOrganizationName("Rust505")
    enable_dark_mode(app)
    set_app_icon(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
