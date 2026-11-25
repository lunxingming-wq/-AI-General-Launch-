<p align="right">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

# qidong — llama.cpp Windows 智能启动中心

一个开箱即用的 **Windows 本地大模型（GGUF / llama.cpp）智能启动与硬件资源调度工具**。  
双击 `qidong.bat`，依次完成 5 步向导（选模型 → 选优化 → 选策略 → 选角色 → 选长度），即可一键启动推理引擎、桌面/手机 Web 界面与 OpenAI 兼容接口。

---

## 核心功能一览

| 模块 | 说明 |
| :--- | :--- |
| **硬件自适应引擎拉取器** | `llama_fetcher.py`（主菜单 `[F]`）自动检测 CPU 架构（`x64`/`arm64`）、NVIDIA 算力与驱动 CUDA 版本（`nvidia-smi`）、AMD/Intel/高通 GPU 或纯 CPU，自动从 `ggml-org/llama.cpp` Releases 成对下载匹配的 `llama-server` 与 `cudart-llama-bin-*`，支持 SHA-256 校验、断点续传与防路径穿越解压 |
| **内置 GGUF 模型下载器** | `model_fetcher.py`（主菜单 `[D]`）纯标准库下载 `.gguf` 模型到 `models/`：内置轻量入门模型仓库、支持任意 Hugging Face 仓库实时拉取文件列表、自动成套下载分卷模型、支持直链下载，并可一键切换 **国际官方 (`huggingface.co`)** 与 **国内镜像 (`hf-mirror.com`)** |
| **跨硬盘零复制模型管理** | `model_manager.py` 扫描 `models/` 及 `model_dirs.txt` 配置的任意外部目录（机械盘/移动硬盘跨盘直接加载，无需复制，带 `[Local]` / `[Drive X]` 标签）；自动合并分卷 GGUF（`*-00001-of-0000N.gguf`）为单条选项并计算总大小；智能匹配对应 `*mmproj*.gguf` 视觉组件，避免误挂到纯文本模型 |
| **全硬件真实显存识别** | 精确识别 NVIDIA（`nvidia-smi`）、AMD / Intel 独立显存（读取 Windows 64 位显示适配器注册表，不封顶 4GB），无独显时诚实识别为纯 CPU 模式（`0 GB`）并自动强制 `-ngl 0` 防 OOM |
| **显存/内存腾退与守护** | `memory_optimizer.py` 支持暂停 Wallpaper Engine（配独立后台守护进程，正常退出、`Ctrl+C` 或直接点 `×` 关窗口均自动恢复壁纸）、压缩后台进程工作集、N 卡 CUDA 显存脉冲，且模式 `[2]` 的清理进程名单已外置到 `cleanup_apps.txt` 由用户自由编辑 |
| **5 种动态运行策略** | 每次启动按当前实时剩余显存/内存动态计算 `-ngl` 层数、`-nkvo` 分配与安全 `-c` 上下文：全显存加速 / 显存装模型+内存装上下文(`-nkvo`) / 均衡共存 / 自定义显存上限 / 纯内存 |
| **对话模板自适应** | Qwen 系列使用内置 Jinja 模板；Llama / Gemma / Mistral / DeepSeek 等非 Qwen 架构自动使用 GGUF 内置原生模板 |
| **双端角色卡管理** | 命令行 `[M]` 与网页右上角浮窗双端支持：搜索、展开全文、新建、编辑、删除、热切换、**原生默认（无角色）**、**临时自定义角色（可转存永久）** |
| **Web / 移动端 / API 中枢** | `server_core.py` 提供桌面页 `/`、手机端 `/mobile`、OpenAI 接口 `/v1`、SQLite WAL 持久化会话、主动停止生成、阅后即焚分享 `/share/{token}`，以及**可选访问密钥保护** |
| **可选多地区远程访问助手** | `remote_access.py`（主菜单 `[R]`）自动检测 LAN / Tailscale / EasyTier / ZeroTier 地址，并针对不同国家/地区提供可选的一键拉取与安装指引 |

---

## 环境要求

- Windows 10 / 11（x64 或 ARM64）
- NVIDIA 显卡、AMD/Intel 显卡（Vulkan）或纯 CPU 电脑
- **Python 3.9+**
  - 从 [python.org](https://www.python.org/downloads/windows/) 安装时请务必勾选 **"Add python.exe to PATH"**；或直接将嵌入式便携 Python 解压至本目录 `python\` 文件夹下。
  - 仅靠 Python 标准库即可运行启动器、引擎拉取、模型下载、远程工具助手、显存优化与命令行角色管理。
  - 在主菜单按 **`[I]`** 一键安装 `requirements.txt`（可选官方源或国内清华源）后，启用完整 `server_core.py` Web 中枢；未安装时自动降级为 `llama-server` 原生界面（端口 `8080`）。

---

## 快速上手（零手动找文件）

1. **双击运行 `qidong.bat`**。
2. **安装推理引擎与 CUDA 运行时（主菜单按 `F`）**：
   - 自动检测本机显卡与驱动并下载匹配的 `llama.cpp` 与 `cudart` 运行时压缩包（未安装时直接启动模型也会自动触发 `llama_fetcher.py ensure`）。
   - 也可手动从 [ggml-org/llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) 下载同版本引擎包与 `cudart` 包解压到与 `qidong.bat` 同级目录（注意引擎与 `cudart` 的 CUDA 版本必须一致）。
3. **准备或下载模型（按 `D` 或配置 `model_dirs.txt`）**：
   - 按 `D` 进入模型下载器，可按 `[M]` 切换国内高速镜像 `hf-mirror.com` 下载入门模型或任意 Hugging Face 仓库；
   - 或直接把 `.gguf` 文件放入 `models/`；
   - **跨硬盘加载**：编辑 `model_dirs.txt`，每行填一个已有模型目录绝对路径（如 `D:\AI\Models`），启动器直接跨盘读取无需复制。
4. **一键安装可选 Web 中枢依赖（主菜单按 `I`）**：
   - 按 `I` 可选清华镜像源或官方 PyPI 安装 `fastapi`、`uvicorn`、`aiohttp`。
5. **选择模型，按 5 步菜单完成启动**。

---

## 可选远程访问软件指南（按国家/地区推荐，主菜单 `[R]`）

本机访问（`http://127.0.0.1:8080`）与同一 Wi-Fi 下的手机局域网访问（`http://<局域网IP>:8080/mobile`）**开箱即用，无需任何外部软件**。

若希望出门在外通过手机/笔记本远程访问家里电脑上的本地大模型，可通过主菜单 **`[R]`**（或运行 `python remote_access.py menu`）按所在地区**可选**安装或自动拉取外部组网/穿透工具：

| 适用地区 | 推荐外部软件 | 特点与适用场景 | `[R]` 菜单可选拉取/配置 |
| :--- | :--- | :--- | :--- |
| **海外 / 国际用户** | **Tailscale** *(首选)* | 私有 WireGuard P2P 虚拟局域网，电脑和手机登录同一账号即可访问 `http://<100.x.x.x>:8080/mobile` | `[1]` 引导安装 / 可选调用 `winget install Tailscale.Tailscale` |
| **中国大陆用户** | **EasyTier** *(首选)* | 开源去中心化 P2P 异地组网，支持国内公共共享节点、无需海外账号，支持 Windows/Android/iOS | `[2]` 自动从 `EasyTier/EasyTier` Releases 拉取便携版至 `tools/easytier/`（支持 `--mirror`） |
| **任意地区（手机免装 App）** | **Cloudflare Tunnel (`cloudflared`)** | 一条命令生成临时 HTTPS 公网链接（`https://*.trycloudflare.com`），手机浏览器直接打开 | `[3]` 自动拉取便携 `cloudflared.exe` 至 `tools/cloudflared/`；`[6]` 一键启动隧道 |
| **跨区备选** | **ZeroTier One** | 成熟 P2P 虚拟局域网，国内与海外均可使用 | `[4]` 引导安装 / 可选调用 `winget install ZeroTier.ZeroTierOne` |

> `network_helper.py` 启动时会自动检测并打印已激活的 **局域网 / Tailscale / EasyTier / ZeroTier** 访问地址。

### 可选远程访问密钥保护（默认关闭，零打扰）

- 在自家 Wi-Fi 或个人 Tailscale / EasyTier 私有网下，默认无需密钥即可直接访问。
- 如果在 **公共/公司 Wi-Fi** 使用，或开启了 **Cloudflare Tunnel 公网临时链接**，强烈建议在 `[R] -> [5]` 开启可选访问密钥（或执行 `python remote_access.py token gen` / 设置环境变量 `WEB_ACCESS_TOKEN`）：
  - **本机电脑访问 `127.0.0.1:8080` 默认自动免密**（无需每次输入密码，如需本机也鉴权可设 `WEB_AUTH_LOCAL=1`）。
  - **局域网 / VPN / Cloudflare 隧道转发过来的远程请求**均受保护：手机浏览器打开后输入一次密钥（或访问 `?token=密钥`）即写入 `HttpOnly` Cookie 保持登录；Cherry Studio / Cursor 等 OpenAI 客户端直接把该密钥填进 `API Key`（`Authorization: Bearer`）即可无缝调用。

---

## 常用命令行参考

```powershell
# 1. 硬件自适应引擎与 CUDA 运行时拉取器
python llama_fetcher.py info                  # 查看识别到的显卡、驱动 CUDA、当前版本与推荐包
python llama_fetcher.py install               # 下载并安装匹配的引擎 + cudart 运行时
python llama_fetcher.py update                # 检查并更新到最新兼容构建
python llama_fetcher.py list                  # 列出最新 Release 中可用的 Windows 变体

# 2. GGUF 模型下载器
python model_fetcher.py menu                  # 交互式模型下载菜单（支持一键切换国内 hf-mirror.com）
python model_fetcher.py download Qwen/Qwen2.5-3B-Instruct-GGUF --mirror cn

# 3. 可选远程访问与访问密钥助手
python remote_access.py status                # 查看已安装的远程工具、IP 与密钥状态
python remote_access.py install easytier      # 自动拉取便携版 EasyTier（可加 --mirror 加速）
python remote_access.py install cloudflared   # 自动拉取便携版 cloudflared
python remote_access.py token gen             # 生成可选访问密钥 (.access_token)
python remote_access.py token clear           # 关闭密钥保护
python remote_access.py tunnel                # 启动 Cloudflare Quick Tunnel（未设密钥会自动提醒）
```

---

## 目录结构

```text
├── qidong.bat               # 主启动脚本（GitHub 开源版为英文 ASCII + chcp 65001）
├── llama_fetcher.py         # 硬件自适应 llama.cpp + CUDA 运行时拉取器
├── model_fetcher.py         # 可选 GGUF 模型下载器（Hugging Face / hf-mirror / 直链）
├── remote_access.py         # 可选多地区远程访问软件拉取与密钥助手
├── model_manager.py         # 跨盘模型扫描、分卷合并、mmproj 智能匹配与显存策略计算
├── memory_optimizer.py      # 显存/内存腾退与 Wallpaper Engine 守护恢复
├── role_manager.py          # 角色卡管理、模板同步与网页悬浮窗注入
├── server_core.py           # FastAPI Web & API 中枢、可选密钥中间件、移动端页面与反向代理
├── db_manager.py            # SQLite WAL 会话与阅后即焚分享链接
├── network_helper.py        # LAN / Tailscale / EasyTier / ZeroTier 地址检测
├── thinking_parser.py       # <think> 思考过程解析器
├── model_dirs.txt           # 跨硬盘外部模型目录配置文件
├── cleanup_apps.txt         # 极限清理模式 [2] 可自定义后台进程白名单
├── role_setting.txt         # 角色卡预设文件（保留原始示例角色卡）
├── _active_template.jinja   # Qwen 系列自定义对话模板
├── requirements.txt         # 可选 Python 依赖清单
├── README.md / README_ZH.md # 中英双语说明文档
├── models/                  # 本地 .gguf 模型目录
└── web/                     # Web UI 静态资源
```

---

## 开源协议

MIT License — 详见 [LICENSE](LICENSE)。  
`web/_app/` 下的静态界面资源来源于 [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)（MIT）。
