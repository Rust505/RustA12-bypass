# -*- coding: utf-8 -*-
import os
import sys
import re
import time
import json
import struct
import shutil
import sqlite3
import tempfile
import binascii
import threading
import datetime
import subprocess
import urllib.parse
from collections import Counter
from typing import Optional
from pathlib import Path
# PySide6 imports (ONLY PySide6 — NO PyQt5)
from PySide6.QtCore import Qt, QCoreApplication, QTimer
from PySide6.QtGui import QFontDatabase, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QTextEdit, QMessageBox
)

# Colorama fallback
try:
    from colorama import Fore, Style
except ImportError:
    class DummyColor:
        def __getattr__(self, _): return ''
    Fore = Style = DummyColor()


# ——— Utility ———
def resource_path(relative_path: str) -> str:
    """
    Resolve resource path for:
    - Development
    - Nuitka --mode=app (.app bundle on macOS)
    - Nuitka --onefile
    """

    # 1) Nuitka onefile
    if hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / relative_path)

    # 2) Nuitka app bundle (.app)
    if getattr(sys, "frozen", False):
        # executable: MyApp.app/Contents/MacOS/MyApp
        macos_dir = Path(sys.executable).resolve().parent

        # сначала ищем рядом с бинарём (Contents/MacOS)
        p = macos_dir / relative_path
        if p.exists():
            return str(p)

        # потом в Contents/Resources
        p = macos_dir.parent / "Resources" / relative_path
        if p.exists():
            return str(p)

        # потом в Contents/Resources/img
        p = macos_dir.parent / "Resources" / "img" / relative_path
        if p.exists():
            return str(p)

        raise FileNotFoundError(relative_path)

    # 3) Development
    return str(Path(__file__).resolve().parent / relative_path)

# ——— Main Window Class ———
class MainWindow(QMainWindow):
    def __init__(self):
        # 🔑 MUST be FIRST
        super().__init__()

        self.setWindowTitle("Rust A12+")
        self.setFixedSize(909, 540)

        # Load custom font
        font_path = resource_path("fonts/FuturaCyrillicBold.ttf")
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id == -1:
                print("[WARN] Failed to load custom font")
        else:
            print(f"[INFO] Font not found: {font_path}")

        # Set window icon
        icon_path = resource_path("img/logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Extend PATH for CLI tools (macOS/Homebrew)
        extra_paths = [
            "/usr/local/bin", "/usr/local/sbin",
            "/opt/homebrew/bin", "/opt/homebrew/sbin"
        ]
        os.environ["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + os.environ.get("PATH", "")

        # UI config & state
        self.api_url = "https://codex-r1nderpest-a12.ru/get2.php"
        self.timeouts = {
            'asset_wait': 300,
            'asset_delete_delay': 15,
            'reboot_wait': 300,
            'syslog_collect': 180,
            'log_show_timeout': 60,
        }
        self.device_info = {}
        self.guid = None
        self.attempt_count = 0
        self.max_attempts = 5
        self.global_GUID = ""
        self.BLDB_FILENAME = "BLDatabaseManager.sqlite"
        self.GUID_REGEX = re.compile(r'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}', re.IGNORECASE)
        self.temp_dir = tempfile.gettempdir()

        # Setup UI and connections
        self.setupUi()
        self.setupConnections()

        # Start device watcher
        threading.Thread(target=self.SearchingDevices, daemon=True).start()

        # Bottom console
        self.setupConsole()

    def setupUi(self):
        # Central widget
        self.centralwidget = QWidget(self)
        self.setCentralWidget(self.centralwidget)

        # ——— Intro Frame ———
        self.Intro = QFrame(self.centralwidget)
        self.Intro.setGeometry(-10, -10, 921, 601)
        self.Intro.setStyleSheet(
            "background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, "
            "stop:0 rgba(25, 25, 25, 255), stop:1 rgba(1, 27, 59, 255));"
            "border-radius: 0px;"
        )

        self.label_glow_phone = QLabel(self.Intro)
        self.label_glow_phone.setGeometry(400, 0, 601, 551)
        self.label_glow_phone.setPixmap(QPixmap(resource_path("img/glow_phone.png")))
        self.label_glow_phone.setScaledContents(True)
        self.label_glow_phone.setStyleSheet("background-color: transparent;") 

        self.label_title = QLabel("Welcome to Rust_A12+!", self.Intro)
        self.label_title.setGeometry(40, 210, 671, 51)
        self.label_title.setFont(QFont("Futura Cyrillic Bold", 30, QFont.Bold))
        self.label_title.setStyleSheet("color: white; background-color: transparent;")

        self.label_bg_glow = QLabel(self.Intro)
        self.label_bg_glow.setGeometry(-20, 60, 961, 531)
        self.label_bg_glow.setPixmap(QPixmap(resource_path("img/bg_GLOW.png")))
        self.label_bg_glow.setScaledContents(True)
        self.label_bg_glow.setStyleSheet("background-color: transparent;") 


        self.label_logo = QLabel(self.Intro)
        self.label_logo.setGeometry(80, 110, 371, 131)
        self.label_logo.setPixmap(QPixmap(resource_path("img/logo.png")))
        self.label_logo.setScaledContents(True)
        self.label_logo.setStyleSheet("background-color: transparent;")

        self.label_desc = QLabel(
            "Welcome to RustA12+! This tool helps bypass iCloud on all ipad and iPhone Xr – 17 Pro Max"
            "(iOS 18.7.2 and iOS 26.1). To get started, connect your device.",
            self.Intro
        )
        self.label_desc.setGeometry(44, 260, 441, 101)
        self.label_desc.setFont(QFont("Futura Cyrillic Bold", 14, QFont.Bold))
        self.label_desc.setStyleSheet("color: rgba(255, 255, 255, 187); background-color: transparent;")
        self.label_desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.label_desc.setWordWrap(True)

        self.frame_status_bg = QFrame(self.Intro)
        self.frame_status_bg.setGeometry(110, 370, 311, 41)
        self.frame_status_bg.setStyleSheet("background-color: rgba(0, 0, 0, 46); border-radius: 15px;")

        self.label_status = QLabel("⌛️ Searching for devices...", self.Intro)
        self.label_status.setGeometry(110, 370, 311, 41)
        self.label_status.setFont(QFont("Futura Cyrillic Bold", 14, QFont.Bold))
        self.label_status.setStyleSheet("color: white; background-color: transparent;")
        self.label_status.setAlignment(Qt.AlignCenter)

        # Raise in order
        self.label_bg_glow.raise_()
        self.label_logo.raise_()
        self.label_title.raise_()
        self.label_desc.raise_()
        self.frame_status_bg.raise_()
        self.label_status.raise_()

        # ——— HomePage Frame ———
        self.HomePage = QFrame(self.centralwidget)
        self.HomePage.setGeometry(0, -10, 921, 601)
        self.HomePage.setStyleSheet(
            "background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, "
            "stop:0 rgba(25, 25, 25, 255), stop:1 rgba(1, 27, 59, 255));"
        )
        self.label_cable = QLabel(self.HomePage)
        self.label_cable.setGeometry(50, 450, 221, 151)
        self.label_cable.setPixmap(QPixmap(resource_path("img/cable.png")))
        self.label_cable.setScaledContents(True)
        self.label_cable.setStyleSheet("background-color: transparent;") 

        # Device image
        self.label_ios26 = QLabel(self.HomePage)
        self.label_ios26.setGeometry(60, 70, 201, 421)
        self.label_ios26.setPixmap(QPixmap(resource_path("img/ios26hello.png")))
        self.label_ios26.setScaledContents(True)
        self.label_ios26.setStyleSheet("background-color: transparent;")
        # Labels
        self.DeviceName = QLabel("Device Name", self.HomePage)
        self.DeviceName.setGeometry(330, 100, 491, 41)
        self.DeviceName.setFont(QFont("Futura Cyrillic Bold", 28, QFont.Bold))
        self.DeviceName.setStyleSheet("color: white; background-color: transparent;")

        self.UDID = QLabel("UDID: ", self.HomePage)
        self.UDID.setGeometry(340, 160, 491, 41)
        self.UDID.setFont(QFont("Futura Cyrillic Bold", 16, QFont.Bold))
        self.UDID.setStyleSheet("color: white; background-color: transparent;")

        self.iOSVersion = QLabel("iOS Version: ", self.HomePage)
        self.iOSVersion.setGeometry(340, 210, 491, 41)
        self.iOSVersion.setFont(QFont("Futura Cyrillic Bold", 16, QFont.Bold))
        self.iOSVersion.setStyleSheet("color: white; background-color: transparent;")

        self.ProductType = QLabel("Product Type: ", self.HomePage)
        self.ProductType.setGeometry(340, 260, 491, 41)
        self.ProductType.setFont(QFont("Futura Cyrillic Bold", 16, QFont.Bold))
        self.ProductType.setStyleSheet("color: white; background-color: transparent;")

        self.ActivationState = QLabel("Activation Status: Unactivated", self.HomePage)
        self.ActivationState.setGeometry(340, 310, 491, 41)
        self.ActivationState.setFont(QFont("Futura Cyrillic Bold", 16, QFont.Bold))
        self.ActivationState.setStyleSheet("color: white; background-color: transparent;")

        self.ProductType_2 = QLabel("Your device is", self.HomePage)
        self.ProductType_2.setGeometry(340, 360, 200, 41)
        self.ProductType_2.setFont(QFont("Futura Cyrillic Bold", 16, QFont.Bold))
        self.ProductType_2.setStyleSheet("color: white; background-color: transparent;")

        self.ProductType_3 = QLabel("SUPPORTED!", self.HomePage)
        self.ProductType_3.setGeometry(480, 360, 400, 41)
        self.ProductType_3.setFont(QFont("Futura Cyrillic Bold", 16, QFont.Bold))
        self.ProductType_3.setStyleSheet("color: rgb(34, 255, 16); background-color: transparent;")

        # Background frames (for styling)
        for y in [160, 210, 260, 310, 360]:
            frame = QFrame(self.HomePage)
            frame.setGeometry(330, y, 501, 41)
            frame.setStyleSheet("background-color: rgba(0, 0, 0, 46); border-radius: 10px;")

        # Logo & cable
        self.label_logo_top = QLabel(self.HomePage)
        self.label_logo_top.setGeometry(640, 10, 281, 101)
        self.label_logo_top.setPixmap(QPixmap(resource_path("img/logo.png")))
        self.label_logo_top.setScaledContents(True)
        self.label_logo_top.setStyleSheet("background-color: transparent;")



        # Activate button
        self.activateButton = QPushButton("🚀 Activate device!", self.HomePage)
        self.activateButton.setGeometry(330, 415, 504, 41)
        self.activateButton.setFont(QFont("", 14))
        self.activateButton.setCursor(Qt.PointingHandCursor)
        self.activateButton.setStyleSheet(
            "background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, "
            "stop:0 rgba(21, 151, 255, 255), stop:1 rgba(113, 163, 168, 255));"
            "color: white; border-radius: 15px;"
        )

        # Progress bar
        self.pbFrame = QFrame(self.HomePage)
        self.pbFrame.setGeometry(330, 470, 504, 12)
        self.pbFrame.setStyleSheet("background-color: rgb(2, 33, 51); border-radius: 5px;")

        self.pb = QFrame(self.pbFrame)
        self.pb.setGeometry(0, 0, 0, 12)
        self.pb.setStyleSheet("background-color: rgb(19, 159, 255); border-radius: 5px;")

        # ——— Done Frame ———
        self.Done = QFrame(self.centralwidget)
        self.Done.setGeometry(0, -10, 921, 601)
        self.Done.setStyleSheet(
            "background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, "
            "stop:0 rgba(25, 25, 25, 255), stop:1 rgba(1, 27, 59, 255));"
        )

        self.label_done_ios = QLabel(self.Done)
        self.label_done_ios.setGeometry(60, 70, 201, 421)
        self.label_done_ios.setPixmap(QPixmap(resource_path("img/ios26hello.png")))
        self.label_done_ios.setScaledContents(True)
        

        self.DeviceName_3 = QLabel("Done!", self.Done)
        self.DeviceName_3.setGeometry(330, 100, 491, 41)
        self.DeviceName_3.setFont(QFont("Futura", 36))
        self.DeviceName_3.setStyleSheet("color: white; background-color: transparent;")

        self.UDID_3 = QLabel(
            "Thank you for using Rust_A12+! Your device has been successfully activated! "
            "Please complete the initial setup as usual.\n"
            "If you encounter any issues, please run the bypass process again.",
            self.Done
        )
        self.UDID_3.setGeometry(330, 160, 491, 171)
        self.UDID_3.setFont(QFont("Futura", 18))
        self.UDID_3.setStyleSheet("color: white; background-color: transparent;")
        self.UDID_3.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.UDID_3.setWordWrap(True)

        self.label_done_cable = QLabel(self.Done)
        self.label_done_cable.setGeometry(50, 450, 221, 151)
        self.label_done_cable.setPixmap(QPixmap(resource_path("img/cable.png")))
        self.label_done_cable.setScaledContents(True)
        self.label_done_cable.setStyleSheet("background-color: transparent;")

        self.label_done_logo = QLabel(self.Done)
        self.label_done_logo.setGeometry(640, 10, 281, 101)
        self.label_done_logo.setPixmap(QPixmap(resource_path("img/logo.png")))
        self.label_done_logo.setScaledContents(True)
        self.label_done_logo.setStyleSheet("background-color: transparent;")  # 👈 ДОБАВЛЕНО

        self.backToHomePage = QPushButton("◁️ Back to Home Page", self.Done)
        self.backToHomePage.setGeometry(330, 440, 481, 41)
        self.backToHomePage.setFont(QFont("", 18))
        self.backToHomePage.setCursor(Qt.PointingHandCursor)
        self.backToHomePage.setStyleSheet(
            "background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, "
            "stop:0 rgba(21, 151, 255, 255), stop:1 rgba(113, 163, 168, 255));"
            "color: white; border-radius: 15px;"
        )

        # ——— Visibility ———
        self.HomePage.hide()
        self.Done.hide()
        self.Intro.show()

    def setupConnections(self):
        self.activateButton.clicked.connect(self.StartThread)
        self.backToHomePage.clicked.connect(lambda: [self.Done.hide(), self.HomePage.show()])

    def setupConsole(self):
        self.console_frame = QFrame(self.centralwidget)
        self.console_frame.setGeometry(0, 480, 909, 60)
        self.console_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(8, 16, 32, 245);
                border-top: 2px solid rgba(60, 120, 255, 120);
            }
        """)
        self.console_frame.raise_()

        self.console = QTextEdit(self.console_frame)
        self.console.setGeometry(12, 6, 885, 48)
        self.console.setReadOnly(True)
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: #D0D8FF;
                font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
                font-size: 10pt;
                border: none;
                padding: 2px 6px;
            }
        """)
        self.console.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.console.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.console.append("<span style='color:#5577CC; font-weight:bold;'>Rust A12+ — Live Log</span>")
        self.console.append("<span style='color:#8888AA;'>Awaiting device connection...</span>")

        self.console_frame.show()
        self.console.show()
        print('v1.5 snapshot 25122025')

    ## Utility Methods
    def _run_cmd(self, cmd, timeout=None):
        """Run a subprocess command, return (returncode, stdout, stderr)"""
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return 124, "", "Timeout"
        except Exception as e:
            return 1, "", str(e)

    def _curl_download(self, url, filename):
        """Download file to /tmp, return full path on success, else False"""
        full_path = os.path.join(self.temp_dir, filename)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except:
                pass
        curl_cmd = ["curl", "-L", "-k", "-f", "-o", full_path, url]
        self.log(f"Starting download: {' '.join(curl_cmd)}", "info")
        code, out, err = self._run_cmd(curl_cmd)
        self.log(f"cURL exit code: {code}", "info")
        if code != 0:
            if err:
                self.log(f"cURL error: {err.strip()}", "error")
            self.log("Download failed", "error")
            return False
        if os.path.exists(full_path) and os.path.getsize(full_path) > 100:
            size_mb = os.path.getsize(full_path) / (1024 * 1024)
            self.log(f"Successfully downloaded {filename}: ~{size_mb:.2f} MB", "success")
            return full_path
        else:
            self.log("Downloaded file is empty or missing", "error")
            return False

    def reboot_device(self):
        """Reboot device and wait for it to reconnect"""
        self.log("Rebooting device...", "info")
        # Try pymobiledevice3 first
        code, _, err = self._run_cmd(["pymobiledevice3", "restart"])
        if code != 0:
            code, _, err = self._run_cmd(["idevicediagnostics", "restart"])
            if code != 0:
                self.log(f"Soft reboot failed: {err}", "warn")
                self.log("Please reboot device manually and press Enter to continue...", "warn")
                input()
                return True
        self.log("Reboot command sent. Waiting for device to reconnect...", "info")
        for i in range(60):  # up to 5 minutes
            time.sleep(5)
            code, _, _ = self._run_cmd(["ideviceinfo"])
            if code == 0:
                self.log(f"Device reconnected after {i * 5} seconds", "success")
                time.sleep(10)  # extra stabilization time
                return True
            if i % 6 == 0:
                self.log(f"Still waiting... ({i * 5} seconds)", "info")
        self.log("Device did not reconnect in time", "error")
        return False

    def _wait_for_device(self, timeout_sec: int) -> bool:
        """Wait for ideviceinfo to succeed within timeout_sec seconds."""
        start = time.time()
        while time.time() - start < timeout_sec:
            code, _, _ = self._run_cmd(["ideviceinfo"], timeout=5)
            if code == 0:
                self.log(f"Device reconnected after {int(time.time() - start)}s", "success")
                time.sleep(5)
                return True
            time.sleep(2)
        self.log(f"Timed out waiting for device ({timeout_sec}s)", "error")
        return False

    def verify_dependencies(self):
        self.log("Verifying system dependencies...", "info")
        self.afc_mode = "pymobiledevice3"
        self.log(f"AFC Transfer Mode: {self.afc_mode}", "info")

    def _cleanup(self):
        """Cleanup on exit"""
        pass

    def detect_device(self):
        """Fetch device info via ideviceinfo"""
        self.log("Detecting device...", "info")
        code, out, err = self._run_cmd(["ideviceinfo"])
        if code != 0:
            self.log(f"Device not found. Error: {err or 'Unknown'}", "error")
            sys.exit(1)
        info = {}
        for line in out.splitlines():
            if ": " in line:
                key, val = line.split(": ", 1)
                info[key.strip()] = val.strip()
        self.device_info = info
        udid = info.get('UniqueDeviceID', '?')
        self.log(f"UDID: {udid}", "info")
        if info.get('ActivationState') == 'Activated':
            self.log("⚠ Warning: Device is already activated", "warn")

    def collect_syslog_archive(self, archive_path: str, timeout: int = 200) -> bool:
        """Collect syslog as logarchive using pymobiledevice3"""
        self.log(f"[+] Collecting syslog archive → {os.path.basename(archive_path)} (timeout {timeout}s)", "info")
        cmd = ["pymobiledevice3", "syslog", "collect", archive_path]
        code, _, err = self._run_cmd(cmd, timeout=timeout + 30)
        if not os.path.isdir(archive_path):
            self.log("[-] Archive directory not created", "error")
            return False
        total_size = sum(
            os.path.getsize(os.path.join(dirpath, f))
            for dirpath, _, filenames in os.walk(archive_path)
            for f in filenames
            if os.path.isfile(os.path.join(dirpath, f))
        )
        size_mb = total_size // (1024 * 1024)
        if total_size < 10_000_000:  # <10 MB
            self.log(f"[-] Archive too small ({size_mb} MB)", "error")
            return False
        self.log(f"[✓] Archive collected: ~{size_mb} MB", "success")
        return True

    def extract_guid_from_archive(self, archive_path: str) -> Optional[str]:
        """Extract GUID from .logarchive using macOS `log show` command"""
        self.log("[+] Searching for GUID in archive using 'log show'...", "info")
        if not shutil.which("/usr/bin/log"):
            self.log("[-] '/usr/bin/log' not found — skipping log-show method", "warn")
            return None
        cmd = [
            "/usr/bin/log", "show",
            "--archive", archive_path,
            "--info", "--debug",
            "--style", "syslog",
            "--predicate", f'process == "bookassetd" AND eventMessage CONTAINS "{self.BLDB_FILENAME}"'
        ]
        code, stdout, stderr = self._run_cmd(cmd, timeout=self.timeouts['log_show_timeout'])
        if code != 0:
            self.log(f"[-] log show failed (code {code}): {stderr}", "error")
            return None
        for line in stdout.splitlines():
            if self.BLDB_FILENAME in line:
                self.log("[+] Found relevant line", "info")
                self.log(f" {line.strip()}", "info")
                match = self.GUID_REGEX.search(line)
                if match:
                    guid = match.group(0).upper()
                    self.log(f"[✓] GUID extracted: {guid}", "success")
                    return guid
        self.log("[-] GUID not found in archive", "error")
        return None

    def get_guid_auto_new(self, max_attempts: int = 5) -> Optional[str]:
        """New automatic GUID detection using syslog archive + log show"""
        for attempt in range(1, max_attempts + 1):
            self.log(f"\n=== GUID Extraction (Attempt {attempt}/{max_attempts}) ===\n", "attempt")
            # Step 1: Reboot
            if not self.reboot_device():
                if attempt == max_attempts:
                    self.log("[-] Final reboot failed — aborting", "error")
                    return None
                self.log("[-] Reboot failed — retrying...", "warn")
                continue
            # Step 2: Wait for device reconnect
            if not self._wait_for_device(180):
                if attempt == max_attempts:
                    self.log("[-] Device never reconnected — aborting", "error")
                    return None
                self.log("[-] Device not found — retrying...", "warn")
                continue
            # Step 3: Collect & parse archive
            with tempfile.TemporaryDirectory() as tmpdir:
                archive_path = os.path.join(tmpdir, "ios_logs.logarchive")
                if not self.collect_syslog_archive(archive_path, timeout=200):
                    self.log("[-] Failed to collect syslog archive", "error")
                    if attempt == max_attempts:
                        return None
                    continue
                guid = self.extract_guid_from_archive(archive_path)
                if guid and self.validate_guid_structure(guid):
                    self.global_GUID = guid
                    return guid
        self.log("[-] All attempts exhausted: GUID detection failed", "error")
        return None

    def get_guid_auto(self):
        """Try new method first, fall back to legacy if needed"""
        self.log("Trying NEW method (log show + archive parsing)...", "info")
        guid = self.get_guid_auto_new(max_attempts=3)
        if guid:
            return guid
        self.log("⚠ NEW method failed — falling back to legacy tracev3 parsing...", "warn")
        return self.get_guid_auto_with_retry()

    def get_guid_manual(self):
        """Prompt user to input GUID manually"""
        print(f"\n⚠ GUID Input Required")
        print(" Format: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX")
        print(" Example: 2A22A82B-C342-444D-972F-5270FB5080DF")
        UUID_PATTERN = re.compile(r'^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$', re.IGNORECASE)
        while True:
            guid_input = input("\n➤ Enter SystemGroup GUID: ").strip()
            if UUID_PATTERN.match(guid_input):
                return guid_input.upper()
            print("❌ Invalid format. Must be 8-4-4-4-12 hex chars (e.g. 2A22A82B-C342-444D-972F-5270FB5080DF).")

    def parse_tracev3_structure(self, data):
        """Search for known patterns in tracev3 file"""
        signatures = []
        db_patterns = [
            b'BLDatabaseManager',
            b'BLDatabase',
            b'BLDatabaseManager.sqlite',
            b'bookassetd [Database]: Store is at file:///private/var/containers/Shared/SystemGroup',
        ]
        for pattern in db_patterns:
            pos = 0
            while True:
                pos = data.find(pattern, pos)
                if pos == -1:
                    break
                signatures.append(('string', pattern, pos))
                pos += len(pattern)
        return signatures

    def extract_guid_candidates(self, data, context_pos, window_size=512):
        """Extract GUID candidates near a context position"""
        candidates = []
        guid_pattern = re.compile(
            rb'([0-9A-F]{8}[-][0-9A-F]{4}[-][0-9A-F]{4}[-][0-9A-F]{4}[-][0-9A-F]{12})',
            re.IGNORECASE
        )
        start = max(0, context_pos - window_size)
        end = min(len(data), context_pos + window_size)
        context_data = data[start:end]
        for match in guid_pattern.finditer(context_data):
            guid = match.group(1).decode('ascii').upper()
            relative_pos = match.start() + start - context_pos
            if self.validate_guid_structure(guid):
                candidates.append({
                    'guid': guid,
                    'position': relative_pos,
                    'context': self.get_context_string(context_data, match.start(), match.end())
                })
        return candidates

    def validate_guid_structure(self, guid):
        """Validate GUID conforms to RFC 4122 (version 4, variant 1)"""
        try:
            parts = guid.split('-')
            if len(parts) != 5:
                return False
            if not (len(parts[0]) == 8 and len(parts[1]) == len(parts[2]) == len(parts[3]) == 4 and len(parts[4]) == 12):
                return False
            hex_chars = set('0123456789ABCDEF')
            clean = guid.replace('-', '')
            if not all(c in hex_chars for c in clean):
                return False
            # Version must be 4
            if parts[2][0] != '4':
                return False
            # Variant must be 8/9/A/B
            if parts[3][0] not in '89AB':
                return False
            return True
        except Exception:
            return False

    def get_context_string(self, data, start, end, context_size=50):
        """Extract readable context around binary match"""
        context_start = max(0, start - context_size)
        context_end = min(len(data), end + context_size)
        context = data[context_start:context_end]
        try:
            return context.decode('utf-8', errors='replace')
        except:
            return binascii.hexlify(context).decode('ascii')

    def analyze_guid_confidence(self, guid_candidates):
        """Score & rank GUID candidates by recurrence and proximity"""
        if not guid_candidates:
            return None
        guid_counts = Counter(candidate['guid'] for candidate in guid_candidates)
        scored_guids = []
        for guid, count in guid_counts.items():
            score = count * 10
            positions = [c['position'] for c in guid_candidates if c['guid'] == guid]
            close_positions = [p for p in positions if abs(p) < 100]
            if close_positions:
                score += len(close_positions) * 5
            before_positions = [p for p in positions if p < 0]
            if before_positions:
                score += len(before_positions) * 3
            scored_guids.append((guid, score, count))
        scored_guids.sort(key=lambda x: x[1], reverse=True)
        return scored_guids

    def confirm_guid_manual(self, guid):
        """Prompt user to confirm low-confidence GUID (auto-confirm in GUI mode → 'y')"""
        self.log(f"GUID successfully parsed! {guid}", type="success")
        response = "y"
        self.global_GUID = guid
        return response

    def get_guid_enhanced(self):
        """Legacy tracev3 parsing with confidence scoring"""
        self.attempt_count += 1
        self.log(f"GUID search attempt {self.attempt_count}/{self.max_attempts}", "attempt")
        udid = self.UDID.text().replace("UDID: ", "")
        log_path = f"{udid}.logarchive"
        try:
            self.activateButton.setText(f"⏳ Searching GUID (Attempt {self.attempt_count} / {self.max_attempts}) ...")
            code, _, err = self._run_cmd(["pymobiledevice3", "syslog", "collect", log_path], timeout=120)
            if code != 0:
                self.log(f"Log collection failed: {err}", "error")
                return None
            trace_file = os.path.join(log_path, "logdata.LiveData.tracev3")
            if not os.path.exists(trace_file):
                self.log("tracev3 file not found", "error")
                return None
            with open(trace_file, 'rb') as f:
                data = f.read()
            size_mb = len(data) / (1024 * 1024)
            self.log(f"Analyzing tracev3 ({size_mb:.1f} MB)...", "info")
            signatures = self.parse_tracev3_structure(data)
            self.log(f"Found {len(signatures)} relevant signatures", "info")
            all_candidates = []
            for sig_type, pattern, pos in signatures:
                if pattern == b'BLDatabaseManager':
                    candidates = self.extract_guid_candidates(data, pos)
                    all_candidates.extend(candidates)
                    if candidates:
                        self.log(f"Found {len(candidates)} GUID candidates near BLDatabaseManager at 0x{pos:x}", "info")
            if not all_candidates:
                self.log("No valid GUID candidates found", "error")
                return None
            scored_guids = self.analyze_guid_confidence(all_candidates)
            if not scored_guids:
                return None
            self.log("GUID confidence analysis:", "info")
            for guid, score, count in scored_guids[:5]:
                self.log(f" {guid}: score={score}, occurrences={count}", "info")
            best_guid, best_score, best_count = scored_guids[0]
            if best_score >= 30:
                confidence = "HIGH"
                self.log(f"✅ HIGH CONFIDENCE: {best_guid} (score: {best_score})", "success")
            elif best_score >= 15:
                confidence = "MEDIUM"
                self.log(f"⚠️ MEDIUM CONFIDENCE: {best_guid} (score: {best_score})", "warn")
            else:
                confidence = "LOW"
                self.log(f"⚠️ LOW CONFIDENCE: {best_guid} (score: {best_score})", "warn")
            if confidence in ["LOW", "MEDIUM"]:
                self.log("Requesting manual confirmation for low-confidence GUID...", "warn")
                if not self.confirm_guid_manual(best_guid):
                    return None
            return best_guid
        finally:
            if os.path.exists(log_path):
                shutil.rmtree(log_path)

    def get_guid_auto_with_retry(self):
        """Retry enhanced GUID extraction up to max_attempts"""
        self.attempt_count = 0
        while self.attempt_count < self.max_attempts:
            guid = self.get_guid_enhanced()
            if guid:
                return guid
            if self.attempt_count < self.max_attempts:
                self.log(f"GUID not found in attempt {self.attempt_count}. Rebooting device and retrying...", "warn")
                if not self.reboot_device():
                    self.log("Failed to reboot device, continuing anyway...", "warn")
                self.log("Re-detecting device after reboot...", "info")
                self.detect_device()
                time.sleep(5)
            else:
                self.log(f"All {self.max_attempts} attempts exhausted", "error")
        return None

    def get_all_urls_from_server(self, prd, guid, sn):
        """Fetch payload URLs from remote server"""
        params = f"prd={prd}&guid={guid}&sn={sn}"
        url = f"{self.api_url}?{params}"
        self.log(text=f"Requesting all URLs from server: {url}", type="info")
        code, out, err = self._run_cmd(["curl", "-s", "-k", url])
        if code != 0:
            self.log(text=f"Server request failed: {err}", type="error")
            return None, None, None
        try:
            data = json.loads(out)
            if data.get('success'):
                stage1_url = data['links']['step1_fixedfile']
                stage2_url = data['links']['step2_bldatabase']
                stage3_url = data['links']['step3_final']
                return stage1_url, stage2_url, stage3_url
            else:
                self.log(text="Server returned error response", type="error")
                return None, None, None
        except json.JSONDecodeError:
            self.log(text="Server did not return valid JSON", type="error")
            return None, None, None

    def preload_stage(self, stage_name, stage_url):
        """Download payload stage to /tmp and clean up"""
        self.log(f"Pre-loading: {stage_name}...", "info")
        filename = f"temp_{stage_name}"
        result = self._curl_download(stage_url, filename)
        if result:
            self.log(f"Successfully pre-loaded {stage_name}", "success")
            try:
                os.remove(result)
            except:
                pass
            return True
        else:
            self.log(f"Warning: Failed to pre-load {stage_name}", "warning")
            self.activateButton.setText("❌ Failed to preload payload!")
            self.pb.setStyleSheet("background-color: rgb(252, 0, 6); border-radius: 5px;")
            QApplication.processEvents()
            return False

    ###############
    # Main Workflow
    ###############
    def StartThread(self):
        process = threading.Thread(target=self.Hacktivating)
        process.daemon = True
        process.start()

    def showPopup(self, title: str, text: str, type: str):
        """Show modal message box"""
        msg_box = QMessageBox()
        msg_box.setText(text)
        msg_box.setWindowTitle(title)
        msg_box.setStandardButtons(QMessageBox.Ok)
        if type == "info":
            msg_box.setIcon(QMessageBox.Information)
        elif type == "warning":
            msg_box.setIcon(QMessageBox.Warning)
        msg_box.exec_()

    def pull_file(self, remote: str, local: str) -> bool:
        code, _, _ = self._run_cmd(["pymobiledevice3", "afc", "pull", remote, local])
        return code == 0 and os.path.exists(local) and os.path.getsize(local) > 0

    def push_file(self, local: str, remote: str, keep_local=True) -> bool:
        """Загрузка файла на устройство"""
        self.log(f"📤 Pushing {os.path.basename(local)} to {remote}...", "detail")
        if not os.path.exists(local):
            self.log(f"❌ Local file not found: {local}", "error")
            return False
        file_size = os.path.getsize(local)
        self.log(f"  File size: {file_size} bytes", "detail")
        self.rm_file(remote)
        time.sleep(1)
        code, out, err = self._run_cmd(["pymobiledevice3", "afc", "push", local, remote])
        if code != 0:
            self.log(f"❌ Push failed - Code: {code}", "error")
            if err:
                self.log(f"  stderr: {err[:200]}", "detail")
            return False
        time.sleep(2)
        remote_dir = os.path.dirname(remote)
        code_list, list_out, _ = self._run_cmd(["pymobiledevice3", "afc", "ls", remote_dir])
        if remote in list_out or os.path.basename(remote) in list_out:
            self.log(f"✅ File confirmed on device at {remote}", "success")
            if not keep_local:
                try:
                    os.remove(local)
                    self.log(f"  Local file removed", "detail")
                except:
                    pass
            return True
        else:
            self.log(f"❌ File not found after push in {remote_dir}", "error")
            return False

    def rm_file(self, remote: str) -> bool:
        code, _, _ = self._run_cmd(["pymobiledevice3", "afc", "rm", remote])
        return code == 0 or "ENOENT" in _

    def Hacktivating(self):
        """Main activation workflow thread"""
        self.pbFrame.show()
        self.log("Process started!", "success")
        self.activateButton.setText("⏳ Connecting to device...")
        QApplication.processEvents()

        process = subprocess.Popen(['ideviceinfo'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.PIPE, text=True, bufsize=1)
        output = str(process.stdout.read())
        process.terminate()
        self.setProgress(10)

        if "ERROR: No device found!" in output:
            self.log("Failed to connect to device!", "error")
            self.log("Process finished with error.", "error")
            self.pb.setStyleSheet("background-color: rgb(252, 0, 6); border-radius: 5px;")
            self.activateButton.setText("❌ Failed to connect to device")
            QApplication.processEvents()
            return
        elif "ProductType" in output:
            self.log("Successfully connected to device!", "success")
        else:
            self.log("Failed to connect to device!", "error")
            self.pb.setStyleSheet("background-color: rgb(252, 0, 6); border-radius: 5px;")
            self.activateButton.setText("❌ Failed to connect to device")
            QApplication.processEvents()
            return

        try:
            prd = output.split("ProductType: ")[1].split("\n")[0]
            sn = output.split("SerialNumber: ")[1].split("\n")[0]
        except Exception as e:
            self.log(f"Failed to parse device info: {e}", "error")
            return

        self.activateButton.setText("⏳ Searching GUID (Attempt 1) ...")
        QApplication.processEvents()
        self.guid = self.get_guid_auto()
        self.log(f"Final GUID: {self.global_GUID}", "success")
        self.setProgress(20)

        self.activateButton.setText("⏳ Requesting payload...")
        QApplication.processEvents()
        stage1_url, stage2_url, stage3_url = self.get_all_urls_from_server(prd, self.guid, sn)
        if not all([stage1_url, stage2_url, stage3_url]):
            self.log("Failed to get URLs from server", "error")
            self.activateButton.setText("❌ Failed to get URLs from server!")
            self.pb.setStyleSheet("background-color: rgb(252, 0, 6); border-radius: 5px;")
            QApplication.processEvents()
            return

        self.log(f"Stage1 URL: {stage1_url}", "info")
        self.log(f"Stage2 URL: {stage2_url}", "info")
        self.log(f"Stage3 URL: {stage3_url}", "info")
        self.setProgress(30)

        self.activateButton.setText("⏳ Pre-loading payload...")
        QApplication.processEvents()
        for stage_name, stage_url in [("stage1", stage1_url), ("stage2", stage2_url), ("stage3", stage3_url)]:
            self.preload_stage(stage_name, stage_url)
            time.sleep(1)
        self.setProgress(35)

        self.log("Downloading final payload...", "info")
        self.activateButton.setText("⏳ Downloading Payload...")
        local_db = "downloads.28.sqlitedb"
        full_db_path = self._curl_download(stage3_url, local_db)
        if not full_db_path:
            self.log("Final payload download failed", "error")
            self.activateButton.setText("❌ Failed to download payload!")
            self.pb.setStyleSheet("background-color: rgb(252, 0, 6); border-radius: 5px;")
            return
        self.setProgress(45)

        self.log("Validating payload database...", "info")
        try:
            conn = sqlite3.connect(full_db_path)
            res = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='asset'")
            if res.fetchone()[0] == 0:
                raise Exception("Invalid DB - no asset table found")
            res = conn.execute("SELECT COUNT(*) FROM asset")
            count = res.fetchone()[0]
            if count == 0:
                raise Exception("Invalid DB - no records in asset table")
            self.log(f"Database validation passed — {count} records", "info")
            for row in conn.execute("SELECT pid, url, local_path FROM asset"):
                self.log(f"Record {row[0]}: {row[1]} → {row[2]}", "info")
        except Exception as e:
            self.log(f"Invalid payload received: {e}", "error")
            self.activateButton.setText("❌ Invalid Payload!")
            self.pb.setStyleSheet("background-color: rgb(252, 0, 6); border-radius: 5px;")
            return
        finally:
            conn.close()
        self.setProgress(50)

        self.activateButton.setText("⏳ Uploading Payload...")
        QApplication.processEvents()
        target = "/Downloads/downloads.28.sqlitedb"
        self.rm_file("/Downloads/downloads.28.sqlitedb")
        self.rm_file("/Downloads/downloads.28.sqlitedb-wal")
        self.rm_file("/Downloads/downloads.28.sqlitedb-shm")
        self.rm_file("/Books/asset.epub")
        self.rm_file("/Books/iTunesMetadata.plist")
        self.rm_file("/iTunes_Control/iTunes/iTunesMetadata.plist")
        self.rm_file("/iTunes_Control/iTunes/iTunesMetadata.plist.ext")
        if not self.push_file(full_db_path, target):
            try:
                os.remove(full_db_path)
            except:
                pass
            self.log("AFC upload failed", "error")
            self.activateButton.setText("❌ Upload failed!")
            self.pb.setStyleSheet("background-color: rgb(252, 0, 6); border-radius: 5px;")
            return
        self.log("✅ Payload deployed successfully", "success")
        self.setProgress(60)

        self.activateButton.setText("⏳ Cleaning up files...")
        self.log("Cleaning up WAL/SHM and auxiliary files in /Downloads /Books /iTunes_Control...", "info")
        cleanup_files = [
            "/Downloads/downloads.28.sqlitedb-wal",
            "/Downloads/downloads.28.sqlitedb-shm",
            "/Books/asset.epub",
            "/Books/iTunesMetadata.plist",
            "/iTunes_Control/iTunes/iTunesMetadata.plist",
            "/iTunes_Control/iTunes/iTunesMetadata.plist.ext"
        ]
        for wal_file in cleanup_files:
            code, _, err = self._run_cmd(["pymobiledevice3", "afc", "rm", wal_file])
            if code == 0:
                self.log(f"Removed {wal_file} via pymobiledevice3", "info")
            else:
                if "ENOENT" not in err and "No such file" not in err:
                    self.log(f"Warning removing {wal_file}: {err}", "warn")
                else:
                    self.log(f"{wal_file} not present — OK", "info")
        self.setProgress(65)

        self.log("🔄 STAGE 1: First reboot + copy to /Books/...", "info")
        self.activateButton.setText("⏳ Rebooting device...")
        QApplication.processEvents()
        if not self.reboot_device():
            self.log("⚠ First reboot failed — continuing anyway", "warn")
        self.log("Waiting 30 seconds for iTunesMetadata.plist to regenerate...", "info")
        self.activateButton.setText("⏳ Waiting for iTunesMetadata.plist")
        for _ in range(10):
            time.sleep(5)
            self.log(" ▫ Waiting...", "info")
        src = "/iTunes_Control/iTunes/iTunesMetadata.plist"
        dst_books = "/Books/iTunesMetadata.plist"
        tmp = os.path.join(self.temp_dir, "temp_plist_copy.plist")
        self.log(f"Copying {src} → {dst_books}...", "info")
        if self.pull_file(src, tmp):
            if self.push_file(tmp, dst_books):
                self.log("✅ Copied to /Books/ successfully", "success")
            else:
                self.log("⚠ Failed to push to /Books/", "warn")
            try:
                os.remove(tmp)
            except:
                pass
        else:
            self.log("⚠ /iTunes_Control/iTunes/iTunesMetadata.plist not found — skipping copy to /Books/", "warn")
        self.activateButton.setText("⏳ Rebooting device...")
        self.setProgress(75)
        QApplication.processEvents()

        self.log("🔄 STAGE 2: Second reboot + copy back to /iTunes_Control/...", "info")
        if not self.reboot_device():
            self.log("⚠ Second reboot failed — continuing anyway", "warn")
        time.sleep(10)
        self.activateButton.setText("⏳ Copying to /iTunesControl/")
        self.setProgress(85)
        self.log(f"Copying {dst_books} → {src}...", "info")
        if self.pull_file(dst_books, tmp):
            if self.push_file(tmp, src):
                self.log("✅ Copied back to /iTunes_Control/ successfully", "success")
            else:
                self.log("⚠ Failed to restore plist", "warn")
            try:
                os.remove(tmp)
            except:
                pass
        else:
            self.log("⚠ /Books/iTunesMetadata.plist missing — copy-back skipped", "warn")

        self.log("⏸ Holding 30s for bookassetd processing...", "info")
        self.activateButton.setText("⏳ Waiting for bookassetd...")
        self.setProgress(90)
        time.sleep(30)

        self.activateButton.setText("✅ Done! Activate your device as usual.")
        self.setProgress(100)
        self.log("🔄 Final reboot to trigger MobileActivation...", "info")
        self.reboot_device()
        time.sleep(5)
        self.Done.show()

    def setProgress(self, progress: float):
        """Animate progress bar"""
        new_width = round(progress * 5.04)  # 504px / 100%
        step = 1 if new_width > self.pb.width() else -1
        while self.pb.width() != new_width:
            time.sleep(0.004)
            self.pb.setFixedWidth(self.pb.width() + step)
            QApplication.processEvents()

    def SearchingDevices(self):
        """Background thread: wait for device connection and populate HomePage"""
        while True:
            process = subprocess.Popen(['ideviceinfo'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.PIPE, text=True, bufsize=1)
            output = str(process.stdout.read())
            process.terminate()
            if "ERROR: No device found!" in output:
                self.label_status.setText("⏳ Searching for devices...")
            else:
                self.label_status.setText("✅ Connected!")
                time.sleep(0.3)
                try:
                    ProductVersion = output.split("ProductVersion: ")[1].split("\n")[0]
                    ProductType = output.split("ProductType: ")[1].split("\n")[0]
                    UDID = output.split("UniqueDeviceID: ")[1].split("\n")[0]
                    DeviceName = output.split("DeviceName: ")[1].split("\n")[0]
                    ActivationState = output.split("ActivationState: ")[1].split("\n")[0]
                except Exception as e:
                    self.log(f"Could not parse device info: {e}", "error")
                    self.showPopup("Error", "Could not get device info!", "warning")
                    break
                self.log("Device connected!", "success")
                self.log(f"Detected device:\n iOS Version: {ProductVersion}\n Product Type: {ProductType}\n UDID: {UDID}\n Device Name: {DeviceName}", "none")
                self.Intro.hide()
                self.HomePage.show()
                self.DeviceName.setText(f"📱 {DeviceName}")
                self.UDID.setText(f"UDID: {UDID}")
                self.iOSVersion.setText(f"iOS Version: {ProductVersion}")
                self.ProductType.setText(f"Product Type: {ProductType}")
                self.ActivationState.setText(f"Activation State: {ActivationState}")
                supported_versions = {"26.0.1", "26.0", "18.7.2", "18.7.1"}
                if ProductVersion in supported_versions:
                    self.log("Device is SUPPORTED!", "success")
                    self.activateButton.setText("🚀 Activate device!")
                    self.activateButton.setStyleSheet("""
                    background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 rgba(21, 151, 255, 255), stop:1 rgba(113, 163, 168, 255));
                    color: rgb(255, 255, 255);
                    border-radius: 15px;
                    """)
                    self.ProductType_3.setText("SUPPORTED!")
                    self.ProductType_3.setStyleSheet("color: rgb(34, 255, 16); background-color: rgba(255, 255, 255, 0);")
                break    
    def log(self, text: str, type: str = "info"):
        """Log to GUI console and stdout"""
        colors = {
            "info": "#88AAFF",
            "warning": "#FFFF88",
            "warn": "#FFFF88",
            "error": "#FF6666",
            "success": "#66FF88",
            "attempt": "#88CCFF",
            "progress": "#CCCCCC",
            "none": "#D0D8FF",
        }
        color = colors.get(type, "#FFFFFF")
        prefix = {
            "info": "ℹ",
            "warning": "⚠",
            "warn": "⚠",
            "error": "✗",
            "success": "✓",
            "attempt": "⟳",
            "progress": "⏳",
            "none": "•",
        }.get(type, "•")
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f'<span style="color:{color};">[{timestamp}] {prefix} {text}</span>'
        if hasattr(self, 'console'):
            self.console.append(line)
            scrollbar = self.console.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            QApplication.processEvents()
        print(f"[{timestamp}] {prefix} {text}")

    def retranslateUi(self, MainWindow):
        _translate = QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "Rust A12+"))


# ——— Entry Point ———
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Rust A12+")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())