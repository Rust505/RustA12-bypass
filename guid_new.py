# -*- coding: utf-8 -*-
"""
Rust A12+ (Windows) — GUID Extractor CLI
Author: Anonymous / Rust505
Note: Educational/research purposes only.
"""
import os
import sys
import re
import time
import json
import shutil
import tempfile
import subprocess
import threading
import datetime
import argparse
from pathlib import Path
from typing import Optional, List, Tuple

try:
    from pymobiledevice3.services.os_trace import OsTraceService
    from pymobiledevice3.lockdown import create_using_usbmux
except ImportError:
    print("[ERROR] Missing dependency: pymobiledevice3. Install via: pip install pymobiledevice3")
    sys.exit(1)

# --- Configuration & Constants ---
if sys.platform == "win32":
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0

GUID_REGEX_B = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
TARGET_PROCESS = "bookassetd"
BLDB_FILENAME = "BLDatabaseManager.sqlite"
TARGET_PATH = "/private/var/containers/Shared/SystemGroup/"
POST_CONNECT_DELAY = 12
SYSLOG_RETRIES = 3
SYSLOG_RETRY_DELAY = 15
MIN_ARCHIVE_SIZE = 10_000_000

# --- ANSI Colors for CLI ---
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

# --- Logging Helper ---
def log(text: str, level: str = "info"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    icons = {
        "info": "ℹ", "warn": "⚠", "error": "✗", "success": "✓", "detail": "▸", "attempt": "⟳"
    }
    colors = {
        "info": Colors.CYAN, "warn": Colors.YELLOW, "error": Colors.RED,
        "success": Colors.GREEN, "detail": Colors.GRAY, "attempt": Colors.BLUE
    }
    
    icon = icons.get(level, "•")
    color = colors.get(level, Colors.WHITE)
    
    print(f"{color}[{ts}] {icon} {text}{Colors.RESET}")
    sys.stdout.flush()

# --- File & Path Helpers ---
def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent

def get_bin_dir() -> Path:
    return get_base_dir() / "bin"

def find_binary(name: str) -> Optional[str]:
    bin_dir = get_bin_dir()
    path = bin_dir / name
    if path.is_file():
        return str(path)
    return shutil.which(name)

def run_short_command(cmd: List[str], timeout: Optional[int] = None) -> Tuple[int, str, str]:
    try:
        bin_dir = str(get_bin_dir())
        env = os.environ.copy()
        env["PATH"] = bin_dir + os.pathsep + env["PATH"]
        
        # Windows specific startup info to hide console windows of children
        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = CREATE_NO_WINDOW

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
            env=env,
            startupinfo=startupinfo
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)

# --- Device Interaction ---
class DeviceManager:
    def __init__(self):
        self.active_processes = []

    def ideviceinfo_cmd(self, *args) -> List[str]:
        exe = find_binary("ideviceinfo.exe")
        if exe:
            return [exe, *args]
        return ["ideviceinfo", *args] # Fallback to system path name

    def idevicediagnostics_cmd(self, *args) -> List[str]:
        exe = find_binary("idevicediagnostics.exe")
        if exe:
            return [exe, *args]
        return ["idevicediagnostics", *args]

    def get_device_info(self) -> Optional[dict]:
        info = {}
        keys = ["DeviceName", "ProductType", "ProductVersion", "BuildVersion", "SerialNumber", "UniqueDeviceID", "ActivationState"]
        for key in keys:
            cmd = self.ideviceinfo_cmd("-k", key)
            code, out, _ = run_short_command(cmd, timeout=10)
            if code == 0 and out.strip():
                info[key] = out.strip()
        return info or None

    def restart_device(self) -> bool:
        log("[+] Sending device reboot command...", "info")
        cmd = self.idevicediagnostics_cmd("restart")
        code, out, err = run_short_command(cmd, timeout=30)
        if code == 0:
            log("[✓] Reboot command sent", "success")
            return True
        log("[-] Reboot failed", "error")
        if err.strip():
            log("    " + err.strip(), "detail")
        return False

    def wait_for_device(self, timeout: int = 65) -> bool:
        log("[+] Waiting for device to reconnect...", "info")
        start = time.time()
        last_seen = False
        while time.time() - start < timeout:
            cmd = self.ideviceinfo_cmd()
            code, out, err = run_short_command(cmd, timeout=15)
            if code == 0 and "ERROR:" not in out and "No device found" not in out:
                if not last_seen:
                    log("[✓] Device detected", "success")
                    last_seen = True
                
                udid_cmd = self.ideviceinfo_cmd("-k", "UniqueDeviceID")
                udid_code, udid_out, _ = run_short_command(udid_cmd, timeout=10)
                if udid_code == 0 and udid_out.strip():
                    log(f"[+] Verified device UDID: {udid_out.strip()[:8]}...", "info")
                    log(f"[+] Waiting {POST_CONNECT_DELAY}s for services to stabilize...", "info")
                    time.sleep(POST_CONNECT_DELAY)
                    return True
                else:
                    log("[i] Device seen but UDID not ready yet — waiting...", "detail")
            else:
                if last_seen:
                    log("[i] Device disconnected again — still waiting...", "warn")
                    last_seen = False
            time.sleep(4)
        log("[-] Timeout waiting for device to reconnect", "error")
        return False

    def collect_syslog_archive(self, archive_path: Path) -> bool:
        log(f"[+] Collecting syslog archive → {archive_path}", "info")
        with tempfile.TemporaryDirectory() as temp_dir:
            log_archive_path = Path(temp_dir) / "syslog.logarchive"
            try:
                log("[i] Connecting to device via USBMUX (auto-select)...", "info")
                with create_using_usbmux() as lockdown:
                    with OsTraceService(lockdown) as os_trace:
                        log("[i] Starting native syslog collection...", "info")
                        os_trace.collect(
                            out=str(log_archive_path),
                            size_limit=12000,
                            age_limit=3600,
                            start_time=0
                        )
                if not log_archive_path.exists():
                    log("[-] Syslog archive was not created", "error")
                    return False
                
                archive_path.mkdir(parents=True, exist_ok=True)
                if log_archive_path.is_file():
                    shutil.copy2(log_archive_path, archive_path / "syslog.logarchive")
                elif log_archive_path.is_dir():
                    for item in log_archive_path.rglob("*"):
                        if item.is_file():
                            rel = item.relative_to(log_archive_path)
                            dst = archive_path / rel
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, dst)
                else:
                    log("[-] Unexpected archive type", "error")
                    return False
                
                total_size = sum(f.stat().st_size for f in archive_path.rglob("*") if f.is_file())
                size_mb = total_size // (1024 * 1024)
                if total_size >= MIN_ARCHIVE_SIZE:
                    log(f"[✓] Archive collected: ~{size_mb} MB", "success")
                    return True
                else:
                    log(f"[!] Archive too small (~{size_mb} MB)", "warn")
                    return False
            except Exception as e:
                log(f"[-] Failed to collect syslog: {e}", "error")
                return False

    def extract_guid_from_archive(self, archive_path: Path, debug_logs: bool = False) -> Optional[str]:
        exe = find_binary("unifiedlog_iterator.exe")
        if not exe:
            log("[-] unifiedlog_iterator.exe not found in ./bin or PATH", "error")
            return None
        
        cmd = [exe, "--mode", "log-archive", "--input", str(archive_path), "--format", "jsonl"]
        log("[+] Searching GUID in Unified Logs", "info")
        
        bldb_patterns = [b"BLDatabaseManager.sqlite", b"BLDatabaseManager", b"BLDatabase"]
        bldb_patterns_upper = [p.upper() for p in bldb_patterns]
        guid_regex = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')

        def is_relevant_fast(buf: bytes, start: int, end: int) -> bool:
            segment = buf[start:end]
            seg_upper = segment.upper()
            return any(pat in seg_upper for pat in bldb_patterns_upper)

        def validate_guid_bytes(guid_bytes: bytes) -> Optional[str]:
            try:
                guid = guid_bytes.decode("ascii").upper()
                parts = guid.split('-')
                if len(parts) != 5:
                    return None
                if not (len(parts[0]) == 8 and len(parts[1]) == 4 and
                        len(parts[2]) == 4 and len(parts[3]) == 4 and
                        len(parts[4]) == 12):
                    return None
                if parts[2][0] != '4':
                    return None
                if parts[3][0] not in '89AB':
                    return None
                clean = guid.replace('-', '')
                if not all(c in '0123456789ABCDEF' for c in clean):
                    return None
                return guid
            except Exception:
                return None

        startup_kwargs = {}
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            startup_kwargs.update({"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW})

        proc = None
        state = {"lines_scanned": 0, "lines_matched": 0, "last_stdout_time": time.time()}
        start_time = time.time()
        last_progress = start_time
        PROGRESS_INTERVAL = 10.0
        CHUNK_SIZE = 4 * 1024 * 1024

        debug_log_file = None
        if debug_logs:
            debug_log_file = open("decrypted_logs.txt", "w", encoding="utf-8", buffering=8192*1024)
            log("[i] Debug logs enabled → decrypted_logs.txt", "info")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=False,
                bufsize=CHUNK_SIZE,
                **startup_kwargs
            )
            self.active_processes.append(proc)
            buf = bytearray()
            scan_pos = 0
            
            while proc.poll() is None:
                chunk = proc.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                state["last_stdout_time"] = time.time()
                buf.extend(chunk)
                
                while True:
                    nl = buf.find(b"\n", scan_pos)
                    if nl == -1:
                        if scan_pos > 0:
                            del buf[:scan_pos]
                            scan_pos = 0
                        break
                    start, end = scan_pos, nl
                    scan_pos = nl + 1
                    state["lines_scanned"] += 1
                    
                    if not is_relevant_fast(buf, start, end):
                        continue
                    
                    state["lines_matched"] += 1
                    raw_line = bytes(buf[start:end])
                    
                    if debug_log_file:
                        try:
                            pat = b'"message":"'
                            i = raw_line.find(pat)
                            if i != -1:
                                j = i + len(pat)
                                out = bytearray()
                                esc = False
                                while j < len(raw_line):
                                    c = raw_line[j]
                                    if esc:
                                        out.append(c)
                                        esc = False
                                    else:
                                        if c == 0x5C: # Backslash
                                            esc = True
                                        elif c == 0x22: # Quote
                                            break
                                        else:
                                            out.append(c)
                                    j += 1
                                if out:
                                    debug_log_file.write(out.decode('utf-8', errors='replace') + "\n")
                        except Exception:
                            pass
                    
                    m = guid_regex.search(raw_line)
                    if m:
                        guid_candidate = m.group(0)
                        validated_guid = validate_guid_bytes(guid_candidate)
                        if validated_guid:
                            elapsed = time.time() - start_time
                            log(f"[✓] GUID FOUND after {elapsed:.2f}s ({state['lines_scanned']:,} lines scanned)", "success")
                            log(f"[✓] GUID: {validated_guid}", "success")
                            log(f"[i] Matched {state['lines_matched']:,} relevant entries", "info")
                            if debug_log_file:
                                debug_log_file.flush()
                                debug_log_file.close()
                            proc.terminate()
                            try:
                                proc.wait(timeout=3)
                            except:
                                proc.kill()
                            if proc in self.active_processes:
                                self.active_processes.remove(proc)
                            return validated_guid
                    
                    now = time.time()
                    if now - last_progress >= PROGRESS_INTERVAL:
                        elapsed = now - start_time
                        rate = state["lines_scanned"] / elapsed if elapsed > 0 else 0
                        log(f"[i] Scanned {state['lines_scanned']:,} lines ({state['lines_matched']:,} matched) in {elapsed:.1f}s ({rate:,.0f} lines/s)", "info")
                        last_progress = now
            
            elapsed = time.time() - start_time
            log(f"[-] No GUID found after scanning {state['lines_scanned']:,} lines ({state['lines_matched']:,} matched) in {elapsed:.1f}s", "error")
            if state["lines_matched"] == 0:
                log("[!] WARNING: No BLDatabase-related activity detected.", "warn")
            return None

        except Exception as e:
            log(f"[-] Error during log parsing: {e}", "error")
            import traceback
            log(f"[detail] Traceback: {traceback.format_exc()}", "detail")
            return None
        finally:
            if debug_log_file:
                try:
                    debug_log_file.flush()
                    debug_log_file.close()
                    log("[i] Full decrypted logs saved to 'decrypted_logs.txt'", "info")
                except Exception:
                    pass
            if proc:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                try:
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()
                except Exception:
                    pass
                if proc in self.active_processes:
                    self.active_processes.remove(proc)

    def get_guid_auto(self, debug_logs: bool = False) -> Optional[str]:
        MAX_ATTEMPTS = 3
        RETRY_DELAY = 10
        for attempt in range(1, MAX_ATTEMPTS + 1):
            log(f"[+] Starting GUID extraction attempt {attempt}/{MAX_ATTEMPTS}", "info")
            log("🔄 Restarting device to trigger logs...", "info")
            
            # In CLI, we might want to skip reboot if requested, but logic assumes reboot for fresh logs
            if not (self.restart_device() and self.wait_for_device(timeout=60)):
                log("⚠️ error reconnect", "error")
                return None
            
            with tempfile.TemporaryDirectory() as tmpdir:
                archive_path = Path(tmpdir) / "ios_logs.logarchive"
                if not self.collect_syslog_archive(archive_path):
                    log(f"[-] Attempt {attempt}: Failed to collect syslog archive", "error")
                    if attempt < MAX_ATTEMPTS:
                        log(f"[i] Waiting {RETRY_DELAY}s before retry...", "info")
                        time.sleep(RETRY_DELAY)
                        continue
                
                guid = self.extract_guid_from_archive(archive_path, debug_logs=debug_logs)
                if guid:
                    return guid
                
                log(f"[-] Attempt {attempt}: No GUID found in collected logs", "warn")
                if attempt < MAX_ATTEMPTS:
                    log(f"[i] Waiting {RETRY_DELAY}s before next attempt...", "info")
                    time.sleep(RETRY_DELAY)
        
        log(f"[-] GUID extraction failed after {MAX_ATTEMPTS} attempts", "error")
        return None

    def cleanup(self):
        for proc in self.active_processes[:]:
            try:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=3)
            except:
                pass
            if proc in self.active_processes:
                self.active_processes.remove(proc)

# --- Main Execution ---
def validate_guid(guid: str) -> bool:
    pattern = r'^[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$'
    return bool(re.fullmatch(pattern, guid.upper()))

def main():
    parser = argparse.ArgumentParser(description="Rust A12+ — GUID Extractor CLI")
    parser.add_argument("--manual-guid", type=str, help="Use a manually provided GUID instead of extracting")
    parser.add_argument("--no-reboot", action="store_true", help="Skip device reboot (use existing logs)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging (saves decrypted_logs.txt)")
    parser.add_argument("--output", type=str, help="Save result to file")
    
    args = parser.parse_args()

    print(f"{Colors.BOLD}RUST A12+ — GUID Extractor (CLI){Colors.RESET}")
    print("-" * 40)

    if args.manual_guid:
        if not validate_guid(args.manual_guid):
            log("[-] Invalid GUID format. Must be UUID v4.", "error")
            sys.exit(1)
        final_guid = args.manual_guid.upper()
        log(f"[✓] Using manual GUID: {final_guid}", "success")
    else:
        dm = DeviceManager()
        
        # Check connection first
        log("[i] Checking device connection...", "info")
        info = dm.get_device_info()
        if not info:
            log("❌ Device not detected. Please connect via USB and trust computer.", "error")
            sys.exit(1)
        
        prd = info.get("ProductType", "unknown")
        ios_version_raw = info.get("ProductVersion", "unknown")
        sn = info.get("SerialNumber", "unknown")
        log(f"Detected: {prd} | iOS {ios_version_raw} | Serial: {sn}", "info")

        if args.no_reboot:
            log("[!] Skipping reboot as requested. Extraction might fail if logs are stale.", "warn")
            # For no-reboot, we just try to collect once without the loop in get_guid_auto
            with tempfile.TemporaryDirectory() as tmpdir:
                archive_path = Path(tmpdir) / "ios_logs.logarchive"
                if dm.collect_syslog_archive(archive_path):
                    final_guid = dm.extract_guid_from_archive(archive_path, debug_logs=args.debug)
                else:
                    final_guid = None
        else:
            final_guid = dm.get_guid_auto(debug_logs=args.debug)
        
        dm.cleanup()

        if not final_guid:
            log("❌ GUID extraction failed completely.", "error")
            sys.exit(1)

    print("-" * 40)
    log(f"✅ FINAL GUID: {final_guid}", "success")
    
    if args.output:
        try:
            with open(args.output, "w") as f:
                f.write(final_guid)
            log(f"[i] GUID saved to {args.output}", "info")
        except Exception as e:
            log(f"[-] Failed to save output file: {e}", "error")

if __name__ == "__main__":
    if sys.platform != "win32":
        print("⚠ This build is primarily tested on Windows.")
        # Continue anyway for Linux/Mac users who might have adapted binaries
    
    # Ensure multiprocessing freeze support for PyInstaller if frozen
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()
        
    try:
        main()
    except KeyboardInterrupt:
        log("\n[!] Interrupted by user.", "warn")
        sys.exit(130)
    except Exception as e:
        log(f"[!] Unexpected error: {e}", "error")
        sys.exit(1)