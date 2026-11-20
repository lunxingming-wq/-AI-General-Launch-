# -*- coding: utf-8 -*-
import os
import sys
import json
import struct
import ctypes
import re


def _detect_console_encoding() -> str:
    try:
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        if cp == 65001:
            return "utf-8"
        if cp in (936, 54936):
            return "gbk"
        if cp > 0:
            return f"cp{cp}"
    except Exception:
        pass
    try:
        acp = ctypes.windll.kernel32.GetACP()
        if acp in (936, 54936):
            return "gbk"
        if acp > 0:
            return f"cp{acp}"
    except Exception:
        pass
    return "utf-8"


_CONSOLE_ENC = _detect_console_encoding()


def _bat_write(text: str) -> None:
    """Write text to Windows console matching active console codepage."""
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


TARGET_DIR = os.path.dirname(os.path.abspath(__file__))
if TARGET_DIR not in sys.path:
    sys.path.insert(0, TARGET_DIR)
MODELS_DIR = os.path.join(TARGET_DIR, "models")
CACHE_FILE = os.path.join(TARGET_DIR, ".models_cache.json")
CONFIG_DIRS_FILE = os.path.join(TARGET_DIR, "model_dirs.txt")


def get_system_ram_info():
    """Return physical RAM info (total, used, available) in GB."""
    try:
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
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total_ram = round(stat.ullTotalPhys / (1024**3), 1)
        avail_ram = round(stat.ullAvailPhys / (1024**3), 1)
        used_ram = round(total_ram - avail_ram, 1)
        return total_ram, used_ram, avail_ram
    except Exception:
        return 32.0, 12.0, 20.0


def get_system_ram_gb():
    total_ram, _, _ = get_system_ram_info()
    return total_ram


def get_system_vram_info():
    """Return NVIDIA GPU name, total VRAM, used VRAM, free VRAM (GB)."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
            encoding="utf-8",
            errors="ignore",
        )
        line = out.strip().split("\n")[0]
        parts = [x.strip() for x in line.split(",")]
        gpu_name = parts[0]
        total_gb = round(int(parts[1]) / 1024.0, 1)
        used_gb = round(int(parts[2]) / 1024.0, 1)
        free_gb = round(int(parts[3]) / 1024.0, 1)
        return gpu_name, total_gb, used_gb, free_gb
    except Exception:
        return "GPU / CPU", 12.0, 1.8, 10.2


def get_system_vram_gb():
    _, total_gb, _, _ = get_system_vram_info()
    return total_gb


NON_LLM_ARCHS = {
    "qwen_image21", "flux", "sd1", "sdxl", "sd3", "wan", "hunyuan", "aura",
    "cogvideox", "mochi", "ltx-video", "cosmos",
}


def read_gguf_blocks_and_arch(filepath):
    """Fast-parse GGUF header metadata for block_count and general.architecture."""
    blocks = 40
    arch = "unknown"
    try:
        with open(filepath, "rb") as f:
            magic = f.read(4)
            if magic != b"GGUF":
                return 40, "unknown"
            version = struct.unpack("<I", f.read(4))[0]
            if version >= 2:
                tensor_count = struct.unpack("<Q", f.read(8))[0]
                kv_count = struct.unpack("<Q", f.read(8))[0]
            else:
                tensor_count = struct.unpack("<I", f.read(4))[0]
                kv_count = struct.unpack("<I", f.read(4))[0]

            def read_str():
                if version >= 2:
                    l = struct.unpack("<Q", f.read(8))[0]
                else:
                    l = struct.unpack("<I", f.read(4))[0]
                return f.read(l).decode("utf-8", errors="ignore")

            def read_val(vtype):
                if vtype == 0: return struct.unpack("<B", f.read(1))[0]
                elif vtype == 1: return struct.unpack("<b", f.read(1))[0]
                elif vtype == 2: return struct.unpack("<H", f.read(2))[0]
                elif vtype == 3: return struct.unpack("<h", f.read(2))[0]
                elif vtype == 4: return struct.unpack("<I", f.read(4))[0]
                elif vtype == 5: return struct.unpack("<i", f.read(4))[0]
                elif vtype == 6: return struct.unpack("<f", f.read(4))[0]
                elif vtype == 7: return struct.unpack("<?", f.read(1))[0]
                elif vtype == 8: return read_str()
                elif vtype == 9:
                    if version >= 2:
                        arr_type, arr_len = struct.unpack("<IQ", f.read(12))
                    else:
                        arr_type, arr_len = struct.unpack("<II", f.read(8))
                    if arr_type == 8:
                        for _ in range(arr_len):
                            read_str()
                    else:
                        sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
                        f.seek(arr_len * sizes.get(arr_type, 0), 1)
                    return None
                elif vtype == 10: return struct.unpack("<Q", f.read(8))[0]
                elif vtype == 11: return struct.unpack("<q", f.read(8))[0]
                elif vtype == 12: return struct.unpack("<d", f.read(8))[0]
                return None

            for _ in range(min(kv_count, 500)):
                k = read_str()
                vtype = struct.unpack("<I", f.read(4))[0]
                val = read_val(vtype)
                if k == "general.architecture" and isinstance(val, str):
                    arch = val.lower()
                if k.endswith(".block_count") and isinstance(val, int) and val > 0:
                    blocks = val
                    if arch != "unknown":
                        break
    except Exception:
        pass
    return blocks, arch


def read_gguf_blocks(filepath):
    blocks, _ = read_gguf_blocks_and_arch(filepath)
    return blocks


def get_configured_model_dirs():
    """
    Return all configured model scan directories:
    1. Local `models` folder in the application root
    2. Custom external folders configured in `model_dirs.txt`
    """
    dirs = []
    local_dir = os.path.join(TARGET_DIR, "models")
    if os.path.exists(local_dir):
        dirs.append({"path": os.path.abspath(local_dir), "tag": "[Local]"})

    if os.path.exists(CONFIG_DIRS_FILE):
        try:
            with open(CONFIG_DIRS_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    clean_path = os.path.abspath(line)
                    if os.path.exists(clean_path):
                        drive = os.path.splitdrive(clean_path)[0]
                        tag = f"[Drive {drive.rstrip(':')}]" if drive else f"[{os.path.basename(clean_path)}]"
                        dirs.append({"path": clean_path, "tag": tag})
        except Exception:
            pass

    seen = set()
    unique_dirs = []
    for d in dirs:
        norm = os.path.normcase(os.path.normpath(d["path"]))
        if norm not in seen:
            seen.add(norm)
            unique_dirs.append(d)

    return unique_dirs


def scan_models():
    """Scan all configured directories for GGUF model metadata and defaults."""
    configured_dirs = get_configured_model_dirs()
    if not configured_dirs:
        return []

    total_ram = get_system_ram_gb()
    total_vram = get_system_vram_gb()

    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    cache_dirty = False
    models = []
    seen_paths = set()

    for dir_info in configured_dirs:
        dir_path = dir_info["path"]
        tag = dir_info["tag"]
        try:
            for entry in os.scandir(dir_path):
                if not (entry.is_file() and entry.name.lower().endswith(".gguf") and "mmproj" not in entry.name.lower()):
                    continue
                full_path = os.path.abspath(entry.path)
                norm_full = os.path.normcase(full_path)
                if norm_full in seen_paths:
                    continue
                seen_paths.add(norm_full)

                stat = entry.stat()
                size_gb = round(stat.st_size / (1024**3), 2)
                mtime = stat.st_mtime

                cached = cache.get(full_path) or cache.get(entry.name)
                if cached and cached.get("mtime") == mtime and "blocks" in cached and "arch" in cached:
                    blocks = cached["blocks"]
                    arch = cached.get("arch", "unknown")
                else:
                    blocks, arch = read_gguf_blocks_and_arch(full_path)
                    cache[full_path] = {"mtime": mtime, "blocks": blocks, "size_gb": size_gb, "arch": arch}
                    cache_dirty = True

                is_unsupported = arch in NON_LLM_ARCHS
                is_oversized = size_gb > 10.0

                if blocks > 0:
                    gb_per_layer = max(0.05, size_gb / blocks)
                    if is_oversized:
                        high_ngl = min(blocks - 2, max(4, int((total_vram - 2.0) / gb_per_layer)))
                        low_ngl = min(high_ngl - 2, max(2, int((6.0 - 1.5) / gb_per_layer)))
                    else:
                        high_ngl = blocks
                        low_ngl = min(blocks - 2, max(4, int((8.0 - 1.5) / gb_per_layer)))
                else:
                    high_ngl = 28
                    low_ngl = 12

                avail_kv_gb = max(1.0, total_ram - 2.0 - size_gb)
                gb_per_token = (max(20, blocks) * 8704) / (1024**3)
                raw_tokens = int(avail_kv_gb / gb_per_token)

                if raw_tokens >= 131072: pure_ram_ctx, pure_ram_ctx_label = 131072, "128K"
                elif raw_tokens >= 98304: pure_ram_ctx, pure_ram_ctx_label = 98304, "96K"
                elif raw_tokens >= 65536: pure_ram_ctx, pure_ram_ctx_label = 65536, "64K"
                elif raw_tokens >= 49152: pure_ram_ctx, pure_ram_ctx_label = 49152, "48K"
                elif raw_tokens >= 32768: pure_ram_ctx, pure_ram_ctx_label = 32768, "32K"
                elif raw_tokens >= 16384: pure_ram_ctx, pure_ram_ctx_label = 16384, "16K"
                else: pure_ram_ctx, pure_ram_ctx_label = 8192, "8K"

                display_title = f"{tag} {entry.name}"

                models.append({
                    "filename": entry.name,
                    "display_title": display_title,
                    "source_tag": tag,
                    "path": full_path,
                    "size_gb": size_gb,
                    "arch": arch,
                    "is_unsupported": is_unsupported,
                    "is_oversized": 1 if is_oversized else 0,
                    "block_count": blocks,
                    "high_ngl": high_ngl,
                    "low_ngl": low_ngl,
                    "remain_high": max(0, blocks - high_ngl),
                    "remain_low": max(0, blocks - low_ngl),
                    "pure_ram_ctx": pure_ram_ctx,
                    "pure_ram_ctx_label": pure_ram_ctx_label,
                    "remain_ram": 2.0,
                })
        except Exception:
            continue

    if cache_dirty:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass

    models.sort(key=lambda x: (0 if x["source_tag"] == "[Local]" else 1, x["filename"].lower()))
    return models


def list_models_for_bat():
    models = scan_models()
    for idx, m in enumerate(models, 1):
        size_display = f"{m['size_gb']:.2f} GB"
        if m.get("is_unsupported"):
            size_display += f" [ImageGen:{m['arch']}, unsupported by llama.cpp]"
        # Pipe "|" delimiter prevents Windows drive colons (C:, D:, I:) from splitting fields
        line = (
            f"{idx}|{m['path']}|{m['display_title']}|{size_display}|{m['is_oversized']}|"
            f"{m['high_ngl']}|{m['low_ngl']}|{m['block_count']}|{m['remain_high']}|"
            f"{m['remain_low']}|{m['pure_ram_ctx']}|{m['pure_ram_ctx_label']}|{m['remain_ram']:.1f}\n"
        )
        _bat_write(line)


def calc_strategy(filepath, choice, is_oversized, target_vram=None, opt_choice="1"):
    total_ram, used_ram, avail_ram = get_system_ram_info()
    gpu_name, total_vram, used_vram, free_vram = get_system_vram_info()

    try:
        stat = os.stat(filepath)
        size_gb = round(stat.st_size / (1024**3), 2)
    except Exception as e:
        print(f"[WARNING] calc_strategy: cannot read model size ({filepath}): {e}", file=sys.stderr)
        size_gb = 5.0

    blocks = read_gguf_blocks(filepath)
    if blocks <= 0:
        blocks = 40
    gb_per_layer = max(0.05, size_gb / blocks)

    opt = str(opt_choice).strip() if opt_choice else "1"

    # Dynamically budget VRAM & RAM based on the selected optimization tier
    if opt == "1":
        gpu_total_budget = round(min(total_vram - 0.8, max(3.5, free_vram + 0.6)), 1)
        avail_ram_budget = round(min(total_ram - 2.5, max(4.0, avail_ram)), 1)
        opt_label = "Fast Cleanup"
    elif opt == "2":
        gpu_total_budget = round(min(total_vram - 0.6, max(3.5, free_vram + 1.0)), 1)
        avail_ram_budget = round(min(total_ram - 2.0, max(4.0, avail_ram + 1.5)), 1)
        opt_label = "Extreme Cleanup"
    elif opt == "3":
        gpu_total_budget = round(max(3.5, total_vram - 1.6), 1)
        avail_ram_budget = round(min(total_ram - 3.0, max(4.0, avail_ram)), 1)
        opt_label = "RAM Trim Only"
    else:  # opt == "4"
        gpu_total_budget = round(max(3.5, total_vram - max(1.8, used_vram)), 1)
        avail_ram_budget = round(max(3.0, avail_ram - 3.0), 1)
        opt_label = "As-Is (Unoptimized)"

    if str(choice) == "1":  # Full VRAM / Max GPU Acceleration
        if str(is_oversized) != "1" and size_gb <= gpu_total_budget - 1.2:
            ngl = 99
            model_vram_est = size_gb
            remain_layers = 0
            applied_vram = round(min(total_vram, size_gb + 1.5), 1)
            avail_kv_gb = max(0.8, gpu_total_budget - model_vram_est)
            gb_per_token = (max(20, blocks) * 8704) / (1024**3)
            raw_tokens = int(avail_kv_gb / gb_per_token)
            if raw_tokens >= 131072: ctx = 131072
            elif raw_tokens >= 65536: ctx = 65536
            elif raw_tokens >= 49152: ctx = 49152
            elif raw_tokens >= 32768: ctx = 32768
            elif raw_tokens >= 24576: ctx = 24576
            elif raw_tokens >= 16384: ctx = 16384
            elif raw_tokens >= 12288: ctx = 12288
            else: ctx = max(8192, (raw_tokens // 2048) * 2048)
            flags = "-ctk q8_0 -ctv q8_0"
            mode = f"Full VRAM Turbo (All GPU - {ctx} ctx - {opt_label})"
        else:
            weights_budget = round(max(2.0, gpu_total_budget - 1.8), 1)
            ngl = min(blocks - 2, max(4, int(weights_budget / gb_per_layer)))
            model_vram_est = round(ngl * gb_per_layer, 1)
            remain_layers = blocks - ngl
            applied_vram = total_vram
            avail_kv_gb = max(0.8, gpu_total_budget - model_vram_est)
            gb_per_token = (max(20, blocks) * 8704) / (1024**3)
            raw_tokens = int(avail_kv_gb / gb_per_token)
            if raw_tokens >= 16384: ctx = 16384
            elif raw_tokens >= 12288: ctx = 12288
            else: ctx = 8192
            flags = "-ctk q8_0 -ctv q8_0"
            mode = f"Max GPU Offload ({ctx} ctx - {ngl}/{blocks} layers GPU - {opt_label})"

    elif str(choice) == "2":  # VRAM Weights + System RAM KV Context
        weights_budget = round(max(3.0, gpu_total_budget - 0.3), 2)
        if size_gb <= weights_budget:
            ngl = 99
            model_vram_est = size_gb
            remain_layers = 0
            applied_vram = round(min(total_vram, size_gb + 0.3), 1)
            model_ram = 0.0
        else:
            ngl = min(blocks - 1, max(4, int(weights_budget / gb_per_layer)))
            model_vram_est = round(ngl * gb_per_layer, 1)
            remain_layers = blocks - ngl
            applied_vram = round(min(total_vram, model_vram_est + 0.3), 1)
            model_ram = max(0.0, size_gb - model_vram_est)

        avail_kv_ram = max(1.0, avail_ram_budget - model_ram)
        gb_per_token = (max(20, blocks) * 8704) / (1024**3)
        raw_tokens = int(avail_kv_ram / gb_per_token)
        if raw_tokens >= 131072: ctx = 131072
        elif raw_tokens >= 98304: ctx = 98304
        elif raw_tokens >= 65536: ctx = 65536
        elif raw_tokens >= 49152: ctx = 49152
        elif raw_tokens >= 32768: ctx = 32768
        elif raw_tokens >= 24576: ctx = 24576
        elif raw_tokens >= 16384: ctx = 16384
        else: ctx = max(8192, (raw_tokens // 4096) * 4096)
        flags = "-nkvo -ctk q8_0 -ctv q8_0"

        if ngl == 99 or ngl >= blocks:
            mode = f"VRAM Model + RAM Context ({ctx} ctx - All GPU - KV in RAM - {opt_label})"
        else:
            mode = f"VRAM Model + RAM Context ({ctx} ctx - {ngl}/{blocks} GPU - KV in RAM - {opt_label})"

    elif str(choice) == "3":  # Balanced Coexistence
        reserved_free = 4.0 if opt in ("1", "2") else 5.0
        applied_vram = round(max(4.0, total_vram - reserved_free), 1)
        target_weights_vram = max(1.0, applied_vram - 1.2)
        ngl = min(blocks, max(4, int(target_weights_vram / gb_per_layer)))
        if str(is_oversized) != "1" and ngl >= blocks:
            ngl = 99
            model_vram_est = size_gb
            remain_layers = 0
            model_ram = 0.0
        else:
            model_vram_est = round(min(size_gb, ngl * gb_per_layer), 1)
            remain_layers = max(0, blocks - ngl)
            model_ram = max(0.0, size_gb - model_vram_est)

        avail_kv_ram = max(1.0, avail_ram_budget - model_ram)
        gb_per_token = (max(20, blocks) * 4608) / (1024**3)
        raw_tokens = int(avail_kv_ram / gb_per_token)
        if raw_tokens >= 65536: ctx = 65536
        elif raw_tokens >= 49152: ctx = 49152
        elif raw_tokens >= 32768: ctx = 32768
        elif raw_tokens >= 24576: ctx = 24576
        elif raw_tokens >= 16384: ctx = 16384
        elif raw_tokens >= 12288: ctx = 12288
        else: ctx = max(8192, (raw_tokens // 2048) * 2048)
        flags = "-nkvo -ctk q4_0 -ctv q4_0"
        if str(is_oversized) != "1":
            mode = f"Balanced Mode ({ctx} ctx - {reserved_free}G VRAM Reserved - {opt_label})"
        else:
            mode = f"Balanced Hybrid ({ctx} ctx - {ngl}/{blocks} GPU - {reserved_free}G Reserved - {opt_label})"

    elif str(choice) == "4":  # Custom VRAM Budget
        target_str = str(target_vram).strip().lower() if target_vram else "4.0"
        num_match = re.search(r"(\d+(?:\.\d+)?)", target_str)
        if num_match:
            try:
                target = float(num_match.group(1))
            except Exception:
                target = 4.0
        else:
            target = 4.0

        if target <= 0.0:
            target = 4.0

        max_safe_budget = round(max(2.0, gpu_total_budget - 0.2), 1)
        applied_vram = round(min(target, max_safe_budget), 1)

        target_weights = max(0.5, applied_vram - 0.3)
        if size_gb <= target_weights:
            ngl = 99
            model_vram_est = size_gb
            remain_layers = 0
            applied_vram = round(min(total_vram, size_gb + 0.3), 1)
            model_ram = 0.0
        else:
            ngl = min(blocks - 1, max(1, int(target_weights / gb_per_layer)))
            model_vram_est = round(ngl * gb_per_layer, 1)
            remain_layers = blocks - ngl
            applied_vram = round(min(total_vram, model_vram_est + 0.3), 1)
            model_ram = max(0.0, size_gb - model_vram_est)

        avail_kv_ram = max(1.0, avail_ram_budget - model_ram)
        gb_per_token = (max(20, blocks) * 8704) / (1024**3)
        raw_tokens = int(avail_kv_ram / gb_per_token)
        if raw_tokens >= 131072: ctx = 131072
        elif raw_tokens >= 98304: ctx = 98304
        elif raw_tokens >= 65536: ctx = 65536
        elif raw_tokens >= 49152: ctx = 49152
        elif raw_tokens >= 32768: ctx = 32768
        elif raw_tokens >= 24576: ctx = 24576
        elif raw_tokens >= 16384: ctx = 16384
        else: ctx = max(8192, (raw_tokens // 4096) * 4096)
        flags = "-nkvo -ctk q8_0 -ctv q8_0"

        free_gpu = round(max(0.0, total_vram - applied_vram), 1)
        if ngl == 99 or ngl >= blocks:
            mode = f"Custom VRAM ({applied_vram}G Limit - All GPU - {ctx} ctx - {free_gpu}G Free - {opt_label})"
        else:
            mode = f"Custom VRAM ({applied_vram}G Limit - {ngl}/{blocks} GPU - {ctx} ctx - {free_gpu}G Free - {opt_label})"

    elif str(choice) == "5":  # CPU / RAM Only
        ngl = 0
        applied_vram = 0.0
        model_vram_est = 0.0
        remain_layers = blocks
        avail_kv_gb = max(1.0, avail_ram_budget - size_gb)
        gb_per_token = (max(20, blocks) * 8704) / (1024**3)
        raw_tokens = int(avail_kv_gb / gb_per_token)
        if raw_tokens >= 131072: ctx = 131072
        elif raw_tokens >= 98304: ctx = 98304
        elif raw_tokens >= 65536: ctx = 65536
        elif raw_tokens >= 49152: ctx = 49152
        elif raw_tokens >= 32768: ctx = 32768
        elif raw_tokens >= 16384: ctx = 16384
        else: ctx = max(8192, (raw_tokens // 4096) * 4096)
        flags = "-ctk q8_0 -ctv q8_0"
        mode = f"CPU + RAM Only ({ctx} ctx - 0 VRAM - {opt_label})"

    else:
        ngl = 99
        ctx = 16384
        mode = f"Default Full VRAM ({opt_label})"
        flags = "-ctk q8_0 -ctv q8_0"
        remain_layers = 0
        model_vram_est = size_gb
        applied_vram = total_vram

    if ctx < 4096:
        ctx = 4096

    res = f"{ngl}:{ctx}:{mode}:{flags}:{remain_layers}:{model_vram_est:.1f}:{applied_vram:.1f}:{blocks}\n"
    _bat_write(res)


def print_resource_banner(
    filepath,
    ngl_str="99",
    ctx_str="16384",
    extra_flags="",
    mode_str="",
    role_name="Default",
    n_predict_str="3000",
    total_blocks_str="40",
):
    """Print detailed hardware/memory allocation summary and access endpoints."""
    try:
        size_bytes = os.path.getsize(filepath)
        size_gb = round(size_bytes / (1024**3), 2)
    except Exception:
        size_gb = 8.0

    filename = os.path.basename(filepath)

    try:
        total_blocks = int(total_blocks_str)
        if total_blocks <= 0:
            total_blocks = 40
    except Exception:
        total_blocks = read_gguf_blocks(filepath)

    try:
        ngl = int(ngl_str)
    except Exception:
        ngl = 99

    try:
        ctx = int(ctx_str)
    except Exception:
        ctx = 16384

    gpu_name, gpu_total, gpu_used, gpu_free = get_system_vram_info()
    ram_total, ram_used, ram_avail = get_system_ram_info()

    if ngl >= total_blocks or ngl == 99:
        gpu_layers = total_blocks
        cpu_layers = 0
        gpu_weights = size_gb
        cpu_weights = 0.0
    elif ngl <= 0:
        gpu_layers = 0
        cpu_layers = total_blocks
        gpu_weights = 0.0
        cpu_weights = size_gb
    else:
        gpu_layers = min(ngl, total_blocks)
        cpu_layers = max(0, total_blocks - gpu_layers)
        frac = gpu_layers / float(total_blocks)
        gpu_weights = round(size_gb * frac, 2)
        cpu_weights = round(size_gb * (1.0 - frac), 2)

    nkvo = "-nkvo" in extra_flags
    bytes_per_tok = max(20, total_blocks) * (4608 if "q4_0" in extra_flags else 8704)
    kv_gb = round((ctx * bytes_per_tok) / (1024**3), 2)

    cuda_scratch = 0.3 if gpu_layers > 0 else 0.0
    model_vram_total = round(gpu_weights + (0.0 if nkvo else kv_gb) + cuda_scratch, 1)
    model_ram_total = round(cpu_weights + (kv_gb if nkvo else 0.0) + 0.3, 1)

    vram_pct = min(100, int((model_vram_total / max(1.0, gpu_total)) * 100))
    ram_pct = min(100, int((model_ram_total / max(1.0, ram_total)) * 100))

    offload_pct = int((gpu_layers / max(1, total_blocks)) * 100)

    try:
        import network_helper
        lan_ip, tailscale_ip = network_helper.get_network_ips()
    except Exception:
        lan_ip, tailscale_ip = "127.0.0.1", None

    kv_vram_desc = "0.00 GB (Offloaded to System RAM via -nkvo)" if nkvo else f"{kv_gb:.2f} GB (Resident in VRAM)"
    kv_ram_desc = f"{kv_gb:.2f} GB (Resident in System RAM)" if nkvo else "0.00 GB (Resident in GPU VRAM)"

    lines = [
        "",
        "======================================================================",
        "               Model & Hardware Resource Allocation",
        "======================================================================",
        "[Launch Configuration]",
        f" * Model        : {filename} ({size_gb:.2f} GB)",
        f" * Strategy     : {mode_str}",
        f" * Active Role  : {role_name}",
        f" * Context Size : {ctx} Tokens  |  Max Output: {n_predict_str} Tokens",
        "",
        "[Estimated VRAM / RAM Footprint]",
        f" * Est. Model VRAM : ~{model_vram_total:.1f} GB / {gpu_total:.1f} GB ({vram_pct}%)",
        f"   - Weights       : ~{gpu_weights:.2f} GB ({gpu_layers}/{total_blocks} layers on GPU, {offload_pct}%)",
        f"   - KV Context    : ~{kv_vram_desc}",
        f"   - Compute Buf   : ~{cuda_scratch:.1f} GB",
        f" * Est. Model RAM  : ~{model_ram_total:.1f} GB / {ram_total:.1f} GB ({ram_pct}%)",
        f"   - CPU Layers    : ~{cpu_weights:.2f} GB ({cpu_layers} layers on CPU)",
        f"   - KV Context    : {kv_ram_desc}",
        " * Live Hardware Status:",
        f"   - GPU           : {gpu_name} [Total {gpu_total:.1f} GB | Used {gpu_used:.1f} GB | Free {gpu_free:.1f} GB]",
        f"   - System RAM    : [Total {ram_total:.1f} GB | Used {ram_used:.1f} GB | Free {ram_avail:.1f} GB]",
        "----------------------------------------------------------------------",
        "[Service Endpoints (Web UI & OpenAI API)]",
        " * Local PC Web UI       : http://127.0.0.1:8080",
        f" * LAN (Phone / Tablet)  : http://{lan_ip}:8080",
    ]
    if tailscale_ip:
        lines.append(f" * Tailscale Remote      : http://{tailscale_ip}:8080")
    lines.append(" * OpenAI-Compatible API : http://127.0.0.1:8080/v1")
    lines.append("======================================================================")
    lines.append("")

    _bat_write("\n".join(lines) + "\n")


def check_template_compat(filepath):
    """Detect whether model architecture uses the Qwen ChatML Jinja template."""
    arch = "unknown"
    full_path = os.path.abspath(filepath)
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            cached = cache.get(full_path) or cache.get(os.path.basename(full_path))
            if cached and cached.get("arch"):
                arch = str(cached["arch"])
    except Exception:
        pass
    if arch == "unknown":
        try:
            _, arch = read_gguf_blocks_and_arch(full_path)
        except Exception:
            arch = "unknown"
    if str(arch).lower().startswith("qwen"):
        _bat_write("USE_CUSTOM\n")
    else:
        _bat_write("USE_NATIVE\n")


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        list_models_for_bat()
    elif sys.argv[1] == "--info" and len(sys.argv) >= 3:
        print(read_gguf_blocks(sys.argv[2]))
    elif sys.argv[1] == "--check-template-compat" and len(sys.argv) >= 3:
        check_template_compat(sys.argv[2])
    elif sys.argv[1] == "--calc-strategy" and len(sys.argv) >= 5:
        target = sys.argv[5] if len(sys.argv) >= 6 else None
        opt = sys.argv[6] if len(sys.argv) >= 7 else "1"
        calc_strategy(sys.argv[2], sys.argv[3], sys.argv[4], target, opt)
    elif sys.argv[1] == "--print-resource-banner" and len(sys.argv) >= 3:
        filepath = sys.argv[2]
        ngl = sys.argv[3] if len(sys.argv) > 3 else "99"
        ctx = sys.argv[4] if len(sys.argv) > 4 else "16384"
        flags = sys.argv[5] if len(sys.argv) > 5 else ""
        mode = sys.argv[6] if len(sys.argv) > 6 else ""
        role = sys.argv[7] if len(sys.argv) > 7 else "Default"
        n_pred = sys.argv[8] if len(sys.argv) > 8 else "3000"
        blocks = sys.argv[9] if len(sys.argv) > 9 else "40"
        print_resource_banner(filepath, ngl, ctx, flags, mode, role, n_pred, blocks)


if __name__ == "__main__":
    main()
