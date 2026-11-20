# qidong — llama.cpp Smart Windows Launcher

An out-of-the-box **Windows Local LLM (`GGUF` / `llama.cpp`) Launcher & Hardware Resource Orchestrator**.
Double-click `qidong.bat`, then walk through a 5-step interactive menu (Model → Optimization → Strategy → Role → Length) to launch the inference engine and Web UI automatically.

---

## Key Features

| Module | Capabilities |
| :--- | :--- |
| **Auto Engine & CUDA Fetcher** | `llama_fetcher.py` auto-detects CPU architecture (`x64`/`arm64`), GPU vendor (NVIDIA Compute Capability & driver CUDA version via `nvidia-smi`, AMD/Intel/Qualcomm Vulkan, or CPU), fetches matching `llama-server` + `cudart-llama-bin-*` zips from `ggml-org/llama.cpp` Releases, verifies SHA-256 checksums, supports resume/retry, and handles zip-slip-safe installation |
| **Multi-Directory Model Manager** | Scans `models/` plus any external folders listed in `model_dirs.txt` (zero-copy cross-drive support) with `[Local]` / `[Drive X]` source tags; parses GGUF layer counts & architecture with caching; auto-attaches matching `mmproj` vision projectors |
| **VRAM & RAM Optimization** | 4 optimization presets: suspends Wallpaper Engine, trims background process working sets, triggers CUDA VRAM cleanup pulse, and optionally shuts down non-essential heavy background processes |
| **Wallpaper Restore Guardian** | Independent background guardian process: restores paused dynamic wallpapers automatically on normal exit, `Ctrl+C`, or closing the console window |
| **Dynamic Strategy Calculator** | Reads live free VRAM and system RAM at every launch to dynamically compute `-ngl` GPU layers, KV cache placement (`-nkvo`), and maximum safe `-c` context size — never hardcoded |
| **5 Execution Strategies** | Full-Speed VRAM / Model in VRAM + KV Cache in RAM (`-nkvo`) / Balanced Multitask / Custom VRAM Cap / Pure RAM Mode |
| **Chat Template Adaptation** | Uses the included custom Jinja template for Qwen-family models and automatically switches to built-in GGUF chat templates for other architectures (Llama / Gemma / Mistral / DeepSeek, etc.) |
| **Dual Role Management** | Interactive CLI manager and in-browser Web UI Role Switcher modal: search, expand full prompt, create, edit, delete, hot-switch, Native Default (No Role), and Temporary Custom Role |
| **Web & API Hub** | Desktop UI (`/`), responsive Mobile Workstation (`/mobile`), OpenAI-compatible endpoints (`/v1`), SQLite WAL persistent chat history, burn-after-reading share links (`/share/{token}`), and automatic LAN / Tailscale URL display |

---

## Requirements

- Windows 10 / 11 (x64 or ARM64)
- NVIDIA GPU (with up-to-date driver), AMD/Intel GPU (Vulkan), or CPU-only fallback
- Python 3.9+ (standard library only is enough for the launcher, fetcher, optimizer, and CLI role manager)

> Installing `requirements.txt` unlocks the full Web Hub (`server_core.py`: persistent SQLite conversations, live Web UI role editing/creation, burn-after-reading sharing, and `/mobile`). Without those packages, `qidong.bat` automatically falls back to serving the native `llama-server` UI on port `8080`.

---

## Setup & Installation

### 1. Install `llama-server` & Runtime Binaries (Automatic or Manual)

This repository does not bundle large binary executables. You have two options:

#### Option A: Automatic Hardware-Matched Download (Recommended)
1. Double-click `qidong.bat` and enter **`F`** at the main menu (or run `python llama_fetcher.py menu`).
2. `llama_fetcher.py` automatically inspects your hardware and selects the right build:
   - **NVIDIA Turing+ (`sm_75+`, GTX 16xx / RTX 20xx–50xx)** with CUDA 13.x driver → `cuda-13.x` (`llama-bXXXX-bin-win-cuda-13.x-x64.zip` + `cudart-llama-bin-win-cuda-13.x-x64.zip`)
   - **NVIDIA Maxwell/Pascal/Volta (`sm_50–72`) or CUDA 12.x driver** → `cuda-12.4` + matching `cudart`
   - **AMD / Intel / Qualcomm GPU** → `vulkan`
   - **No GPU / Unsupported GPU** → `cpu`
3. If you launch a model when `llama-server.exe` is missing, `qidong.bat` also triggers `llama_fetcher.py ensure` automatically before startup.

CLI usage examples:
```powershell
python llama_fetcher.py info        # Show detected hardware, installed version, and recommended variant
python llama_fetcher.py install     # Download & install recommended engine + CUDA runtime
python llama_fetcher.py update      # Update to the latest compatible ggml-org/llama.cpp build
python llama_fetcher.py list        # List recent releases and available Windows binary variants
```
Optional flags: `--variant cuda-13.5|cuda-12.4|vulkan|cpu`, `--tag bXXXX`, `--mirror <URL_PREFIX>`, `-y`.

#### Option B: Manual Download from `llama.cpp` Releases
Download the matching Windows x64 zips from [ggml-org/llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) and extract them alongside `qidong.bat`:

```text
your-folder/
├── qidong.bat
├── llama-server.exe                        <- Engine zip contents extracted alongside qidong.bat
├── ggml*.dll / llama*.dll ...
└── cudart-llama-bin-win-cuda-13.x-x64/     <- CUDA runtime DLLs (or placed directly next to qidong.bat)
    ├── cudart64_13.dll
    ├── cublas64_13.dll
    └── cublasLt64_13.dll
```

At startup, `qidong.bat` automatically prepends any `cudart-llama-bin-*` subfolder to `PATH`. Keep the engine zip and `cudart` zip on the **same major/minor CUDA version** (do not mix e.g. `cuda-12.4` and `cuda-13.x`).

### 2. Install Python Dependencies (Optional, Recommended for Web Hub)

```bash
pip install -r requirements.txt
```

### 3. Add GGUF Models

- Place `.gguf` files (and optional `*mmproj*.gguf` vision projectors) inside `models/`, **or**
- Edit `model_dirs.txt` and add absolute paths to existing model folders (one per line; `#` starts a comment).

---

## Usage Guide

Double-click `qidong.bat` and follow the 5 steps:

1. **Select Model**: Enter an index (Press `Enter` for `[1]`), `F` to open the Auto Engine/CUDA Fetcher menu, or `0` to exit.
2. **Select Memory/VRAM Optimization**:
   - `[1]` **Rapid Deep Release (Recommended)**: Pause dynamic wallpaper + trim working sets + CUDA VRAM pulse
   - `[2]` **Extreme Clean**: Step 1 + close selected heavy background apps
   - `[3]` **Gentle**: RAM working-set trim only
   - `[4]` **Skip Optimization**
   - `0` Back to model list
3. **Select Execution Strategy**: Computes GPU layers (`-ngl`), RAM layers, and safe context capacity (`-c`):
   - Small models & max speed → `[1] Full-Speed VRAM Mode`
   - Large models / 32K–128K context → `[2] Model in VRAM + KV Cache in RAM`
   - Multitasking with games or ComfyUI → `[3] Balanced` or `[4] Custom VRAM Cap Mode`
   - Leave 100% GPU free → `[5] Pure RAM Mode`
4. **Select Role Preset**:
   - Enter number: activate that saved preset from `role_setting.txt`
   - `N`: **Native Default (No Role)** — no system prompt injection (best for coding, translation, raw model behavior)
   - `E`: **Temporary Custom Role** — paste multi-line prompt (**blank line + Enter to finish**, `0` to cancel), with optional save to presets
   - `M`: **Role Preset Manager** (`A` Add / `E` Edit / `V` View full / `D` Delete / `O` Open in Notepad)
   - Press `Enter`: keep currently active role
5. **Select Max Response Length**: `1500` / `3000` / `7500` / `12000` tokens, `-1` (unlimited), or enter any custom integer.

Once started, open:

| Endpoint | URL |
| :--- | :--- |
| Desktop Web UI | `http://127.0.0.1:8080/` |
| Mobile Workstation | `http://<LAN-IP>:8080/mobile` (printed in console at startup) |
| OpenAI-Compatible API | `http://127.0.0.1:8080/v1` |

When the session exits, paused wallpapers/apps restore immediately and you can `[1]` Restart, `[2]` Reselect Role, `[3]` Reselect Strategy, or `[0]` Return to Model Selection.

### Web UI Role Management

Click the Role Switcher pill in the top-right corner of the Web UI to search roles, expand long prompts, create/edit/delete presets, switch roles live, or toggle **Native Default (No Role)** — all changes take effect on your next message and persist to `role_setting.txt`.

### `role_setting.txt` Format

Each role in `role_setting.txt` starts with `[Role Name]` on its own line, followed by multi-line prompt text below it. Note: sample role cards included in `role_setting.txt` are preserved in their original form, and you can freely add roles in any language.

---

## Project Structure

```text
├── qidong.bat               # Main Windows launcher (ASCII/UTF-8, chcp 65001)
├── llama_fetcher.py         # Auto hardware detector & llama.cpp + CUDA runtime downloader
├── model_manager.py         # Multi-directory GGUF scanner, architecture check & strategy calculator
├── memory_optimizer.py      # VRAM/RAM release & Wallpaper Engine guardian
├── role_manager.py          # CLI & Web UI role preset manager + Jinja template sync
├── server_core.py           # FastAPI Web & API Hub, SSE streaming, /mobile UI & reverse proxy
├── db_manager.py            # SQLite WAL conversation store & burn-after-reading share links
├── network_helper.py        # LAN / Tailscale endpoint detector
├── thinking_parser.py       # <think> reasoning tag parser
├── model_dirs.txt           # External model directory list
├── role_setting.txt         # Role preset cards
├── _active_template.jinja   # Custom Qwen chat template
├── requirements.txt         # Optional Python dependencies for Web Hub
├── models/                  # Local .gguf model folder
└── web/                     # Static Web UI assets
```

---

## Troubleshooting

- **`llama-server.exe` not found**: Run `[F]` in `qidong.bat` (or `python llama_fetcher.py install`) to auto-download the matching binary package, or extract `llama.cpp` Windows release files next to `qidong.bat`.
- **Missing `cudart64_13.dll` / `cublas64_13.dll`**: Use `llama_fetcher.py install` so both the engine and `cudart` packages are fetched together on the same CUDA version, and do not mix e.g. `cuda-12.4` and `cuda-13.x`.
- **Web UI cannot save roles / missing `/mobile`**: Install `pip install -r requirements.txt` so `server_core.py` starts instead of falling back to standalone `llama-server`.
- **Mobile device cannot connect**: Ensure the phone and PC are on the same LAN (or Tailscale) and allow TCP port `8080` through Windows Firewall.

---

## License

MIT License — see [LICENSE](LICENSE).
Static Web UI assets under `web/_app/` originate from [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT).
