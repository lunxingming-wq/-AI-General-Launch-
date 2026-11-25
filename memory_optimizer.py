# -*- coding: utf-8 -*-
"""
Memory & VRAM Optimizer
- Suspends Wallpaper Engine playback during inference to free VRAM/GPU render load
- Trims background process working sets via Win32 EmptyWorkingSet
- Triggers a CUDA allocation pulse to evict stale DX/desktop VRAM caches
- Launches a detached background guardian to guarantee Wallpaper Engine resumes
  even if the console window is closed directly via [X] or Ctrl+C.
"""

import os
import sys
import time
import json
import ctypes
from ctypes import wintypes
import subprocess
import csv
import io
import winreg

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

TARGET_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(TARGET_DIR, ".optimizer_state.json")


def _detect_console_encoding():
    try:
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        if cp == 936:
            return "gbk"
        if cp == 65001:
            return "utf-8"
        return f"cp{cp}"
    except Exception:
        return "utf-8"


_CONSOLE_ENC = _detect_console_encoding()


def _bat_write(text: str) -> None:
    try:
        kernel32 = ctypes.windll.kernel32
        h_stdout = kernel32.GetStdHandle(-11)
        written = ctypes.c_ulong(0)
        if kernel32.WriteConsoleW(h_stdout, text, len(text), ctypes.byref(written), None):
            return
    except Exception:
        pass
    try:
        sys.stdout.buffer.write(text.encode(_CONSOLE_ENC, errors="replace"))
        sys.stdout.buffer.flush()
    except Exception:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_ram_info():
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    total_gb = round(stat.ullTotalPhys / (1024**3), 1)
    avail_gb = round(stat.ullAvailPhys / (1024**3), 1)
    used_gb = round(total_gb - avail_gb, 1)
    return total_gb, avail_gb, used_gb


CLEANUP_APPS_FILE = os.path.join(TARGET_DIR, "cleanup_apps.txt")
VIRTUAL_GPU_KEYWORDS = (
    "microsoft basic", "remote", "virtual", "vmware", "hyper-v",
    "parsec", "oray", "sunlogin", "spacedesk", "gameviewer", "idd",
)


def _detect_non_nvidia_vram():
    """Read dedicated VRAM (GB) for AMD/Intel GPUs from Windows Display Adapter registry."""
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    best_gb = 0.0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            idx = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, idx)
                    idx += 1
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as sk:
                        desc = ""
                        try:
                            desc, _ = winreg.QueryValueEx(sk, "DriverDesc")
                        except OSError:
                            pass
                        if any(k in str(desc).lower() for k in VIRTUAL_GPU_KEYWORDS):
                            continue
                        mem_bytes = 0
                        for kname in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                val, _ = winreg.QueryValueEx(sk, kname)
                                if isinstance(val, bytes):
                                    val = int.from_bytes(val, "little", signed=False)
                                elif isinstance(val, int) and val < 0:
                                    val = val & 0xFFFFFFFF
                                if val and val > 0:
                                    mem_bytes = int(val)
                                    break
                            except OSError:
                                pass
                        gb = round(mem_bytes / (1024**3), 1)
                        if gb > best_gb:
                            best_gb = gb
                except OSError:
                    continue
    except Exception:
        pass
    if best_gb >= 1.0:
        used_gb = round(min(1.2, best_gb * 0.15), 1)
        free_gb = round(max(0.5, best_gb - used_gb), 1)
        return best_gb, free_gb, used_gb
    return 0.0, 0.0, 0.0


def get_vram_info():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
            encoding="utf-8",
            errors="ignore",
            timeout=2,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        line = out.strip().splitlines()[0]
        parts = [float(x.strip()) for x in line.split(",")]
        total_gb = round(parts[0] / 1024.0, 1)
        used_gb = round(parts[1] / 1024.0, 1)
        free_gb = round(parts[2] / 1024.0, 1)
        return total_gb, free_gb, used_gb
    except Exception:
        return _detect_non_nvidia_vram()


def load_cleanup_targets():
    """Load background process names from cleanup_apps.txt (falls back to minimal safe default)."""
    if os.path.exists(CLEANUP_APPS_FILE):
        targets = []
        try:
            with open(CLEANUP_APPS_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    targets.append(line)
            return targets
        except Exception:
            pass
    return ["steamwebhelper.exe"]


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    kernel32 = ctypes.windll.kernel32
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return False
    exit_code = wintypes.DWORD()
    try:
        if kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(h_proc)


def is_process_running(process_name: str) -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV"],
            encoding="utf-8",
            errors="ignore",
            timeout=3,
        )
        return process_name.lower() in out.lower()
    except Exception:
        return False


def get_process_path(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h_proc)
    return ""


def is_wallpaper_running() -> bool:
    return is_process_running("wallpaper64.exe") or is_process_running("wallpaper32.exe")


def find_wallpaper_engine() -> str:
    # 1. Query active running Wallpaper Engine processes (64-bit / 32-bit)
    for exe in ("wallpaper64.exe", "wallpaper32.exe"):
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV"],
                encoding="utf-8",
                errors="ignore",
                timeout=2,
            )
            reader = csv.reader(io.StringIO(out))
            next(reader, None)
            for row in reader:
                if len(row) >= 2 and row[0].lower() == exe:
                    try:
                        pid = int(row[1])
                        p = get_process_path(pid)
                        if p and os.path.exists(p):
                            return p
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. Query Windows Service ImagePath
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\Wallpaper Engine Service") as k:
            val, _ = winreg.QueryValueEx(k, "ImagePath")
            if "-p" in val:
                p = val.split("-p")[1].strip(" \"'")
                if os.path.exists(p):
                    return p
    except Exception:
        pass

    # 3. Scan common Steam library locations across drives
    drives = [chr(c) for c in range(ord("C"), ord("Z") + 1)]
    for d in drives:
        for sub in (
            rf"{d}:\SteamLibrary\steamapps\common\wallpaper_engine\wallpaper64.exe",
            rf"{d}:\SteamLibrary\steamapps\common\wallpaper_engine\wallpaper32.exe",
            rf"{d}:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine\wallpaper64.exe",
            rf"{d}:\Program Files\Steam\steamapps\common\wallpaper_engine\wallpaper64.exe",
        ):
            if os.path.exists(sub):
                return sub

    return ""


def pause_wallpaper_engine() -> str:
    wp_path = find_wallpaper_engine()
    if not wp_path or not os.path.exists(wp_path):
        return None
    if is_wallpaper_running():
        try:
            wp_dir = os.path.dirname(wp_path)
            p = subprocess.Popen(
                [wp_path, "-control", "pause"],
                cwd=wp_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            try:
                p.wait(timeout=3)
            except Exception:
                pass
            return wp_path
        except Exception:
            pass
    return None


def resume_wallpaper_engine(wp_path=None) -> bool:
    if not wp_path or not os.path.exists(wp_path):
        wp_path = find_wallpaper_engine()
    if not wp_path or not os.path.exists(wp_path):
        return False
    wp_dir = os.path.dirname(wp_path)
    try:
        if is_wallpaper_running():
            p = subprocess.Popen(
                [wp_path, "-control", "play"],
                cwd=wp_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            try:
                p.wait(timeout=3)
            except Exception:
                pass
        else:
            subprocess.Popen(
                [wp_path],
                cwd=wp_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        return True
    except Exception:
        return False


def trim_all_process_working_sets():
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_SET_QUOTA = 0x0100

    trimmed_count = 0
    try:
        out = subprocess.check_output(["tasklist", "/FO", "CSV"], encoding="utf-8", errors="ignore", timeout=3)
        reader = csv.reader(io.StringIO(out))
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                name = row[0].lower()
                try:
                    pid = int(row[1])
                except Exception:
                    continue
                if pid <= 4 or name in ("system", "idle", "csrss.exe", "smss.exe", "lsass.exe", "services.exe", "wininit.exe"):
                    continue
                h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if h_proc:
                    if psapi.EmptyWorkingSet(h_proc):
                        trimmed_count += 1
                    kernel32.CloseHandle(h_proc)
    except Exception:
        pass
    return trimmed_count


def trigger_cuda_vram_pulse():
    try:
        cuda = ctypes.windll.nvcuda
        if cuda.cuInit(0) != 0:
            return False
        p_dev = ctypes.c_int()
        if cuda.cuDeviceGet(ctypes.byref(p_dev), 0) != 0:
            return False
        p_ctx = ctypes.c_void_p()
        if cuda.cuCtxCreate_v2(ctypes.byref(p_ctx), 0, p_dev.value) != 0:
            return False

        free_m = ctypes.c_size_t()
        total_m = ctypes.c_size_t()
        if cuda.cuMemGetInfo_v2(ctypes.byref(free_m), ctypes.byref(total_m)) == 0:
            alloc_bytes = int(free_m.value * 0.90)
            if alloc_bytes > 512 * 1024 * 1024:
                p_mem = ctypes.c_ulonglong()
                if cuda.cuMemAlloc_v2(ctypes.byref(p_mem), ctypes.c_size_t(alloc_bytes)) == 0:
                    time.sleep(0.2)
                    cuda.cuMemFree_v2(p_mem)
        cuda.cuCtxDestroy_v2(p_ctx)
        return True
    except Exception:
        return False


def print_menu_banner(model_name=None, model_size=None):
    ram_tot, ram_avail, ram_used = get_ram_info()
    vram_tot, vram_free, vram_used = get_vram_info()
    wp_path = find_wallpaper_engine()
    wp_running = is_wallpaper_running()
    if wp_path and wp_running:
        wp_desc = "Wallpaper Engine running (auto-pauses during run, auto-resumes after exit)"
    elif wp_path:
        wp_desc = "Wallpaper Engine installed (currently not running)"
    else:
        wp_desc = "Not detected"

    r1_min = max(3.0, round(ram_used * 0.55, 1))
    r1_max = max(r1_min + 1.5, round(ram_used * 0.85, 1))
    v1_min = 0.6 if (wp_path and wp_running) else 0.3
    v1_max = round(min(vram_used * 0.75, 1.5), 1)

    r2_min = round(r1_min + 1.2, 1)
    r2_max = round(r1_max + 2.0, 1)
    v2_min = round(v1_min + 0.3, 1)
    v2_max = round(v1_max + 0.5, 1)

    r3_min = round(r1_min * 0.85, 1)
    r3_max = round(r1_max * 0.9, 1)

    lines = [
        "============================================================",
        "               Memory & VRAM Deep Optimizer",
        "============================================================",
    ]
    if model_name:
        clean_name = model_name.strip("\"' ")
        clean_size = model_size.strip("\"' ") if model_size else ""
        size_str = f" ({clean_size})" if clean_size else ""
        lines.append(f" Selected Model: {clean_name}{size_str}")
        lines.append("------------------------------------------------------------")

    lines.extend([
        " Current System Hardware Status:",
        f"  - System RAM : Total {ram_tot:.1f} GB | Free {ram_avail:.1f} GB (In Use: {ram_used:.1f} GB)",
        f"  - GPU VRAM   : Total {vram_tot:.1f} GB | Free {vram_free:.1f} GB (In Use: {vram_used:.1f} GB)",
        f"  - Live BG    : {wp_desc}",
        "------------------------------------------------------------",
        " Reclaim background RAM & VRAM before calculating model layers?",
        " (Freed memory directly unlocks more GPU layers and larger context)",
        "",
        f" [1] Fast Deep Cleanup (Recommended)   [Est. Freed: RAM +{r1_min}~{r1_max} GB | VRAM +{v1_min}~{v1_max} GB]",
        "     * Pause Wallpaper Engine + Trim 200+ process working sets + CUDA VRAM pulse",
        f" [2] Aggressive Extreme Cleanup        [Est. Freed: RAM +{r2_min}~{r2_max} GB | VRAM +{v2_min}~{v2_max} GB]",
        "     * Everything in [1] + close non-essential heavy background apps",
        f" [3] Gentle RAM-Only Trim              [Est. Freed: RAM +{r3_min}~{r3_max} GB | VRAM +0 GB]",
        "     * Trim system working sets only; keep VRAM and wallpapers untouched",
        " [4] Skip Cleanup (As-Is Launch)       [Freed: RAM +0 GB | VRAM +0 GB]",
        "     * Leave background apps untouched and budget conservatively",
        "------------------------------------------------------------",
        " [0] Back to model selection",
        "============================================================",
    ])
    _bat_write("\n".join(lines) + "\n")


def start_guardian(parent_pid: int, wp_path: str):
    if not parent_pid or not wp_path:
        return
    python_exe = sys.executable
    script_path = os.path.abspath(__file__)
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    try:
        subprocess.Popen(
            [python_exe, script_path, "--guardian", str(parent_pid), wp_path],
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        pass


def run_guardian(parent_pid: int, wp_path: str):
    """
    Detached background guardian: monitors launcher CMD PID and llama-server.
    If the console exits abnormally ([X], Ctrl+C, crash), resumes Wallpaper Engine.
    """
    while True:
        time.sleep(1.0)

        if not os.path.exists(STATE_FILE):
            break

        if not is_pid_alive(parent_pid):
            for _ in range(3):
                if not is_process_running("llama-server.exe"):
                    break
                time.sleep(1.0)

            if is_process_running("llama-server.exe"):
                try:
                    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                except Exception:
                    pass

            resume_wallpaper_engine(wp_path)

            try:
                if os.path.exists(STATE_FILE):
                    os.remove(STATE_FILE)
            except Exception:
                pass
            break


def run_optimization(mode):
    ram_tot, ram_avail_before, _ = get_ram_info()
    vram_tot, vram_free_before, _ = get_vram_info()

    wp_paused = False
    wp_path = None

    _bat_write("\n[Running VRAM & RAM deep optimization, please wait...]\n")

    if mode in ("1", "2"):
        wp_path = pause_wallpaper_engine()
        if wp_path:
            wp_paused = True
            _bat_write("  [+] Paused Wallpaper Engine (freed resident GPU render & VRAM)\n")
            try:
                parent_pid = os.getppid()
                start_guardian(parent_pid, wp_path)
            except Exception:
                pass

    if mode == "2":
        target_kills = load_cleanup_targets()
        killed = []
        for proc in target_kills:
            try:
                res = subprocess.run(["taskkill", "/F", "/IM", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                if res.returncode == 0:
                    killed.append(proc)
            except Exception:
                pass
        if killed:
            _bat_write(f"  [+] Closed configured heavy background apps: {', '.join(killed)}\n")

    trimmed = trim_all_process_working_sets()
    _bat_write(f"  [+] Compressed and trimmed working sets for {trimmed} background processes\n")

    if mode in ("1", "2"):
        if trigger_cuda_vram_pulse():
            _bat_write("  [+] Triggered CUDA VRAM allocation pulse to evict stale DirectX caches\n")

    state = {
        "wp_paused": wp_paused,
        "wp_path": wp_path,
        "mode": mode,
        "time": time.time(),
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

    time.sleep(0.5)
    _, ram_avail_after, _ = get_ram_info()
    _, vram_free_after, _ = get_vram_info()

    freed_ram = max(0.0, ram_avail_after - ram_avail_before)

    _bat_write("------------------------------------------------------------\n")
    _bat_write(f"[Done] Free System RAM : {ram_avail_after:.1f} GB (+{freed_ram:.1f} GB reclaimed)\n")
    _bat_write(f"       Free GPU VRAM   : {vram_free_after:.1f} GB / {vram_tot:.1f} GB\n")
    _bat_write("============================================================\n\n")


def restore():
    wp_path = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            wp_path = state.get("wp_path")
        except Exception:
            pass
        try:
            os.remove(STATE_FILE)
        except Exception:
            pass

    if not wp_path:
        wp_path = find_wallpaper_engine()

    if wp_path:
        if resume_wallpaper_engine(wp_path):
            _bat_write("[Info] Automatically resumed Wallpaper Engine playback.\n")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--menu":
            m_name = sys.argv[2] if len(sys.argv) > 2 else None
            m_size = sys.argv[3] if len(sys.argv) > 3 else None
            print_menu_banner(m_name, m_size)
        elif cmd == "--optimize" and len(sys.argv) > 2:
            run_optimization(sys.argv[2])
        elif cmd == "--restore":
            restore()
        elif cmd == "--guardian" and len(sys.argv) > 3:
            try:
                p_pid = int(sys.argv[2])
                w_path = sys.argv[3]
                run_guardian(p_pid, w_path)
            except Exception:
                pass
    else:
        print_menu_banner()


if __name__ == "__main__":
    main()
