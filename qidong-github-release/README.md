# llama.cpp Windows 智能启动中心 (`qidong`)

一个轻量、开箱即用的 **Windows 本地大模型（GGUF / llama.cpp）智能启动与资源调度工具**。

内置 **显存/内存深度腾退优化与壁纸自动守护恢复、实时硬件探测与上下文精算、多磁盘免复制模型聚合、命令行与网页端双向角色管理（增删改查 + 实时热切换 + 原生无角色模式）、多模型架构对话模板自适应，以及局域网/移动端 Web UI 与 SQLite 持久化中枢**。

---

## 核心特性

- **多磁盘免复制模型聚合 (`model_manager.py` + `model_dirs.txt`)**
  - 自动扫描本地 `models/` 目录，并支持在 `model_dirs.txt` 中追加任意分区/外置硬盘路径，聚合展示来源标签（如 `[本地]`、`[D盘]`），无需跨盘复制大文件。
  - 自动解析 GGUF 头部元数据（层数 `block_count`、模型架构 `general.architecture`）并缓存加速。
- **多架构对话模板自适应**
  - Qwen 家族模型自动挂载防冲突的 Jinja 模板；Gemma / Llama / Mistral / DeepSeek 等非 Qwen 模型自动切换为 GGUF 内置原生对话模板，避免跨模型模板错乱。
- **显存与内存深度腾退优化 + 后台守护进程 (`memory_optimizer.py`)**
  - 支持自动挂起 Wallpaper Engine 动态壁纸、压缩后台进程工作集、触发 CUDA 显存脉冲清理显存缓存。
  - 内置独立无窗口守护进程（`--guardian`）：无论模型正常退出、按 `Ctrl+C` 还是直接点右上角 `[X]` 关闭控制台，均会自动恢复动态壁纸播放。
- **硬件自适应分层与上下文精算 (`model_manager.py`)**
  - 每次启动实时读取 NVIDIA 显卡剩余显存（`nvidia-smi`）与系统剩余物理内存（`GlobalMemoryStatusEx`）。
  - 提供 5 种运行策略（全显存加速、显存装模型 + 内存装上下文 `-nkvo`、均衡共享、自定义显存上限、纯内存模式），动态计算最佳 `-ngl` 层数与 `-c` 上下文容量。
- **人性化全端角色设定管理 (`role_manager.py` + `server_core.py`)**
  - **桌面端与移动端 Web UI**：内置人物卡管理浮窗，支持**在线搜索、展开全文、新建、编辑、删除、热切换**，以及一键切换 **⚪ 原生默认模式（不注入任何角色设定）**，修改立即写入 `role_setting.txt` 并对下一条消息生效（无双人设叠加冲突，也不再被浏览器旧缓存覆盖）。
  - **命令行交互式管理中心 (`[M]`)**：支持预览摘要、新增、编辑、查看全文、确认删除，以及兼容 Win11 多标签记事本的手动回车刷新模式。
  - **临时自定义角色 (`[E]`)**：支持单行/多行输入，**空行回车即完成、输入 `0` 取消**，还可一键转存为永久角色并同步到 Web UI。
- **统一 Web 交互与 API 中枢 (`server_core.py`)**
  - 提供桌面端 Web UI（`/`）、移动端自适应页面（`/mobile`）、OpenAI 兼容接口（`/v1`）、SQLite WAL 会话持久化与阅后即焚分享链接。
  - 自动识别本机、局域网 IP 及 Tailscale 远程地址；若未安装 Web 依赖则自动无缝回退至 `llama-server` 原生界面。

---

## 环境准备与使用

### 1. 下载 `llama.cpp` 预编译二进制包
前往 [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) 下载对应你显卡（如 CUDA / Vulkan / CPU）的 Windows 预编译压缩包，将其中的 `llama-server.exe` 及相关 `.dll` 文件解压到本项目根目录（与 `qidong.bat` 同级）。

### 2. 安装 Python 依赖（可选，用于开启 Web 中枢与在线角色编辑）
需要 Python 3.9+（核心启动器、显存优化与命令行角色管理仅依赖 Python 标准库；安装以下依赖可启用完整 `server_core.py` 中枢与 Web 端在线编辑）：

```bash
pip install -r requirements.txt
```

### 3. 放入模型或配置外部目录
- 将 `.gguf` 模型文件放入 `models/` 文件夹；
- 或编辑 `model_dirs.txt`，每行填写一个存放 GGUF 模型的文件夹绝对路径。

### 4. 一键启动
双击运行 `qidong.bat`，按照交互式菜单依次选择：
1. 模型
2. 显存/内存腾退优化模式
3. 运行策略（自动计算 GPU 层数与上下文）
4. 角色设定（支持预设 / 原生默认 `[N]` / 临时自定义 `[E]` / 管理中心 `[M]`）
5. 单次回复长度限制

启动完成后，浏览器打开 `http://127.0.0.1:8080`（或控制台显示的局域网/移动端地址）即可开始使用。

---

## 目录结构

```text
├── qidong.bat               # Windows 交互式主启动脚本 (GBK 编码)
├── model_manager.py         # 多目录 GGUF 扫描、架构识别与显存/内存动态策略计算
├── memory_optimizer.py      # 内存工作集压缩、CUDA 显存脉冲与壁纸守护恢复
├── role_manager.py          # 角色设定管理、Jinja 模板安全同步与 Web 角色浮窗注入
├── server_core.py           # FastAPI Web/API 中枢、角色 CRUD API、移动端 UI 与反向代理
├── db_manager.py            # SQLite WAL 会话与一次性分享链接管理
├── network_helper.py        # 局域网 / Tailscale 地址检测
├── thinking_parser.py       # <think> 思考链解析
├── model_dirs.txt           # 外部多磁盘模型路径配置
├── role_setting.txt         # 角色提示词预设文件
├── _active_template.jinja   # Qwen/ChatML 防冲突对话模板
├── requirements.txt         # Python 依赖清单
├── models/                  # 本地模型存放目录
└── web/                     # Web UI 静态资源
```

## License

MIT License. See [LICENSE](LICENSE) for details.
