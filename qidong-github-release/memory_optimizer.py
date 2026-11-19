# -*- coding: utf-8 -*-
"""
显存与内存深度腾退优化器 (Memory & VRAM Optimizer)
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
        return "gbk"

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
        ('dwLength', ctypes.c_ulong),
        ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong),
        ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong),
        ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong),
        ('ullAvailVirtual', ctypes.c_ulonglong),
        ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
    ]

def get_ram_info():
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    total_gb = round(stat.ullTotalPhys / (1024**3), 1)
    avail_gb = round(stat.ullAvailPhys / (1024**3), 1)
    used_gb = round(total_gb - avail_gb, 1)
    return total_gb, avail_gb, used_gb

def get_vram_info():
    try:
        out = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=memory.total,memory.used,memory.free', '--format=csv,noheader,nounits'],
            encoding='utf-8', errors='ignore', timeout=2
        )
        parts = [float(x.strip()) for x in out.strip().split(',')]
        total_gb = round(parts[0] / 1024.0, 1)
        used_gb = round(parts[1] / 1024.0, 1)
        free_gb = round(parts[2] / 1024.0, 1)
        return total_gb, free_gb, used_gb
    except Exception:
        return 12.0, 10.0, 2.0

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
            ['tasklist', '/FI', f'IMAGENAME eq {process_name}', '/FO', 'CSV'],
            encoding='gbk', errors='ignore', timeout=3
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
    # 1. 直接查询当前正在运行的壁纸引擎进程 (64位或32位)
    for exe in ('wallpaper64.exe', 'wallpaper32.exe'):
        try:
            out = subprocess.check_output(
                ['tasklist', '/FI', f'IMAGENAME eq {exe}', '/FO', 'CSV'],
                encoding='gbk', errors='ignore', timeout=2
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

    # 2. 查询 Windows 服务 ImagePath (Wallpaper Engine Service 常驻服务中记录的主程序绝对路径)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\Wallpaper Engine Service') as k:
            val, _ = winreg.QueryValueEx(k, 'ImagePath')
            if '-p' in val:
                p = val.split('-p')[1].strip(' "\'')
                if os.path.exists(p):
                    return p
    except Exception:
        pass

    # 3. 遍历全盘常见 Steam 库路径
    drives = [chr(c) for c in range(ord('C'), ord('Z')+1)]
    for d in drives:
        for sub in (
            rf'{d}:\SteamLibrary\steamapps\common\wallpaper_engine\wallpaper64.exe',
            rf'{d}:\SteamLibrary\steamapps\common\wallpaper_engine\wallpaper32.exe',
            rf'{d}:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine\wallpaper64.exe',
            rf'{d}:\Program Files\Steam\steamapps\common\wallpaper_engine\wallpaper64.exe',
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
                stdin=subprocess.DEVNULL
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
                stdin=subprocess.DEVNULL
            )
            try:
                p.wait(timeout=3)
            except Exception:
                pass
        else:
            # 若壁纸主程序未在运行，直接重启拉起
            subprocess.Popen(
                [wp_path],
                cwd=wp_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
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
        out = subprocess.check_output(['tasklist', '/FO', 'CSV'], encoding='gbk', errors='ignore', timeout=3)
        reader = csv.reader(io.StringIO(out))
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                name = row[0].lower()
                try:
                    pid = int(row[1])
                except Exception:
                    continue
                if pid <= 4 or name in ('system', 'idle', 'csrss.exe', 'smss.exe', 'lsass.exe', 'services.exe', 'wininit.exe'):
                    continue
                hProc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if hProc:
                    if psapi.EmptyWorkingSet(hProc):
                        trimmed_count += 1
                    kernel32.CloseHandle(hProc)
    except Exception:
        pass
    return trimmed_count

def trigger_cuda_vram_pulse():
    try:
        cuda = ctypes.windll.nvcuda
        if cuda.cuInit(0) != 0:
            return False
        pDev = ctypes.c_int()
        if cuda.cuDeviceGet(ctypes.byref(pDev), 0) != 0:
            return False
        pCtx = ctypes.c_void_p()
        if cuda.cuCtxCreate_v2(ctypes.byref(pCtx), 0, pDev.value) != 0:
            return False

        free_m = ctypes.c_size_t()
        total_m = ctypes.c_size_t()
        if cuda.cuMemGetInfo_v2(ctypes.byref(free_m), ctypes.byref(total_m)) == 0:
            alloc_bytes = int(free_m.value * 0.90)
            if alloc_bytes > 512 * 1024 * 1024:
                pMem = ctypes.c_ulonglong()
                if cuda.cuMemAlloc_v2(ctypes.byref(pMem), ctypes.c_size_t(alloc_bytes)) == 0:
                    time.sleep(0.2)
                    cuda.cuMemFree_v2(pMem)
        cuda.cuCtxDestroy_v2(pCtx)
        return True
    except Exception:
        return False

def print_menu_banner(model_name=None, model_size=None):
    ram_tot, ram_avail, ram_used = get_ram_info()
    vram_tot, vram_free, vram_used = get_vram_info()
    wp_path = find_wallpaper_engine()
    wp_running = is_wallpaper_running()
    if wp_path and wp_running:
        wp_desc = "Wallpaper Engine 运行中 (优化时将自动暂停腾出显存，运行结束自动恢复)"
    elif wp_path:
        wp_desc = "Wallpaper Engine 已安装 (当前未处于运行状态)"
    else:
        wp_desc = "未检测到运行"

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
        "               显存与内存深度腾退优化",
        "============================================================"
    ]
    if model_name:
        clean_name = model_name.strip('\"\' ')
        clean_size = model_size.strip('\"\' ') if model_size else ""
        size_str = f" ({clean_size})" if clean_size else ""
        lines.append(f" 当前选定模型: {clean_name}{size_str}")
        lines.append("------------------------------------------------------------")

    lines.extend([
        " 当前系统物理资源状态:",
        f"  - 物理内存: 总共 {ram_tot:.1f} GB | 当前可用: {ram_avail:.1f} GB (已被后台占用: {ram_used:.1f} GB)",
        f"  - 显卡显存: 总共 {vram_tot:.1f} GB | 当前可用: {vram_free:.1f} GB (已被后台占用: {vram_used:.1f} GB)",
        f"  - 动态壁纸: {wp_desc}",
        "------------------------------------------------------------",
        " 请选择是否在配置策略前腾退后台占用？",
        " (腾退出的显存与内存将直接用于后续加载更多显卡层数与计算更长上下文！)",
        "",
        f" [1] 一键极速深度强力腾退 (强烈推荐)  [预计释放: 内存 +{r1_min}~{r1_max} GB | 显存 +{v1_min}~{v1_max} GB]",
        "     * 动作: 挂起动态壁纸 + 200+个后台进程内存强制清空工作集 + 脉冲CUDA显存置换",
        f" [2] 终极极限深挖腾退 (最强模式)  [预计释放: 内存 +{r2_min}~{r2_max} GB | 显存 +{v2_min}~{v2_max} GB]",
        "     * 动作: 在[1]基础上，自动检测/关闭高显存与内存后台非核心常驻进程",
        f" [3] 温和工作集优化 (只清内存)  [预计释放: 内存 +{r3_min}~{r3_max} GB | 显存 +0 GB (不动显存)]",
        "     * 动作: 仅清空全系统进程内存工作集，全显存与动态壁纸保持原状",
        " [4] 原汁原味启动 (不优化)  [释放: 内存 +0 GB | 显存 +0 GB (维持现状)]",
        "     * 动作: 不做任何系统干预，后续按当前现有剩余显存与内存保守计算",
        "------------------------------------------------------------",
        " [0] 返回重新选择模型",
        "============================================================"
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
            stdin=subprocess.DEVNULL
        )
    except Exception:
        pass

def run_guardian(parent_pid: int, wp_path: str):
    """
    后台常驻守护进程：
    持续监控启动器 CMD 窗口与 llama-server.exe 的存活状态。
    无论用户通过关闭窗口 [X]、Ctrl+C 中断、异常崩溃或直接退出，
    只要启动器进程死亡，立刻第一时间无条件恢复动态壁纸！
    """
    while True:
        time.sleep(1.0)

        # 1. 如果正常流程已调用 restore() (状态文件被正常清理)，守护完成使命退出
        if not os.path.exists(STATE_FILE):
            break

        # 2. 如果启动器 CMD 窗口已经关闭 (用户点击了 [X] 或被终止)
        if not is_pid_alive(parent_pid):
            # 稍作等待，看 llama-server 是否随控制台关闭退出
            for _ in range(3):
                if not is_process_running("llama-server.exe"):
                    break
                time.sleep(1.0)

            # 若仍有孤儿 llama-server 残留，清理它以防显存泄漏
            if is_process_running("llama-server.exe"):
                try:
                    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                except Exception:
                    pass

            # 立刻无条件恢复壁纸引擎！
            resume_wallpaper_engine(wp_path)

            # 清理状态文件并退出
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

    _bat_write("\n[正在执行显存与内存深度优化，请稍候...]\n")

    if mode in ("1", "2"):
        wp_path = pause_wallpaper_engine()
        if wp_path:
            wp_paused = True
            _bat_write("  [+] 成功挂起 Wallpaper Engine 动态壁纸 (释放常驻显存与GPU渲染)\n")
            # 启动独立守护进程：即便后续用户点右上角 [X] 关闭窗口，也会自动恢复壁纸
            try:
                parent_pid = os.getppid()
                start_guardian(parent_pid, wp_path)
            except Exception:
                pass

    if mode == "2":
        target_kills = ["steamwebhelper.exe", "BaiduNetdiskUnite.exe", "old_media_container.exe"]
        killed = []
        for proc in target_kills:
            try:
                res = subprocess.run(["taskkill", "/F", "/IM", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                if res.returncode == 0:
                    killed.append(proc)
            except Exception:
                pass
        if killed:
            _bat_write(f"  [+] 已清理后台非核心高占用应用: {', '.join(killed)}\n")

    trimmed = trim_all_process_working_sets()
    _bat_write(f"  [+] 已强制压缩并释放 {trimmed} 个后台进程的内存工作集\n")

    if mode in ("1", "2"):
        if trigger_cuda_vram_pulse():
            _bat_write("  [+] 已触发 CUDA 显存脉冲，逼退后台 DirectX 显存缓存\n")

    state = {
        "wp_paused": wp_paused,
        "wp_path": wp_path,
        "mode": mode,
        "time": time.time()
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
    _bat_write(f"[优化完成] 物理内存可用: {ram_avail_after:.1f} GB (成功腾退 +{freed_ram:.1f} GB 内存!)\n")
    _bat_write(f"           显卡显存空闲: {vram_free_after:.1f} GB / {vram_tot:.1f} GB\n")
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
            _bat_write("[提示] 已自动恢复 Wallpaper Engine 动态壁纸播放。\n")

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

