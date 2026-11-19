# -*- coding: utf-8 -*-
import os
import sys
import json
import struct
import ctypes

def _detect_console_encoding() -> str:
    try:
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        if cp == 65001:
            return 'utf-8'
        if cp in (936, 54936):
            return 'gbk'
        if cp > 0:
            return f'cp{cp}'
    except Exception:
        pass
    try:
        acp = ctypes.windll.kernel32.GetACP()
        if acp in (936, 54936):
            return 'gbk'
        if acp > 0:
            return f'cp{acp}'
    except Exception:
        pass
    return 'gbk'

_CONSOLE_ENC = _detect_console_encoding()

def _bat_write(text: str) -> None:
    """向 bat 控制台输出文本，自动匹配控制台代码页"""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_stdout = kernel32.GetStdHandle(-11)
        written = ctypes.c_ulong(0)
        if kernel32.WriteConsoleW(h_stdout, text, len(text), ctypes.byref(written), None):
            return
    except Exception:
        pass
    try:
        sys.stdout.buffer.write(text.encode(_CONSOLE_ENC, errors='replace'))
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
    """获取系统物理内存信息 (总内存, 已用内存, 可用内存) 单位 GB"""
    try:
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
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
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
    """获取系统总物理内存大小 (GB)"""
    total_ram, _, _ = get_system_ram_info()
    return total_ram

def get_system_vram_info():
    """获取 NVIDIA 显卡名称、总显存、已用显存、剩余显存 (GB)"""
    import subprocess
    try:
        out = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=name,memory.total,memory.used,memory.free', '--format=csv,noheader,nounits'],
            encoding='utf-8', errors='ignore'
        )
        line = out.strip().split('\n')[0]
        parts = [x.strip() for x in line.split(',')]
        gpu_name = parts[0]
        total_gb = round(int(parts[1]) / 1024.0, 1)
        used_gb = round(int(parts[2]) / 1024.0, 1)
        free_gb = round(int(parts[3]) / 1024.0, 1)
        return gpu_name, total_gb, used_gb, free_gb
    except Exception:
        return "NVIDIA GeForce GPU", 12.0, 1.8, 10.2

def get_system_vram_gb():
    _, total_gb, _, _ = get_system_vram_info()
    return total_gb

NON_LLM_ARCHS = {
    "qwen_image21", "flux", "sd1", "sdxl", "sd3", "wan", "hunyuan", "aura",
    "cogvideox", "mochi", "ltx-video", "cosmos"
}

def read_gguf_blocks_and_arch(filepath):
    """初次扫描模型时快速读取一次 GGUF 头的层数信息 (block_count) 及模型架构 (general.architecture)"""
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
                        atype, alen = struct.unpack("<IQ", f.read(12))
                    else:
                        atype, alen = struct.unpack("<II", f.read(8))
                    return [read_val(atype) for _ in range(alen)]
                elif vtype == 10: return struct.unpack("<Q", f.read(8))[0]
                elif vtype == 11: return struct.unpack("<q", f.read(8))[0]
                elif vtype == 12: return struct.unpack("<d", f.read(8))[0]
                return None

            for _ in range(min(kv_count, 120)):
                k = read_str()
                vtype = struct.unpack("<I", f.read(4))[0]
                val = read_val(vtype)
                if k == "general.architecture":
                    arch = str(val).lower()
                elif k.endswith(".block_count"):
                    blocks = int(val)
                if arch != "unknown" and blocks != 40:
                    break
    except Exception:
        pass
    return blocks, arch

def read_gguf_blocks(filepath):
    blocks, _ = read_gguf_blocks_and_arch(filepath)
    return blocks

def get_configured_model_dirs():
    r"""
    获取所有配置的模型扫描目录列表：
    1. 本地 models 目录 (程序根目录下的 models 文件夹)
    2. model_dirs.txt 中的自定义扩展路径列表 (支持用户随意添加其他磁盘/目录)
    """
    dirs = []
    # 1. 本地 models 目录
    local_dir = os.path.join(TARGET_DIR, "models")
    if os.path.exists(local_dir):
        dirs.append({"path": os.path.abspath(local_dir), "tag": "[本地]"})

    # 3. 读取 model_dirs.txt
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
                        tag = f"[{drive.rstrip(':')}盘]" if drive else f"[{os.path.basename(clean_path)}]"
                        dirs.append({"path": clean_path, "tag": tag})
        except Exception:
            pass

    # 路径去重 (规范化比较)
    seen = set()
    unique_dirs = []
    for d in dirs:
        norm = os.path.normcase(os.path.normpath(d["path"]))
        if norm not in seen:
            seen.add(norm)
            unique_dirs.append(d)

    return unique_dirs

def scan_models():
    """扫描所有配置目录下的 GGUF 模型元数据与推荐策略"""
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

                is_unsupported = (arch in NON_LLM_ARCHS)
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
                    "remain_ram": 2.0
                })
        except Exception:
            continue

    if cache_dirty:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass

    # 排序：本地模型排前，其它按自然顺序排序
    models.sort(key=lambda x: (0 if x["source_tag"] == "[本地]" else 1, x["filename"].lower()))
    return models

def list_models_for_bat():
    models = scan_models()
    for idx, m in enumerate(models, 1):
        size_display = f"{m['size_gb']:.2f} GB"
        if m.get("is_unsupported"):
            size_display += f" [生图模型:{m['arch']},llama不支持]"
        # 使用管道符 | 作为字段分隔符，规避路径中的驱动器冒号 C: / I: 干扰批处理分词
        line = f"{idx}|{m['path']}|{m['display_title']}|{size_display}|{m['is_oversized']}|{m['high_ngl']}|{m['low_ngl']}|{m['block_count']}|{m['remain_high']}|{m['remain_low']}|{m['pure_ram_ctx']}|{m['pure_ram_ctx_label']}|{m['remain_ram']:.1f}\n"
        _bat_write(line)

def calc_strategy(filepath, choice, is_oversized, target_vram=None, opt_choice="1"):
    total_ram, used_ram, avail_ram = get_system_ram_info()
    gpu_name, total_vram, used_vram, free_vram = get_system_vram_info()

    try:
        stat = os.stat(filepath)
        size_gb = round(stat.st_size / (1024**3), 2)
    except Exception as e:
        import sys as _sys
        print(f"[WARNING] calc_strategy: 无法读取模型大小 ({filepath}): {e}", file=_sys.stderr)
        size_gb = 5.0

    blocks = read_gguf_blocks(filepath)
    if blocks <= 0: blocks = 40
    gb_per_layer = max(0.05, size_gb / blocks)

    opt = str(opt_choice).strip() if opt_choice else "1"

    # 根据显存/内存深度腾退优化模式，动态测算可用资源池与上下文上限
    if opt == "1":
        # 极速强力腾退: 壁纸挂起、DirectX缓存置换后，DWM与桌面仅需约 0.8GB
        gpu_total_budget = round(min(total_vram - 0.8, max(3.5, free_vram + 0.6)), 1)
        avail_ram_budget = round(min(total_ram - 2.5, max(4.0, avail_ram)), 1)
        opt_label = "极速腾退释放"
    elif opt == "2":
        # 极限深挖: 额外清理非核心后台应用，预留 0.6GB
        gpu_total_budget = round(min(total_vram - 0.6, max(3.5, free_vram + 1.0)), 1)
        avail_ram_budget = round(min(total_ram - 2.0, max(4.0, avail_ram + 1.5)), 1)
        opt_label = "极限深挖释放"
    elif opt == "3":
        # 温和优化: 只清内存，显存保持原状
        gpu_total_budget = round(max(3.5, total_vram - 1.6), 1)
        avail_ram_budget = round(min(total_ram - 3.0, max(4.0, avail_ram)), 1)
        opt_label = "内存工作集优化"
    else: # opt == "4" 原汁原味
        # 保守分配，防止与现有未清理的后台应用冲突爆显存
        gpu_total_budget = round(max(3.5, total_vram - max(1.8, used_vram)), 1)
        avail_ram_budget = round(max(3.0, avail_ram - 3.0), 1)
        opt_label = "保持现状未优化"

    if str(choice) == '1': # 全显存 / 显卡最大化加速
        if str(is_oversized) != '1' and size_gb <= gpu_total_budget - 1.2:
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
            mode = f"全显存加速模式 (全装显存 - {ctx}字上下文 - {opt_label})"
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
            elif raw_tokens >= 8192: ctx = 8192
            else: ctx = 8192
            flags = "-ctk q8_0 -ctv q8_0"
            mode = f"显卡最大化加速模式 ({ctx}字 - 显卡装载 {ngl}/{blocks}层 - {opt_label})"

    elif str(choice) == '2': # 显存装模型 + 内存装上下文
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
            mode = f"显存装模型+内存装上下文 ({ctx}字 - 全装显存 - KV进内存 - {opt_label})"
        else:
            mode = f"显存装模型+内存装上下文 ({ctx}字 - 显卡装载 {ngl}/{blocks}层 - KV进内存 - {opt_label})"

    elif str(choice) == '3': # 显存内存均衡共享模式
        reserved_free = 4.0 if opt in ("1", "2") else 5.0
        applied_vram = round(max(4.0, total_vram - reserved_free), 1)
        target_weights_vram = max(1.0, applied_vram - 1.2)
        ngl = min(blocks, max(4, int(target_weights_vram / gb_per_layer)))
        if str(is_oversized) != '1' and ngl >= blocks:
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
        mode = f"均衡共享模式 ({ctx}字 - 预留 {reserved_free}G 显存给前台 - {opt_label})" if str(is_oversized) != '1' else f"显存内存均衡共享 ({ctx}字 - {ngl}/{blocks}层 - 预留 {reserved_free}G 显存 - {opt_label})"

    elif str(choice) == '4': # 自定义显存模式
        target_str = str(target_vram).strip().lower() if target_vram else "4.0"
        import re
        num_match = re.search(r'(\d+(?:\.\d+)?)', target_str)
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
            mode = f"自定义显存模式 ({applied_vram}G 显存 - 全装显存 - {ctx}字 - 预留 {free_gpu}G - {opt_label})"
        else:
            mode = f"自定义显存模式 ({applied_vram}G 显存 - {ngl}/{blocks}层 - {ctx}字 - 预留 {free_gpu}G - {opt_label})"

    elif str(choice) == '5': # 纯内存模式
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
        mode = f"纯内存模式 ({ctx}字 - 显存0占用 - {opt_label})" if str(is_oversized) != '1' else f"纯内存漫游模式 ({ctx}字 - 全进内存 - {opt_label})"

    else:
        ngl = 99
        ctx = 16384
        mode = f"默认加速全显存模式 ({opt_label})"
        flags = "-ctk q8_0 -ctv q8_0"
        remain_layers = 0
        model_vram_est = size_gb
        applied_vram = total_vram

    if ctx < 4096: ctx = 4096

    res = f"{ngl}:{ctx}:{mode}:{flags}:{remain_layers}:{model_vram_est:.1f}:{applied_vram:.1f}:{blocks}\n"
    _bat_write(res)

def print_resource_banner(filepath, ngl_str="99", ctx_str="16384", extra_flags="", mode_str="", role_name="默认角色", n_predict_str="3000", total_blocks_str="40"):
    """在启动大模型前，打印直观、详细的模型显存/内存占用标注与硬件状态面板"""
    try:
        size_bytes = os.path.getsize(filepath)
        size_gb = round(size_bytes / (1024**3), 2)
    except Exception:
        size_gb = 8.0

    filename = os.path.basename(filepath)

    try:
        total_blocks = int(total_blocks_str)
        if total_blocks <= 0: total_blocks = 40
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

    # 硬件状态
    gpu_name, gpu_total, gpu_used, gpu_free = get_system_vram_info()
    ram_total, ram_used, ram_avail = get_system_ram_info()

    # 层数与权重分布计算
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

    # KV Cache 上下文显存/内存分布计算
    nkvo = "-nkvo" in extra_flags
    bytes_per_tok = max(20, total_blocks) * (4608 if "q4_0" in extra_flags else 8704)
    kv_gb = round((ctx * bytes_per_tok) / (1024**3), 2)

    # 预估模型显存/内存总体占用
    cuda_scratch = 0.3 if gpu_layers > 0 else 0.0
    model_vram_total = round(gpu_weights + (0.0 if nkvo else kv_gb) + cuda_scratch, 1)
    model_ram_total = round(cpu_weights + (kv_gb if nkvo else 0.0) + 0.3, 1)

    vram_pct = min(100, int((model_vram_total / max(1.0, gpu_total)) * 100))
    ram_pct = min(100, int((model_ram_total / max(1.0, ram_total)) * 100))
    offload_pct = int((gpu_layers / max(1, total_blocks)) * 100)

    # 获取网络访问端点
    from network_helper import get_network_ips
    lan_ip, tailscale_ip = get_network_ips()

    lines = [
        "======================================================================",
        "                 模型与硬件资源占用标注",
        "======================================================================",
        "【当前运行配置】",
        f" * 选定模型:   {filename} ({size_gb:.2f} GB)",
        f" * 运行模式:   {mode_str}",
        f" * 角色设定:   {role_name}",
        f" * 上下文大小: {ctx} Tokens  |  单次生成限制: {n_predict_str} Tokens",
        "",
        "【模型显存 / 内存占用标注】",
        f" * 模型显存占用: 约 {model_vram_total:.1f} GB / {gpu_total:.1f} GB (GPU 占用率约 {vram_pct}%)",
        f"   - 模型权重: 约 {gpu_weights:.2f} GB (GPU 硬件加速 {gpu_layers}/{total_blocks} 层，占比 {offload_pct}%)",
        f"   - 上下文KV: 约 {'0.00 GB (已分离至内存 -nkvo)' if nkvo else f'{kv_gb:.2f} GB (驻留显存，支持高速推理)'}",
        f"   - CUDA缓存: 约 {cuda_scratch:.1f} GB (计算图与工作区缓存)",
        f" * 模型内存占用: 约 {model_ram_total:.1f} GB / {ram_total:.1f} GB (RAM 占用率约 {ram_pct}%)",
        f"   - CPU驻留层: 约 {cpu_weights:.2f} GB (CPU 负责运算 {cpu_layers} 层)",
        f"   - 上下文KV:  约 {kv_gb:.2f} GB (驻留系统物理内存，保障长对话不爆显存)" if nkvo else f"   - 上下文KV:  0.00 GB (已完全卸载至 GPU 显存)",
        " * 硬件实时状态:",
        f"   - 显卡状态: {gpu_name} [总计 {gpu_total:.1f} GB | 已用 {gpu_used:.1f} GB | 剩余可用 {gpu_free:.1f} GB]",
        f"   - 内存状态: 物理内存 [总计 {ram_total:.1f} GB | 已用 {ram_used:.1f} GB | 剩余可用 {ram_avail:.1f} GB]",
        "----------------------------------------------------------------------",
        "【服务访问地址 (Web端与API已连通)】",
        " * [本机电脑直连]:       http://127.0.0.1:8080",
        f" * [局域网手机/平板]:     http://{lan_ip}:8080",
    ]
    if tailscale_ip:
        lines.append(f" * [Tailscale 远程]:     http://{tailscale_ip}:8080")
    lines.append(" * [OpenAI 兼容接口]:    http://127.0.0.1:8080/v1")
    lines.append("======================================================================")
    lines.append("")

    _bat_write("\n".join(lines) + "\n")

def check_template_compat(filepath):
    """检测模型架构是否兼容 Qwen/ChatML 自定义 Jinja 模板；非 Qwen 模型使用 GGUF 原生模板"""
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
        role = sys.argv[7] if len(sys.argv) > 7 else "默认角色"
        n_pred = sys.argv[8] if len(sys.argv) > 8 else "3000"
        blocks = sys.argv[9] if len(sys.argv) > 9 else "40"
        print_resource_banner(filepath, ngl, ctx, flags, mode, role, n_pred, blocks)

if __name__ == "__main__":
    main()
