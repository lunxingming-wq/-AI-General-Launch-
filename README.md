# -AI-General-Launch-
基于cudart-llama-bin-win-cuda-13.3-x64，所建立的通用启动，可以启动大部分语言模型，理论上cudart-llama-bin-win-cuda-13.3-x64兼容的它都兼容，同时还有一些准备的运行模式和AI提示词
# qidong — llama.cpp Windows 智能启动中心

一个开箱即用的 **Windows 本地大模型（GGUF / llama.cpp）启动与资源调度工具**。
双击 `qidong.bat`，按菜单选模型、选优化、选策略、选角色，即可一键拉起推理服务与 Web 界面。

---

## 功能一览

| 模块 | 功能 |
| :--- | :--- |
| 模型管理 | 扫描 `models/` 与 `model_dirs.txt` 中配置的任意目录（跨盘免复制），显示 `[本地]` / `[D盘]` 等来源标签；解析 GGUF 层数与架构并缓存；自动挂载同目录 `mmproj` 视觉组件 |
| 显存/内存腾退 | 4 档优化：挂起 Wallpaper Engine、压缩后台进程工作集、CUDA 显存脉冲、可选清理高占用后台进程 |
| 壁纸守护恢复 | 独立后台守护进程：正常退出、`Ctrl+C`、直接关闭窗口，均自动恢复壁纸 |
| 动态策略计算 | 每次启动实时读取剩余显存/内存，自动计算 `-ngl` 层数、KV 量化与 `-c` 上下文，**不是固定值** |
| 5 种运行策略 | 全显存加速 / 显存装模型+内存装上下文(`-nkvo`) / 均衡共享 / 自定义显存上限 / 纯内存 |
| 对话模板自适应 | Qwen 系列使用自带 Jinja 模板；其他架构（Gemma / Llama / Mistral / DeepSeek 等）自动使用 GGUF 内置模板 |
| 角色管理 | 命令行与网页双端：新建 / 编辑 / 删除 / 搜索 / 展开全文 / 热切换 / 原生无角色模式 / 临时角色（可转存永久） |
| Web 中枢 | 桌面页 `/`、移动端 `/mobile`、OpenAI 兼容接口 `/v1`、SQLite 会话持久化、阅后即焚分享链接、自动显示局域网 / Tailscale 地址 |

---

## 环境要求

- Windows 10 / 11
- NVIDIA 显卡（CPU 模式也可运行），驱动需支持 CUDA 13.x
- Python 3.9+（可选，见下方说明）

> 仅用 Python 标准库即可运行启动器、显存优化与命令行角色管理；
> 安装 `requirements.txt` 后才会启用完整的 Web 中枢（持久化会话、网页端在线角色编辑）。未安装时自动降级为 `llama-server` 原生界面。

---

## 安装步骤

### 1. 下载 llama.cpp 预编译包（本仓库不含二进制）

前往 [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases)，下载 Windows CUDA 版：

| 文件 | 说明 |
| :--- | :--- |
| `llama-bXXXX-bin-win-cuda-13.3-x64.zip` | 推理引擎本体（含 `llama-server.exe` 与 `ggml*.dll`） |
| `cudart-llama-bin-win-cuda-13.3-x64.zip` | CUDA 13.3 运行时（无需单独安装 CUDA Toolkit） |

**放置方式：**

```text
your-folder/
├── qidong.bat
├── llama-server.exe            <- 引擎包内所有文件解压到此处（与 qidong.bat 同级）
├── ggml*.dll / llama*.dll ...
└── cudart-llama-bin-win-cuda-13.3-x64/   <- cudart 包解压成此文件夹
    ├── cudart64_13.dll
    ├── cublas64_13.dll
    └── cublasLt64_13.dll
```

`qidong.bat` 启动时会自动把该 `cudart` 文件夹加入 `PATH`；若你已自行配置好 CUDA 环境，可不放。

**作者实测环境（供参考）：**

| 组件 | 版本 |
| :--- | :--- |
| `llama-server.exe` | `0.7.0-dev (build 11935, commit 7ecb57f7a)`，Clang 20.1.8 x86_64 |
| `cudart64_13.dll` | 6.14.11.13030 |
| `cublas64_13.dll` / `cublasLt64_13.dll` | 6.14.11.1351 |

引擎包与 cudart 包请保持同为 `cuda-13.3` 版本，不要混用不同 CUDA 大版本。
使用其他 CUDA 版本（如 12.x）的包时，同步替换 `cudart` 文件夹名并修改 `qidong.bat` 中对应路径即可。

### 2. 安装 Python 依赖（可选）

```bash
pip install -r requirements.txt
```

### 3. 放入模型

- 把 `.gguf` 文件放进 `models/`；
- 或编辑 `model_dirs.txt`，每行写一个模型目录的绝对路径（`#` 开头为注释）。

---

## 使用方法

双击 `qidong.bat`，依次完成 5 步选择：

1. **选模型**：输入序号，直接回车默认 `[1]`；`0` 退出。
2. **选优化模式**
   - `[1]` 极速深度腾退（推荐）：挂起壁纸 + 清工作集 + CUDA 显存脉冲
   - `[2]` 极限深挖：在 1 基础上关闭非核心高占用进程
   - `[3]` 温和：只清内存
   - `[4]` 不优化
   - `0` 返回上一步
3. **选运行策略**：确认后会显示计算出的层数、上下文、显存占用，回车确认。
   - 小模型追求速度 → 全显存加速
   - 大模型 / 要长上下文 → 显存装模型 + 内存装上下文
   - 要同时运行游戏或绘图软件 → 均衡共享 / 自定义显存上限
4. **选角色**
   - 输入编号：使用该预设角色
   - `N`：原生默认（不注入任何角色设定，适合写代码 / 翻译 / 英文）
   - `E`：临时自定义（粘贴提示词，**空行回车结束，输入 `0` 取消**，可顺便存为永久角色）
   - `M`：管理中心（`A` 新增 / `E` 编辑 / `V` 查看全文 / `D` 删除 / `O` 记事本打开）
   - 直接回车：沿用当前激活的角色
5. **选单次回复长度**：1500 / 3000 / 7500 / 12000 Tokens 或不限制，也可直接输入数字。

启动完成后访问：

| 入口 | 地址 |
| :--- | :--- |
| 桌面网页 | `http://127.0.0.1:8080/` |
| 手机 / 平板 | `http://<局域网IP>:8080/mobile`（控制台会打印实际地址） |
| OpenAI 兼容接口 | `http://127.0.0.1:8080/v1` |

模型结束后菜单会提供：`[1]` 重启当前配置 / `[2]` 重选角色 / `[3]` 重选策略 / `[0]` 返回模型列表。

### 网页端角色管理

点击页面右上角的角色按钮：可搜索、展开全文、新建、编辑、删除、切换角色，或切到「原生默认模式」。
保存后在下一条消息立即生效，并写回 `role_setting.txt`。

### 角色文件格式

`role_setting.txt` 中每个角色以独占一行的 `[角色名]` 开头，下方为提示词（支持多行）。
正文里如需写方括号，请在行首保留空格缩进，避免被识别为新角色标题。

---

## 目录结构

```text
├── qidong.bat               # 主启动脚本（GBK 编码，请勿用 UTF-8 保存）
├── model_manager.py         # 多目录扫描 / 架构识别 / 显存内存策略计算
├── memory_optimizer.py      # 显存内存腾退 / 壁纸守护恢复
├── role_manager.py          # 角色管理 / 模板同步 / 网页浮窗注入
├── server_core.py           # Web 与 API 中枢 / 角色接口 / 移动端页面 / 反向代理
├── db_manager.py            # SQLite 会话与分享链接
├── network_helper.py        # 局域网 / Tailscale 地址检测
├── thinking_parser.py       # <think> 思考链解析
├── model_dirs.txt           # 外部模型目录配置
├── role_setting.txt         # 角色提示词
├── _active_template.jinja   # Qwen 系列对话模板
├── requirements.txt
├── models/                  # 模型目录
└── web/                     # Web UI 静态资源
```

## 常见问题

- **提示未找到 llama-server.exe**：引擎包没解压到与 `qidong.bat` 同级目录。
- **启动报缺少 `cudart64_13.dll` / `cublas64_13.dll`**：未放置 cudart 文件夹，或引擎与 cudart 的 CUDA 大版本不一致。
- **中文乱码**：`qidong.bat` 必须保持 GBK 编码。
- **网页无法保存角色**：未安装 `requirements.txt` 依赖，`server_core.py` 没有启动。
- **手机打不开**：确认与电脑在同一局域网，并放行 Windows 防火墙的 8080 端口。

## License

MIT License，详见 [LICENSE](LICENSE)。
`web/_app/` 下的静态界面来源于 llama.cpp（MIT）。
