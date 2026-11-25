<p align="right">
  <strong>English</strong> | <a href="README_ZH.md">简体中文</a>
</p>

# qidong — llama.cpp Smart Windows Launcher

An out-of-the-box **Windows Local LLM (`GGUF` / `llama.cpp`) Launcher & Hardware Resource Orchestrator**.
Double-click `qidong.bat`, then walk through a 5-step interactive menu (Model → Optimization → Strategy → Role → Length) to launch the inference engine and Web UI automatically.

---

## Key Features

| Module | Capabilities |
| :--- | :--- |
| **Auto Engine & CUDA Fetcher** | `llama_fetcher.py` auto-detects CPU architecture (`x64`/`arm64`), GPU vendor (NVIDIA Compute Capability & driver CUDA version via `nvidia-smi`, AMD/Intel/Qualcomm Vulkan, or CPU), downloads matching `llama-server` + `cudart-llama-bin-*` zips from `ggml-org/llama.cpp` Releases, verifies SHA-256, supports resume/retry, and handles zip-slip-safe installation |
| **Built-in GGUF Model Downloader** | `model_fetcher.py` (`[D]` in menu) downloads `.gguf` models directly into `models/` using stdlib only — supports curated starter models, any Hugging Face repo ID (live file tree listing), multi-part split GGUFs, direct URLs, and one-key switching between **Global (`huggingface.co`)** and **Mainland China (`hf-mirror.com`)** |
| **Cross-Drive Model Manager** | `model_manager.py` scans `models/` plus any external folders in `model_dirs.txt` (zero-copy across HDDs/SSDs/partitions, tagged `[Local]` / `[Drive X]`); automatically merges multi-part split GGUFs (`*-00001-of-0000N.gguf`) into one entry with true combined size; smartly matches `*mmproj*.gguf` vision projectors without pairing unrelated models |
| **Real Multi-Vendor GPU & CPU Detection** | Reads real VRAM for NVIDIA (`nvidia-smi`), AMD & Intel GPUs (Windows Display Adapter 64-bit registry), and cleanly switches to safe CPU-only Pure RAM mode (`-ngl 0`) when no dedicated GPU is present |
| **VRAM & RAM Optimization** | `memory_optimizer.py` pauses Wallpaper Engine (with an independent background guardian that restores wallpaper even on `Ctrl+C` or closing the window), trims process working sets, triggers CUDA VRAM pulse on NVIDIA GPUs, and supports user-editable `cleanup_apps.txt` for Mode `[2]` |
| **5 Dynamic Execution Strategies** | Computes live `-ngl` GPU layers, `-nkvo` KV placement, and safe `-c` context size at every launch: Full-Speed VRAM / VRAM Model + RAM KV (`-nkvo`) / Balanced / Custom VRAM Cap / Pure RAM |
| **Chat Template Adaptation** | Uses `_active_template.jinja` for Qwen-family models and automatically switches to built-in GGUF chat templates for other architectures (Llama / Gemma / Mistral / DeepSeek, etc.) |
| **Dual Role Management** | Interactive CLI manager (`[M]`) and live Web UI Role Switcher modal: search, expand full prompt, create, edit, delete, hot-switch, **Native Default (No Role)**, and **Temporary Custom Role** |
| **Web, Mobile & OpenAI API Hub** | `server_core.py` provides Desktop UI (`/`), responsive Mobile Workstation (`/mobile`), OpenAI-compatible API (`/v1`), SQLite WAL chat history, burn-after-reading share links (`/share/{token}`), and optional lightweight **Access Token** protection |
| **Optional Regional Remote Access** | `remote_access.py` (`[R]` in menu) detects LAN / Tailscale / EasyTier / ZeroTier endpoints and optionally installs/fetches region-appropriate external remote-access tools |

---

## Requirements

- Windows 10 / 11 (x64 or ARM64)
- NVIDIA GPU, AMD/Intel GPU (Vulkan), or CPU-only PC
- **Python 3.9+**
  - During Python installation from [python.org](https://www.python.org/downloads/windows/), check **"Add python.exe to PATH"** — or extract a portable/embedded Python into `python\` inside this folder.
  - Standard library alone runs `qidong.bat`, `llama_fetcher.py`, `model_fetcher.py`, `remote_access.py`, `memory_optimizer.py`, and CLI role management.
  - Installing `requirements.txt` (`[I]` in main menu) enables the full Web Hub (`server_core.py`: persistent SQLite chats, online Web UI role editing, `/mobile`, burn-after-reading sharing, and optional Access Token auth). Without it, `qidong.bat` automatically falls back to native `llama-server` on port `8080`.

---

## Quick Start (Zero Manual File Hunting)

1. **Double-click `qidong.bat`**.
2. **Install `llama-server` & Runtime (`[F]`)**:
   - Press `F` to auto-detect your GPU/driver and download the matching `llama.cpp` Windows package + `cudart` runtime automatically (or skip — `qidong.bat` also auto-runs `llama_fetcher.py ensure` if `llama-server.exe` is missing at launch).
   - Manual option: extract matching `llama-bXXXX-bin-win-cuda-XX.Y-x64.zip` and `cudart-llama-bin-win-cuda-XX.Y-x64.zip` from [ggml-org/llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) alongside `qidong.bat` (keep the same CUDA version for both!).
3. **Add or Download Models (`[D]` or `model_dirs.txt`)**:
   - Press `D` to download a starter GGUF model (switch `[M]` between `huggingface.co` and `hf-mirror.com`), **OR**
   - Drop `.gguf` files directly into `models/`, **OR**
   - **Cross-Drive Zero-Copy Loading**: open `model_dirs.txt` and add absolute paths to existing model folders on any drive (e.g., `D:\AI\Models`, `E:\GGUF-Library`), one path per line.
4. **Install Optional Web Hub Dependencies (`[I]`)**:
   - Press `I` in the main menu to run `pip install -r requirements.txt` (lets you pick Official PyPI or China Tsinghua Mirror).
5. **Select a model and follow the 5-step wizard** (Model → Optimization → Strategy → Role → Max Response Length).

---

## Optional Remote Access & Regional Software Guide (`[R]`)

Local PC (`http://127.0.0.1:8080`) and same-Wi-Fi LAN access (`http://<LAN-IP>:8080/mobile`) work **out of the box with zero extra software**.

If you want to chat with your home PC's LLM from your phone or laptop **outside your home Wi-Fi**, qidong relies on external networking tools rather than bundling a relay server. Press **`R`** in the main menu (or run `python remote_access.py menu`) for an **optional** helper with region-tailored recommendations and auto-downloaders:

| User Region | Recommended Software | Why / Features | Optional Setup via `[R]` |
| :--- | :--- | :--- | :--- |
| **Global / Overseas** | **Tailscale** *(Recommended)* | Private WireGuard P2P mesh VPN; install on PC + Phone and visit `http://<100.x.x.x>:8080/mobile` | `[1]` Guided setup / optional `winget install Tailscale.Tailscale` |
| **Mainland China** | **EasyTier** *(Recommended)* | Open-source decentralized P2P mesh VPN with CN-friendly public shared nodes; no overseas account required; Windows/Android/iOS support | `[2]` Auto-downloads portable `easytier-windows-*.zip` from `EasyTier/EasyTier` Releases (supports `--mirror`) into `tools/easytier/` |
| **Any Region (No Phone App)** | **Cloudflare Tunnel (`cloudflared`)** | Creates a temporary public HTTPS URL (`https://*.trycloudflare.com`) without installing any app on your phone | `[3]` Auto-downloads portable `cloudflared.exe` into `tools/cloudflared/`; `[6]` launches quick tunnel |
| **Cross-Region Alternative** | **ZeroTier One** | Mature virtual LAN working across China and global networks | `[4]` Guided setup / optional `winget install ZeroTier.ZeroTierOne` |

> `network_helper.py` automatically detects active **LAN**, **Tailscale**, **EasyTier**, and **ZeroTier** IPs and prints them in the startup banner.

### Optional Remote Access Token (Security Protection)

By default, remote access authentication is **disabled** for maximum convenience on private home Wi-Fi or personal Tailscale/EasyTier networks.

If you connect over **public/shared Wi-Fi** or open a **Cloudflare Quick Tunnel**, enable the optional Access Token via `[R] -> [5]` (or `python remote_access.py token gen`, or set env var `WEB_ACCESS_TOKEN`):
- **Localhost (`127.0.0.1`) automatically stays password-free** on your host PC (unless `WEB_AUTH_LOCAL=1` is set).
- **Proxied / remote clients** (LAN, VPN, and Cloudflare Tunnel with `X-Forwarded-For` / `CF-Connecting-IP`) must authenticate via:
  - Browser unlock screen or `http://<IP>:8080/?token=<YOUR_TOKEN>` (sets an `HttpOnly` session cookie automatically), **OR**
  - Standard OpenAI API header `Authorization: Bearer <YOUR_TOKEN>` (simply paste the token as the API Key in Cherry Studio / OpenWebUI / Cursor!).

---

## CLI Tools Reference

```powershell
# 1. Hardware-adaptive llama.cpp engine & CUDA runtime fetcher
python llama_fetcher.py info                  # Inspect GPU, driver CUDA, local build & recommended package
python llama_fetcher.py install               # Download & install matching engine + cudart runtime
python llama_fetcher.py update                # Update to the latest compatible ggml-org/llama.cpp build
python llama_fetcher.py list                  # List available Windows variants in the latest release
# Optional flags: --variant cuda-13.5|cuda-12.4|vulkan|cpu  --tag bXXXX  --mirror <PREFIX>  -y

# 2. GGUF model downloader
python model_fetcher.py menu                  # Interactive starter repos / custom HF repo / direct URL
python model_fetcher.py list Qwen/Qwen2.5-3B-Instruct-GGUF --mirror cn
python model_fetcher.py download Qwen/Qwen2.5-3B-Instruct-GGUF --mirror cn

# 3. Optional remote access & access token helper
python remote_access.py status                # Show detected VPN/tunnel tools, IPs & token status
python remote_access.py install easytier      # Download portable EasyTier into tools/easytier/
python remote_access.py install cloudflared   # Download portable cloudflared into tools/cloudflared/
python remote_access.py token gen             # Generate optional .access_token
python remote_access.py token clear           # Disable optional .access_token
python remote_access.py tunnel                # Launch Cloudflare Quick Tunnel (prompts to enable token)
```

---

## 5-Step Launcher Flow & Web Endpoints

1. **Select Model**: Pick model index, `F` (Engine/CUDA), `D` (Download Models), `R` (Remote Access/Token), `I` (Install Python Deps), or `0` (Exit).
2. **VRAM/RAM Optimization**: `[1]` Fast Deep Cleanup / `[2]` Aggressive Cleanup (reads `cleanup_apps.txt`) / `[3]` Gentle RAM Trim / `[4]` Skip.
3. **Execution Strategy**: `[1]` Full-Speed VRAM / `[2]` VRAM Model + RAM KV (`-nkvo`) / `[3]` Balanced / `[4]` Custom VRAM Cap / `[5]` Pure RAM (CPU-only PCs automatically fall back safely to `-ngl 0`).
4. **Role Preset**: Choose preset from `role_setting.txt`, `N` (Native Default / No Role), `E` (Temporary Custom Role), or `M` (Role Manager).
5. **Max Output Length**: `1500` / `3000` / `7500` / `12000` / `-1` (unlimited) or any custom integer.

| Endpoint | URL |
| :--- | :--- |
| Desktop Web UI | `http://127.0.0.1:8080/` |
| Mobile Workstation | `http://<LAN-OR-VPN-IP>:8080/mobile` (or `/m`) |
| OpenAI-Compatible API | `http://127.0.0.1:8080/v1` |
| Burn-After-Reading Share | `POST /api/links/create` → `/share/{token}` |

> Note: Sample role cards in `role_setting.txt` are preserved in their original form; you can freely edit or add roles in any language via CLI `[M]` or the Web UI Role Switcher button.

---

## Project Structure

```text
├── qidong.bat               # Main Windows launcher (ASCII/UTF-8, chcp 65001)
├── llama_fetcher.py         # Auto hardware detector & llama.cpp + CUDA runtime downloader
├── model_fetcher.py         # Optional GGUF downloader (Hugging Face / hf-mirror / direct URL)
├── remote_access.py         # Optional regional remote-access installer & Access Token helper
├── model_manager.py         # Multi-drive GGUF scanner, split-GGUF merger, mmproj matcher & VRAM/RAM planner
├── memory_optimizer.py      # VRAM/RAM release & Wallpaper Engine guardian
├── role_manager.py          # CLI & Web UI role preset manager + Jinja template sync
├── server_core.py           # FastAPI Web & API Hub, optional auth middleware, /mobile UI & reverse proxy
├── db_manager.py            # SQLite WAL conversation store & burn-after-reading share links
├── network_helper.py        # LAN / Tailscale / EasyTier / ZeroTier IP detector
├── thinking_parser.py       # <think> reasoning tag parser
├── model_dirs.txt           # Cross-drive external model directory list
├── cleanup_apps.txt         # Editable background process list for Optimization Mode [2]
├── role_setting.txt         # Role preset cards
├── _active_template.jinja   # Custom Qwen chat template
├── requirements.txt         # Optional Python dependencies for Web Hub
├── README.md / README_ZH.md # Bilingual documentation
├── models/                  # Local .gguf model folder
└── web/                     # Static Web UI assets
```

---

## License

MIT License — see [LICENSE](LICENSE).
Static Web UI assets under `web/_app/` originate from [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT).
