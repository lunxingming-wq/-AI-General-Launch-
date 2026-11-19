# -*- coding: utf-8 -*-
"""
角色设定与提示词管理模块 (Role & Persona Manager)
- 支持命令行交互式增/删/改/查 + 记事本安全编辑（兼容 Win11 多标签记事本）
- 支持临时自定义角色（空行回车结束，支持一键转存永久）与原生默认（无角色）模式
- 与 _active_template.jinja、server_core.py (/api/roles) 及 Web UI 人物卡浮窗实时联动
"""
import os
import sys
import re
import json
import time
import subprocess

# ---------------------------------------------------------------------------
# 动态获取控制台实际代码页，实现对应编码输出
# 支持传统 cmd.exe (chcp 936/GBK) 和 Windows Terminal (chcp 65001/UTF-8)
# ---------------------------------------------------------------------------
def _detect_console_encoding() -> str:
    try:
        import ctypes
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        if cp == 65001:
            return 'utf-8'
        if cp in (936, 54936):  # GBK / GB18030
            return 'gbk'
        if cp > 0:
            return f'cp{cp}'
    except Exception:
        pass
    try:
        import ctypes
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
    """向 bat 控制台输出文本，自动匹配控制台代码页。"""
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

TXT_PATH = os.path.join(TARGET_DIR, "role_setting.txt")
ACTIVE_TEMPLATE_PATH = os.path.join(TARGET_DIR, "_active_template.jinja")
ACTIVE_NAME_PATH = os.path.join(TARGET_DIR, "_active_role_name.txt")
ACTIVE_STATE_PATH = os.path.join(TARGET_DIR, "_active_role_state.json")
WEB_INDEX_PATH = os.path.join(TARGET_DIR, "web", "index.html")

MODE_PRESET = "preset"
MODE_NONE = "none"
MODE_TEMP = "temp"

NONE_TOKEN = "__NONE__"
TEMP_TOKEN = "__TEMP__"
NONE_DISPLAY = "原生默认 (无角色)"
TEMP_DISPLAY = "临时自定义角色"

# 仅匹配行首第 0 列的 [角色名] / 【角色名】 / === 角色名 ===，避免正文中缩进或行内方括号被误切分
HEADER_RE = re.compile(r'^(?:\[|【|===\s*)([^\[\]【】\r\n]{1,80})(?:\]|】|\s*===)\s*$')

ROLE_FILE_HEADER = (
    "# ============================================================\n"
    "# 角色设定配置文件 (role_setting.txt)\n"
    "# 格式说明：每个角色以单独一行 [角色名] 开头，下方填写对应提示词（支持多行）。\n"
    "# 注意：正文内部若需使用方括号，请在行首保留空格缩进以免被识别为新角色标题。\n"
    "# ============================================================\n\n"
)


def read_text_file(filepath: str) -> str:
    if not os.path.exists(filepath):
        return ""
    with open(filepath, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def parse_roles(content: str):
    roles = []
    lines = content.splitlines()
    current_name = None
    current_lines = []

    for line in lines:
        # 跳过第一个角色之前的注释行与空行
        if current_name is None:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

        m = HEADER_RE.match(line)
        if m:
            if current_name is not None:
                prompt = "\n".join(current_lines).strip()
                if current_name or prompt:
                    roles.append((current_name, prompt))
            current_name = m.group(1).strip()
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(line)

    if current_name is not None:
        prompt = "\n".join(current_lines).strip()
        if current_name or prompt:
            roles.append((current_name, prompt))

    return roles


def list_roles():
    return parse_roles(read_text_file(TXT_PATH))


def _sanitize_prompt_for_txt(prompt: str) -> str:
    """防止提示词正文某一行恰好撞上行首 [xxx] 正则而被拆分成新角色"""
    safe_lines = []
    for line in (prompt or "").splitlines():
        if HEADER_RE.match(line):
            safe_lines.append("  " + line)
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines).strip()


def save_roles_to_file(roles_list):
    """将角色列表安全写入 role_setting.txt"""
    blocks = []
    for name, prompt in roles_list:
        clean_name = name.replace("[", "（").replace("]", "）").replace("\n", " ").strip()
        clean_prompt = _sanitize_prompt_for_txt(prompt)
        blocks.append(f"[{clean_name}]\n{clean_prompt}\n")
    content = ROLE_FILE_HEADER + "\n".join(blocks)
    with open(TXT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def get_state() -> dict:
    """读取当前激活角色状态（兼容旧版 _active_role_name.txt）"""
    state = None
    if os.path.exists(ACTIVE_STATE_PATH):
        try:
            with open(ACTIVE_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = None

    roles = list_roles()
    if not isinstance(state, dict):
        legacy_name = read_text_file(ACTIVE_NAME_PATH).strip() if os.path.exists(ACTIVE_NAME_PATH) else ""
        if legacy_name in (NONE_TOKEN, NONE_DISPLAY):
            state = {"mode": MODE_NONE, "active_role": NONE_TOKEN, "temp_prompt": "", "launch_id": str(time.time())}
        elif legacy_name in (TEMP_TOKEN, TEMP_DISPLAY):
            state = {"mode": MODE_TEMP, "active_role": TEMP_TOKEN, "temp_prompt": "", "launch_id": str(time.time())}
        else:
            default_name = legacy_name if any(r[0] == legacy_name for r in roles) else (roles[0][0] if roles else NONE_TOKEN)
            mode = MODE_PRESET if (roles and default_name != NONE_TOKEN) else MODE_NONE
            state = {"mode": mode, "active_role": default_name, "temp_prompt": "", "launch_id": str(time.time())}

    # 校验 preset 角色是否仍存在
    if state.get("mode") == MODE_PRESET:
        if not roles:
            state["mode"] = MODE_NONE
            state["active_role"] = NONE_TOKEN
        elif not any(r[0] == state.get("active_role") for r in roles):
            state["active_role"] = roles[0][0]

    if not state.get("launch_id"):
        state["launch_id"] = str(time.time())

    return state


def save_state(state: dict) -> None:
    try:
        with open(ACTIVE_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    try:
        mode = state.get("mode", MODE_PRESET)
        if mode == MODE_NONE:
            display = NONE_DISPLAY
        elif mode == MODE_TEMP:
            display = TEMP_DISPLAY
        else:
            display = state.get("active_role", "") or NONE_DISPLAY
        with open(ACTIVE_NAME_PATH, "w", encoding="utf-8") as f:
            f.write(display)
    except Exception:
        pass


def get_active_prompt_info():
    """返回 (mode, display_name, prompt)"""
    state = get_state()
    mode = state.get("mode", MODE_PRESET)
    if mode == MODE_NONE:
        return MODE_NONE, NONE_DISPLAY, ""
    if mode == MODE_TEMP:
        return MODE_TEMP, TEMP_DISPLAY, state.get("temp_prompt", "")

    roles = list_roles()
    active_name = state.get("active_role", "")
    for name, prompt in roles:
        if name == active_name:
            return MODE_PRESET, name, prompt
    if roles:
        return MODE_PRESET, roles[0][0], roles[0][1]
    return MODE_NONE, NONE_DISPLAY, ""


def get_current_active_info():
    """兼容旧接口：返回 (active_name, active_prompt)"""
    _, name, prompt = get_active_prompt_info()
    return name, prompt


def get_roles_payload() -> dict:
    """生成前后端统一的角色状态数据结构"""
    roles = list_roles()
    state = get_state()
    mode, display_name, _ = get_active_prompt_info()
    return {
        "mode": mode,
        "active_role": state.get("active_role", NONE_TOKEN),
        "active_display": display_name,
        "temp_prompt": state.get("temp_prompt", "") if mode == MODE_TEMP else "",
        "launch_id": str(state.get("launch_id", "")),
        "roles": [{"id": idx, "name": name, "prompt": prompt} for idx, (name, prompt) in enumerate(roles, 1)]
    }


def update_jinja_identity(role_name: str, prompt: str) -> None:
    """使用 json.dumps 安全写入 _active_template.jinja，完整保留多行换行与英文双引号"""
    try:
        if not os.path.exists(ACTIVE_TEMPLATE_PATH):
            return
        with open(ACTIVE_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        encoded_name = json.dumps(role_name or "", ensure_ascii=False)
        encoded_prompt = json.dumps(prompt or "", ensure_ascii=False)

        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith('{%- set persona_name'):
                new_lines.append(f'{{%- set persona_name = {encoded_name} %}}\n')
            elif stripped.startswith('{%- set system_identity'):
                new_lines.append(f'{{%- set system_identity = {encoded_prompt} %}}\n')
            elif stripped.startswith('{%- set qwythos_identity'):
                new_lines.append(f'{{%- set qwythos_identity = {encoded_prompt} %}}\n')
            else:
                new_lines.append(line)

        with open(ACTIVE_TEMPLATE_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"[WARNING] update_jinja_identity failed: {e}", file=sys.stderr)


def export_roles_json():
    try:
        data = get_roles_payload()
        web_dir = os.path.join(TARGET_DIR, "web")
        os.makedirs(web_dir, exist_ok=True)
        with open(os.path.join(web_dir, "roles.json"), "wb") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    except Exception as e:
        print("export_roles_json error:", e, file=sys.stderr)


def update_web_index():
    """向 web/index.html 注入支持实时同步与在线增删改查的人物卡浮窗"""
    try:
        if not os.path.exists(WEB_INDEX_PATH):
            return

        data = get_roles_payload()
        roles_json_str = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

        with open(WEB_INDEX_PATH, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()

        if "<!-- ROLE_HOT_SWITCHER_START -->" in html and "<!-- ROLE_HOT_SWITCHER_END -->" in html:
            start_idx = html.find("<!-- ROLE_HOT_SWITCHER_START -->")
            end_idx = html.find("<!-- ROLE_HOT_SWITCHER_END -->") + len("<!-- ROLE_HOT_SWITCHER_END -->")
            html = html[:start_idx] + html[end_idx:]

        injection = f"""<!-- ROLE_HOT_SWITCHER_START -->
<style id="native-hot-switcher-styles">
  #role-switcher-btn {{
    position: fixed;
    top: 10px;
    right: 56px;
    z-index: 9999;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 13px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    background: rgba(24, 24, 30, 0.9);
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 0.16);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
    transition: all 0.2s ease;
    user-select: none;
  }}
  #role-switcher-btn:hover {{
    background: rgba(45, 45, 58, 0.96);
    border-color: rgba(129, 140, 248, 0.55);
    transform: translateY(-1px);
  }}
  #role-switcher-btn:active {{
    transform: scale(0.96);
  }}
  #role-modal-overlay {{
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.68);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    z-index: 10000;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }}
  #role-modal-overlay.active {{
    display: flex;
  }}
  #role-modal {{
    width: 100%;
    max-width: 540px;
    max-height: 86vh;
    background: #16161c;
    color: #f1f5f9;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 16px;
    box-shadow: 0 20px 48px rgba(0, 0, 0, 0.65);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    animation: roleModalPop 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  @keyframes roleModalPop {{
    from {{ opacity: 0; transform: scale(0.95) translateY(12px); }}
    to {{ opacity: 1; transform: scale(1) translateY(0); }}
  }}
  .role-modal-header {{
    padding: 14px 18px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
  }}
  .role-modal-header h3 {{
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .role-header-actions {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .role-btn-primary {{
    background: #6366f1;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s;
  }}
  .role-btn-primary:hover {{ background: #4f46e5; }}
  .role-btn-secondary {{
    background: rgba(255, 255, 255, 0.08);
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12.5px;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .role-btn-secondary:hover {{ background: rgba(255, 255, 255, 0.15); }}
  .role-modal-close {{
    background: transparent;
    border: none;
    color: #94a3b8;
    font-size: 22px;
    cursor: pointer;
    padding: 2px 8px;
    border-radius: 6px;
    line-height: 1;
  }}
  .role-modal-close:hover {{
    color: #fff;
    background: rgba(255, 255, 255, 0.1);
  }}
  .role-search-wrap {{
    padding: 10px 14px 0 14px;
    display: none;
  }}
  .role-search-wrap.visible {{ display: block; }}
  .role-search-input {{
    width: 100%;
    box-sizing: border-box;
    padding: 8px 12px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: #f8fafc;
    font-size: 13px;
    outline: none;
  }}
  .role-search-input:focus {{ border-color: #6366f1; }}
  .role-list {{
    padding: 12px 14px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex: 1;
  }}
  .role-item {{
    padding: 12px 14px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    cursor: pointer;
    transition: all 0.15s ease;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .role-item:hover {{
    background: rgba(255, 255, 255, 0.075);
    border-color: rgba(255, 255, 255, 0.22);
  }}
  .role-item.active {{
    background: rgba(99, 102, 241, 0.18);
    border-color: rgba(99, 102, 241, 0.6);
  }}
  .role-item-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }}
  .role-item-title-wrap {{
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }}
  .role-name {{
    font-weight: 600;
    font-size: 14px;
    color: #f8fafc;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .role-badge {{
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 4px;
    background: #6366f1;
    color: #fff;
    display: none;
    font-weight: 500;
    flex-shrink: 0;
  }}
  .role-item.active .role-badge {{ display: inline-block; }}
  .role-item-ops {{
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }}
  .role-op-btn {{
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #cbd5e1;
    font-size: 11.5px;
    padding: 3px 8px;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .role-op-btn:hover {{ background: rgba(255, 255, 255, 0.15); color: #fff; }}
  .role-op-btn.danger:hover {{ background: rgba(239, 68, 68, 0.3); border-color: rgba(239, 68, 68, 0.6); color: #fecaca; }}
  .role-op-btn.confirm-del {{ background: #dc2626; border-color: #ef4444; color: #fff; }}
  .role-prompt-preview {{
    font-size: 12.5px;
    color: #94a3b8;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .role-prompt-preview.expanded {{
    display: block;
    -webkit-line-clamp: unset;
    color: #cbd5e1;
  }}
  .role-expand-link {{
    align-self: flex-start;
    background: none;
    border: none;
    color: #818cf8;
    font-size: 11.5px;
    padding: 0;
    cursor: pointer;
  }}
  .role-expand-link:hover {{ text-decoration: underline; }}
  .role-editor-panel {{
    padding: 16px 18px;
    display: none;
    flex-direction: column;
    gap: 12px;
    overflow-y: auto;
  }}
  .role-editor-panel.active {{ display: flex; }}
  .role-field label {{
    display: flex;
    justify-content: space-between;
    font-size: 12.5px;
    color: #cbd5e1;
    margin-bottom: 6px;
    font-weight: 500;
  }}
  .role-field input, .role-field textarea {{
    width: 100%;
    box-sizing: border-box;
    background: rgba(15, 23, 42, 0.7);
    color: #f8fafc;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 13.5px;
    font-family: inherit;
    outline: none;
    line-height: 1.55;
  }}
  .role-field textarea {{
    resize: vertical;
    min-height: 160px;
  }}
  .role-field input:focus, .role-field textarea:focus {{
    border-color: #6366f1;
  }}
  .role-editor-actions {{
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 4px;
  }}
  .role-modal-footer {{
    padding: 10px 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    font-size: 11.5px;
    color: #94a3b8;
    background: rgba(0, 0, 0, 0.2);
  }}
  #role-toast {{
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%) translateY(24px);
    background: rgba(15, 23, 42, 0.96);
    color: #f8fafc;
    padding: 10px 22px;
    border-radius: 24px;
    font-size: 13px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.5);
    opacity: 0;
    pointer-events: none;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    z-index: 10001;
  }}
  #role-toast.show {{
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }}
  details summary, .think-header, .reasoning-header, summary {{
    cursor: pointer !important;
    touch-action: manipulation !important;
    -webkit-tap-highlight-color: rgba(255, 255, 255, 0.12) !important;
    user-select: none !important;
  }}
  @media (max-width: 640px) {{
    #role-switcher-btn {{
      top: 8px;
      right: 48px;
      padding: 5px 10px;
      font-size: 12px;
    }}
  }}
</style>

<div id="role-switcher-btn" title="点击管理或切换人物卡设定">
  <span id="role-btn-icon">🎭</span>
  <span id="role-btn-name">人物卡</span>
</div>

<div id="role-modal-overlay">
  <div id="role-modal">
    <div class="role-modal-header">
      <h3 id="role-modal-title"><span>🎭</span> 人物卡管理与热切换</h3>
      <div class="role-header-actions">
        <button class="role-btn-primary" id="role-add-btn" type="button">+ 新建角色</button>
        <button class="role-btn-secondary" id="role-back-btn" type="button" style="display:none;">← 返回列表</button>
        <button class="role-modal-close" id="role-modal-close-btn" type="button">&times;</button>
      </div>
    </div>

    <div class="role-search-wrap" id="role-search-wrap">
      <input class="role-search-input" id="role-search-input" type="text" placeholder="搜索角色名称或提示词关键词..." />
    </div>

    <div class="role-list" id="role-list-container"></div>

    <div class="role-editor-panel" id="role-editor-panel">
      <div class="role-field">
        <label for="role-edit-name"><span>角色名称</span></label>
        <input id="role-edit-name" type="text" maxlength="60" placeholder="例如：编程专家 / 创意写作助手" />
      </div>
      <div class="role-field">
        <label for="role-edit-prompt"><span>系统提示词 (System Prompt，支持多行)</span><span id="role-char-count">0 字</span></label>
        <textarea id="role-edit-prompt" placeholder="输入该角色的身份、风格与回复规范..."></textarea>
      </div>
      <div class="role-editor-actions">
        <button class="role-btn-secondary" id="role-edit-cancel-btn" type="button">取消</button>
        <button class="role-btn-primary" id="role-edit-save-btn" type="button">保存并立即生效</button>
      </div>
    </div>

    <div class="role-modal-footer" id="role-modal-footer">
      切换或编辑保存后，将在下一条消息立即生效（不影响已有历史对话）。
    </div>
  </div>
</div>

<div id="role-toast"></div>

<script>
(function() {{
  const EMBEDDED_DATA = {roles_json_str};
  const STORAGE_KEY_STATE = "llama_active_role_state_v2";
  const STORAGE_KEY_LAUNCH = "llama_role_launch_id";

  let state = {{
    mode: EMBEDDED_DATA.mode || "preset",
    active_role: EMBEDDED_DATA.active_role || "",
    temp_prompt: EMBEDDED_DATA.temp_prompt || "",
    launch_id: String(EMBEDDED_DATA.launch_id || ""),
    roles: EMBEDDED_DATA.roles || []
  }};
  let apiAvailable = false;
  let editingRoleId = null; // null = creating new, number = editing existing, "TEMP_SAVE" = saving temp role
  let pendingDeleteId = null;
  let searchKeyword = "";

  const btn = document.getElementById("role-switcher-btn");
  const btnIcon = document.getElementById("role-btn-icon");
  const btnName = document.getElementById("role-btn-name");
  const overlay = document.getElementById("role-modal-overlay");
  const closeBtn = document.getElementById("role-modal-close-btn");
  const addBtn = document.getElementById("role-add-btn");
  const backBtn = document.getElementById("role-back-btn");
  const modalTitle = document.getElementById("role-modal-title");
  const searchWrap = document.getElementById("role-search-wrap");
  const searchInput = document.getElementById("role-search-input");
  const listContainer = document.getElementById("role-list-container");
  const editorPanel = document.getElementById("role-editor-panel");
  const editNameInput = document.getElementById("role-edit-name");
  const editPromptInput = document.getElementById("role-edit-prompt");
  const charCountSpan = document.getElementById("role-char-count");
  const editCancelBtn = document.getElementById("role-edit-cancel-btn");
  const editSaveBtn = document.getElementById("role-edit-save-btn");
  const toast = document.getElementById("role-toast");

  function showToast(msg) {{
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(window.__roleToastTimer);
    window.__roleToastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
  }}

  function getActivePrompt() {{
    if (state.mode === "none") return "";
    if (state.mode === "temp") return state.temp_prompt || "";
    const found = state.roles.find(r => r.name === state.active_role) || state.roles[0];
    return found ? found.prompt : "";
  }}

  function getActiveDisplayName() {{
    if (state.mode === "none") return "原生默认";
    if (state.mode === "temp") return "临时角色";
    const found = state.roles.find(r => r.name === state.active_role) || state.roles[0];
    return found ? found.name : "原生默认";
  }}

  function syncWindowAndButton() {{
    window.__active_role_mode = state.mode;
    window.__active_role_prompt = getActivePrompt();
    const disp = getActiveDisplayName();
    window.__active_role_name = disp;

    if (state.mode === "none") {{
      btnIcon.textContent = "⚪";
      btnName.textContent = "原生默认";
    }} else if (state.mode === "temp") {{
      btnIcon.textContent = "⚡";
      btnName.textContent = "临时角色";
    }} else {{
      btnIcon.textContent = "🎭";
      let shortName = disp.split(" ")[0].replace(/[\\(（].*[\\)）]/, "").trim() || disp;
      if (shortName.length > 6) shortName = shortName.slice(0, 5) + "..";
      btnName.textContent = shortName;
    }}
    try {{
      localStorage.setItem(STORAGE_KEY_STATE, JSON.stringify({{
        mode: state.mode,
        active_role: state.active_role,
        temp_prompt: state.temp_prompt
      }}));
      if (state.launch_id) localStorage.setItem(STORAGE_KEY_LAUNCH, state.launch_id);
    }} catch (e) {{}}
  }}

  async function syncActiveToServer(payload) {{
    if (!apiAvailable) return;
    try {{
      await fetch("/api/roles/active", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload)
      }});
    }} catch (e) {{}}
  }}

  function selectNone(notify = true) {{
    state.mode = "none";
    state.active_role = "__NONE__";
    syncWindowAndButton();
    syncActiveToServer({{ mode: "none" }});
    renderRolesList();
    if (notify) showToast("已切换至「原生默认模式」（不注入角色设定）");
  }}

  function selectTemp(notify = true) {{
    state.mode = "temp";
    state.active_role = "__TEMP__";
    syncWindowAndButton();
    syncActiveToServer({{ mode: "temp", temp_prompt: state.temp_prompt }});
    renderRolesList();
    if (notify) showToast("已切换至「临时自定义角色」");
  }}

  function selectPreset(role, notify = true) {{
    state.mode = "preset";
    state.active_role = role.name;
    syncWindowAndButton();
    syncActiveToServer({{ mode: "preset", role_name: role.name }});
    renderRolesList();
    if (notify) showToast("已切换至人物卡：「" + role.name + "」");
  }}

  function openListView() {{
    editingRoleId = null;
    pendingDeleteId = null;
    modalTitle.innerHTML = '<span>🎭</span> 人物卡管理与热切换';
    listContainer.style.display = "flex";
    editorPanel.classList.remove("active");
    addBtn.style.display = "inline-block";
    backBtn.style.display = "none";
    searchWrap.classList.toggle("visible", state.roles.length > 5);
    renderRolesList();
  }}

  function openEditorView(roleOrNull, isTempSave = false) {{
    if (!apiAvailable) {{
      showToast("当前为原生回退模式，请确保 server_core.py 运行以在线保存角色");
      return;
    }}
    if (isTempSave) {{
      editingRoleId = "TEMP_SAVE";
      modalTitle.innerHTML = '<span>💾</span> 保存临时角色为永久预设';
      editNameInput.value = "";
      editPromptInput.value = state.temp_prompt || "";
    }} else if (roleOrNull) {{
      editingRoleId = roleOrNull.id;
      modalTitle.innerHTML = '<span>✏️</span> 编辑角色设定';
      editNameInput.value = roleOrNull.name;
      editPromptInput.value = roleOrNull.prompt;
    }} else {{
      editingRoleId = null;
      modalTitle.innerHTML = '<span>➕</span> 新建角色设定';
      editNameInput.value = "";
      editPromptInput.value = "";
    }}
    charCountSpan.textContent = editPromptInput.value.length + " 字";
    listContainer.style.display = "none";
    searchWrap.classList.remove("visible");
    editorPanel.classList.add("active");
    addBtn.style.display = "none";
    backBtn.style.display = "inline-block";
    editNameInput.focus();
  }}

  async function saveEditorForm() {{
    const name = editNameInput.value.trim();
    const prompt = editPromptInput.value.trim();
    if (!name) {{
      showToast("请填写角色名称");
      editNameInput.focus();
      return;
    }}
    if (!prompt) {{
      showToast("请填写系统提示词内容");
      editPromptInput.focus();
      return;
    }}

    editSaveBtn.disabled = true;
    editSaveBtn.textContent = "保存中...";
    try {{
      let res;
      if (editingRoleId === null || editingRoleId === "TEMP_SAVE") {{
        res = await fetch("/api/roles", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ name, prompt, activate: true }})
        }});
      }} else {{
        res = await fetch("/api/roles/" + editingRoleId, {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ name, prompt, activate: true }})
        }});
      }}
      const data = await res.json();
      if (!res.ok || data.status !== "ok") {{
        showToast(data.detail || data.message || "保存失败");
      }} else {{
        applyServerData(data, true);
        openListView();
        showToast("已保存并激活角色：「" + name + "」");
      }}
    }} catch (e) {{
      showToast("保存请求失败：" + e.message);
    }} finally {{
      editSaveBtn.disabled = false;
      editSaveBtn.textContent = "保存并立即生效";
    }}
  }}

  async function deleteRoleById(roleId, roleName) {{
    if (!apiAvailable) {{
      showToast("需要 server_core.py 运行才能在线删除");
      return;
    }}
    try {{
      const res = await fetch("/api/roles/" + roleId, {{ method: "DELETE" }});
      const data = await res.json();
      if (!res.ok || data.status !== "ok") {{
        showToast(data.detail || "删除失败");
      }} else {{
        pendingDeleteId = null;
        applyServerData(data, true);
        renderRolesList();
        showToast("已删除角色：「" + roleName + "」");
      }}
    }} catch (e) {{
      showToast("删除失败：" + e.message);
    }}
  }}

  function renderRolesList() {{
    listContainer.innerHTML = "";
    const kw = searchKeyword.trim().toLowerCase();

    // 1. 内置「原生默认模式（无角色）」卡片
    if (!kw || "原生默认无角色native".includes(kw)) {{
      const noneCard = document.createElement("div");
      noneCard.className = "role-item" + (state.mode === "none" ? " active" : "");
      noneCard.innerHTML = `
        <div class="role-item-top">
          <div class="role-item-title-wrap">
            <span class="role-name">⚪ 原生默认模式（不注入角色设定）</span>
            <span class="role-badge">生效中</span>
          </div>
        </div>
        <div class="role-prompt-preview">使用模型自身原始能力直接对话，适合写代码、翻译、英文交流或纯粹模型测试。</div>
      `;
      noneCard.addEventListener("click", () => {{
        selectNone(true);
        overlay.classList.remove("active");
      }});
      listContainer.appendChild(noneCard);
    }}

    // 2. 若启动器设置了临时自定义角色，展示临时卡片
    if (state.temp_prompt && (!kw || "临时自定义角色".includes(kw) || state.temp_prompt.toLowerCase().includes(kw))) {{
      const tempCard = document.createElement("div");
      tempCard.className = "role-item" + (state.mode === "temp" ? " active" : "");

      const top = document.createElement("div");
      top.className = "role-item-top";
      top.innerHTML = `
        <div class="role-item-title-wrap">
          <span class="role-name">⚡ 临时自定义角色（本次启动）</span>
          <span class="role-badge">生效中</span>
        </div>
      `;
      if (apiAvailable) {{
        const ops = document.createElement("div");
        ops.className = "role-item-ops";
        const saveBtn = document.createElement("button");
        saveBtn.className = "role-op-btn";
        saveBtn.textContent = "💾 存为永久";
        saveBtn.addEventListener("click", (e) => {{
          e.stopPropagation();
          openEditorView(null, true);
        }});
        ops.appendChild(saveBtn);
        top.appendChild(ops);
      }}
      const preview = document.createElement("div");
      preview.className = "role-prompt-preview";
      preview.textContent = state.temp_prompt;

      tempCard.appendChild(top);
      tempCard.appendChild(preview);
      tempCard.addEventListener("click", () => {{
        selectTemp(true);
        overlay.classList.remove("active");
      }});
      listContainer.appendChild(tempCard);
    }}

    // 3. 永久角色卡片列表
    const filtered = state.roles.filter(r => !kw || r.name.toLowerCase().includes(kw) || r.prompt.toLowerCase().includes(kw));
    filtered.forEach(r => {{
      const isActive = (state.mode === "preset" && state.active_role === r.name);
      const item = document.createElement("div");
      item.className = "role-item" + (isActive ? " active" : "");

      const top = document.createElement("div");
      top.className = "role-item-top";

      const titleWrap = document.createElement("div");
      titleWrap.className = "role-item-title-wrap";
      const nameSpan = document.createElement("span");
      nameSpan.className = "role-name";
      nameSpan.textContent = r.name;
      const badge = document.createElement("span");
      badge.className = "role-badge";
      badge.textContent = "生效中";
      titleWrap.appendChild(nameSpan);
      titleWrap.appendChild(badge);
      top.appendChild(titleWrap);

      if (apiAvailable) {{
        const ops = document.createElement("div");
        ops.className = "role-item-ops";

        const editBtn = document.createElement("button");
        editBtn.className = "role-op-btn";
        editBtn.textContent = "✏️ 编辑";
        editBtn.addEventListener("click", (e) => {{
          e.stopPropagation();
          openEditorView(r, false);
        }});

        const delBtn = document.createElement("button");
        if (pendingDeleteId === r.id) {{
          delBtn.className = "role-op-btn confirm-del";
          delBtn.textContent = "确认删除?";
          delBtn.addEventListener("click", (e) => {{
            e.stopPropagation();
            deleteRoleById(r.id, r.name);
          }});
        }} else {{
          delBtn.className = "role-op-btn danger";
          delBtn.textContent = "🗑️";
          delBtn.title = "删除角色";
          delBtn.addEventListener("click", (e) => {{
            e.stopPropagation();
            pendingDeleteId = r.id;
            renderRolesList();
          }});
        }}
        ops.appendChild(editBtn);
        ops.appendChild(delBtn);
        top.appendChild(ops);
      }}

      const preview = document.createElement("div");
      preview.className = "role-prompt-preview";
      preview.textContent = r.prompt;

      item.appendChild(top);
      item.appendChild(preview);

      if (r.prompt.length > 70 || r.prompt.includes("\\n")) {{
        const expandBtn = document.createElement("button");
        expandBtn.className = "role-expand-link";
        expandBtn.textContent = "展开全文";
        expandBtn.addEventListener("click", (e) => {{
          e.stopPropagation();
          const exp = preview.classList.toggle("expanded");
          expandBtn.textContent = exp ? "收起" : "展开全文";
        }});
        item.appendChild(expandBtn);
      }}

      item.addEventListener("click", () => {{
        selectPreset(r, true);
        overlay.classList.remove("active");
      }});
      listContainer.appendChild(item);
    }});

    if (!filtered.length && kw) {{
      const empty = document.createElement("div");
      empty.style.cssText = "text-align:center;padding:24px;color:#94a3b8;font-size:13px;";
      empty.textContent = "没有找到匹配的角色设定";
      listContainer.appendChild(empty);
    }}
  }}

  function applyServerData(data, forceTrustServer = false) {{
    state.roles = data.roles || [];
    const serverLaunchId = String(data.launch_id || "");
    const savedLaunchId = localStorage.getItem(STORAGE_KEY_LAUNCH) || "";

    // 若本次是 qidong.bat 新启动（launch_id 变化）或刚在前端保存修改，始终以服务端为准，防止旧缓存覆盖新选角！
    if (forceTrustServer || !savedLaunchId || (serverLaunchId && serverLaunchId !== savedLaunchId)) {{
      state.mode = data.mode || "preset";
      state.active_role = data.active_role || (state.roles[0] ? state.roles[0].name : "__NONE__");
      state.temp_prompt = data.temp_prompt || "";
      state.launch_id = serverLaunchId;
    }} else {{
      // 同一次启动内刷新页面：优先使用当前服务端状态，若本地有切换则兼容恢复
      state.mode = data.mode || state.mode;
      state.active_role = data.active_role || state.active_role;
      state.temp_prompt = data.temp_prompt || "";
      state.launch_id = serverLaunchId;
    }}
    syncWindowAndButton();
  }}

  async function refreshFromServer(forceTrust = false) {{
    try {{
      const res = await fetch("/api/roles", {{ cache: "no-store" }});
      if (res.ok) {{
        const data = await res.json();
        if (data && data.status === "ok") {{
          apiAvailable = true;
          applyServerData(data, forceTrust);
          return true;
        }}
      }}
    }} catch (e) {{}}
    apiAvailable = false;
    applyServerData(EMBEDDED_DATA, false);
    return false;
  }}

  btn.addEventListener("click", async () => {{
    overlay.classList.add("active");
    await refreshFromServer(false);
    openListView();
  }});
  closeBtn.addEventListener("click", () => overlay.classList.remove("active"));
  addBtn.addEventListener("click", () => openEditorView(null, false));
  backBtn.addEventListener("click", openListView);
  editCancelBtn.addEventListener("click", openListView);
  editSaveBtn.addEventListener("click", saveEditorForm);
  editPromptInput.addEventListener("input", () => {{
    charCountSpan.textContent = editPromptInput.value.length + " 字";
  }});
  searchInput.addEventListener("input", () => {{
    searchKeyword = searchInput.value;
    renderRolesList();
  }});
  overlay.addEventListener("click", (e) => {{
    if (e.target === overlay) overlay.classList.remove("active");
  }});

  // Global Fetch Interceptor: 动态注入当前选定角色（或显式通知后端跳过默认角色）
  const origFetch = window.fetch;
  window.fetch = async function(...args) {{
    try {{
      const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url ? args[0].url : "");
      const opts = args[1] || {{}};

      if (url.includes("/chat/completions") || url.includes("/v1/chat/completions") || url.includes("/completion")) {{
        if (opts.body && typeof opts.body === "string") {{
          try {{
            const data = JSON.parse(opts.body);
            if (Array.isArray(data.messages)) {{
              const mode = window.__active_role_mode || "preset";
              const prompt = window.__active_role_prompt || "";

              // 添加角色模式头，便于 server_core.py 针对非 Qwen 模型精准处理
              if (opts.headers instanceof Headers) {{
                opts.headers.set("X-Llama-Role-Mode", mode);
              }} else {{
                opts.headers = Object.assign({{}}, opts.headers || {{}}, {{ "X-Llama-Role-Mode": mode }});
              }}

              if (mode === "none" || !prompt) {{
                // 原生默认模式：显式传入空 system，使 Qwen 模板抑制默认角色；非 Qwen 模型由代理剥离
                if (data.messages.length > 0 && data.messages[0].role === "system") {{
                  data.messages[0].content = "";
                }} else {{
                  data.messages.unshift({{ role: "system", content: "" }});
                }}
              }} else {{
                if (data.messages.length > 0 && data.messages[0].role === "system") {{
                  data.messages[0].content = prompt;
                }} else {{
                  data.messages.unshift({{ role: "system", content: prompt }});
                }}
              }}
              opts.body = JSON.stringify(data);
              args[1] = opts;
            }}
          }} catch (pe) {{}}
        }}
      }}
    }} catch (err) {{}}
    return origFetch.apply(this, args);
  }};

  // Mobile Thinking Chain Click / Tap Handler
  document.addEventListener("click", function(e) {{
    const summary = e.target.closest("summary");
    if (summary) {{
      const details = summary.parentElement;
      if (details && details.tagName.toLowerCase() === "details") {{
        details.classList.toggle("is-open", !details.open);
      }}
    }}
  }}, true);

  // 初始化：优先拉取服务端实时状态
  syncWindowAndButton();
  refreshFromServer(false);
}})();
</script>
<!-- ROLE_HOT_SWITCHER_END -->
"""

        if "</body>" in html:
            before_body, after_body = html.rsplit("</body>", 1)
            html = before_body.rstrip() + "\n\n" + injection + "\n</body>" + after_body
        else:
            html = html.rstrip() + "\n\n" + injection

        with open(WEB_INDEX_PATH, "wb") as f:
            f.write(html.encode("utf-8"))
    except Exception as e:
        print("update_web_index error:", e, file=sys.stderr)


def sync_all_outputs():
    """将当前激活角色同步到 Jinja 模板、web/roles.json 与 web/index.html"""
    _, name, prompt = get_active_prompt_info()
    update_jinja_identity(name, prompt)
    export_roles_json()
    update_web_index()


# ---------------------------------------------------------------------------
# 角色状态切换与 CRUD 业务方法（供 CLI 与 server_core.py REST API 共用）
# ---------------------------------------------------------------------------

def set_active_role(role_name_or_id, strict: bool = True, bump_launch: bool = True):
    roles = list_roles()
    target_name = None
    target_prompt = None

    ref = str(role_name_or_id).strip()
    if ref in (NONE_TOKEN, NONE_DISPLAY, "N", "n"):
        return set_active_none(bump_launch=bump_launch)

    if ref.isdigit():
        idx = int(ref) - 1
        if 0 <= idx < len(roles):
            target_name, target_prompt = roles[idx]
    else:
        for name, prompt in roles:
            if name == ref or name.lower() == ref.lower():
                target_name, target_prompt = name, prompt
                break

    if not target_name:
        if not strict and roles:
            target_name, target_prompt = roles[0]
        else:
            return False, f"无效的角色编号或名称：{ref}（当前共有 {len(roles)} 个角色）"

    state = get_state()
    state["mode"] = MODE_PRESET
    state["active_role"] = target_name
    state["temp_prompt"] = ""
    if bump_launch:
        state["launch_id"] = str(time.time())
    save_state(state)
    sync_all_outputs()
    return True, target_name


def set_active_none(bump_launch: bool = True):
    state = get_state()
    state["mode"] = MODE_NONE
    state["active_role"] = NONE_TOKEN
    state["temp_prompt"] = ""
    if bump_launch:
        state["launch_id"] = str(time.time())
    save_state(state)
    sync_all_outputs()
    return True, NONE_DISPLAY


def set_active_temp(prompt: str, bump_launch: bool = True):
    clean = (prompt or "").strip()
    if not clean:
        return False, "临时提示词不能为空"
    state = get_state()
    state["mode"] = MODE_TEMP
    state["active_role"] = TEMP_TOKEN
    state["temp_prompt"] = clean
    if bump_launch:
        state["launch_id"] = str(time.time())
    save_state(state)
    sync_all_outputs()
    return True, TEMP_DISPLAY


def apply_current(bump_launch: bool = True):
    state = get_state()
    if bump_launch:
        state["launch_id"] = str(time.time())
    save_state(state)
    sync_all_outputs()
    _, display_name, _ = get_active_prompt_info()
    return True, display_name


def add_role(name: str, prompt: str, activate: bool = False):
    clean_name = (name or "").replace("[", "（").replace("]", "）").replace("\n", " ").strip()
    clean_prompt = (prompt or "").strip()
    if not clean_name:
        return False, "角色名称不能为空", None
    if not clean_prompt:
        return False, "提示词内容不能为空", None

    roles = list_roles()
    if any(r[0].lower() == clean_name.lower() for r in roles):
        return False, f"已存在同名角色「{clean_name}」，请换一个名称", None

    roles.append((clean_name, clean_prompt))
    save_roles_to_file(roles)
    new_id = len(roles)
    if activate:
        set_active_role(clean_name, strict=True, bump_launch=False)
    else:
        sync_all_outputs()
    return True, clean_name, new_id


def update_role(role_id: int, new_name: str, new_prompt: str, activate: bool = False):
    roles = list_roles()
    idx = int(role_id) - 1
    if not (0 <= idx < len(roles)):
        return False, f"角色编号 {role_id} 不存在"

    clean_name = (new_name or "").replace("[", "（").replace("]", "）").replace("\n", " ").strip()
    clean_prompt = (new_prompt or "").strip()
    if not clean_name:
        return False, "角色名称不能为空"
    if not clean_prompt:
        return False, "提示词内容不能为空"

    for i, (rname, _) in enumerate(roles):
        if i != idx and rname.lower() == clean_name.lower():
            return False, f"已存在同名角色「{clean_name}」"

    old_name = roles[idx][0]
    roles[idx] = (clean_name, clean_prompt)
    save_roles_to_file(roles)

    state = get_state()
    if activate or (state.get("mode") == MODE_PRESET and state.get("active_role") == old_name):
        state["mode"] = MODE_PRESET
        state["active_role"] = clean_name
        state["temp_prompt"] = ""
        save_state(state)

    sync_all_outputs()
    return True, clean_name


def delete_role(role_id: int):
    roles = list_roles()
    idx = int(role_id) - 1
    if not (0 <= idx < len(roles)):
        return False, f"角色编号 {role_id} 不存在"

    removed_name = roles[idx][0]
    roles.pop(idx)
    save_roles_to_file(roles)

    state = get_state()
    if state.get("mode") == MODE_PRESET and state.get("active_role") == removed_name:
        if roles:
            state["active_role"] = roles[0][0]
        else:
            state["mode"] = MODE_NONE
            state["active_role"] = NONE_TOKEN
        save_state(state)

    sync_all_outputs()
    return True, removed_name


# ---------------------------------------------------------------------------
# 命令行交互式界面 (CLI UX)
# ---------------------------------------------------------------------------

def _snippet(text: str, max_len: int = 34) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= max_len else flat[:max_len] + "..."


def _read_multiline_input(allow_empty_keep: bool = False):
    """
    人性化多行输入：
    - 输入或粘贴完毕后，直接按一次空行回车即可结束（同时兼容 Ctrl+Z）
    - 第一行输入 0 并回车直接取消返回
    返回值：(cancelled: bool, text: str)
    """
    lines_in = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break

        if not lines_in:
            s = line.strip()
            if s == "0":
                return True, ""
            if s == "":
                if allow_empty_keep:
                    return False, ""
                return True, ""
            lines_in.append(line)
        else:
            if line.strip() == "":
                break
            lines_in.append(line)

    return False, "\n".join(lines_in).strip()


def list_roles_short_for_bat():
    """--list-short：输出带编号与摘要的角色列表供 bat 菜单显示"""
    roles = list_roles()
    mode, display_name, temp_prompt = get_active_prompt_info()

    if mode == MODE_NONE:
        _bat_write(f"  (当前已激活：{NONE_DISPLAY})\n\n")
    elif mode == MODE_TEMP:
        _bat_write(f"  (当前已激活：{TEMP_DISPLAY} — {_snippet(temp_prompt, 28)})\n\n")

    if not roles:
        _bat_write("  (role_setting.txt 中暂无预设角色，可按 [M] 新增或按 [N] 原生启动)\n")
        return

    for idx, (name, prompt) in enumerate(roles, 1):
        marker = " *" if (mode == MODE_PRESET and name == display_name) else ""
        preview = _snippet(prompt, 32)
        _bat_write(f" [{idx}] {name}{marker}\n")
        _bat_write(f"     └─ {preview}\n")


def apply_role_cli(role_id: str):
    ok, msg = set_active_role(role_id, strict=True, bump_launch=True)
    if ok:
        _bat_write(f"OK:{msg}\n")
        sys.exit(0)
    else:
        _bat_write(f"[提示] {msg}\n")
        sys.exit(1)


def apply_none_cli():
    ok, msg = set_active_none(bump_launch=True)
    _bat_write(f"OK:{msg}\n")
    sys.exit(0 if ok else 1)


def apply_current_cli():
    ok, msg = apply_current(bump_launch=True)
    _bat_write(f"OK:{msg}\n")
    sys.exit(0 if ok else 1)


def get_current_name_cli():
    _, display_name, _ = get_active_prompt_info()
    _bat_write(display_name + "\n")


def custom_role_cli():
    """--custom：人性化临时角色输入（空行回车结束、0 取消、可选转存永久）"""
    os.system("cls")
    _bat_write("============================================================\n")
    _bat_write("            临时输入自定义角色设定 (仅本次生效)\n")
    _bat_write("============================================================\n")
    _bat_write(" * 支持直接粘贴单行或多行提示词\n")
    _bat_write(" * 输入完成后，再按一次【回车】(输入空行) 即可完成\n")
    _bat_write(" * 直接输入 0 并回车可取消并返回上一级菜单\n")
    _bat_write("------------------------------------------------------------\n")
    _bat_write("请输入提示词内容：\n")

    cancelled, prompt = _read_multiline_input(allow_empty_keep=False)
    if cancelled or not prompt:
        _bat_write("\n[提示] 已取消临时输入，返回角色选择菜单...\n")
        time.sleep(0.8)
        sys.exit(2)

    _bat_write("\n------------------------------------------------------------\n")
    _bat_write(f"[已录入 {len(prompt)} 字] 预览：{_snippet(prompt, 48)}\n")
    _bat_write("是否顺便保存为永久角色？(直接回车=仅本次临时生效，输入角色名=永久保存)：\n")
    try:
        save_name = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        save_name = ""

    if save_name and save_name != "0":
        ok, msg, _ = add_role(save_name, prompt, activate=True)
        if ok:
            # 同步刷新 launch_id
            apply_current(bump_launch=True)
            _bat_write(f"\n[成功] 已永久保存并激活角色「{msg}」！\n")
            time.sleep(0.8)
            sys.exit(0)
        else:
            _bat_write(f"\n[提示] 永久保存失败（{msg}），已自动降级为本次临时生效。\n")

    set_active_temp(prompt, bump_launch=True)
    _bat_write("\n[成功] 临时自定义角色已生效（同步支持桌面端与移动端 Web UI）！\n")
    time.sleep(0.8)
    sys.exit(0)


def manage_roles_cli():
    """--manage：可视化命令行角色管理中心（增/删/改/查 + Win11 兼容记事本编辑）"""
    while True:
        os.system("cls")
        roles = list_roles()
        mode, active_disp, _ = get_active_prompt_info()

        _bat_write("============================================================\n")
        _bat_write("                    角色设定管理中心\n")
        _bat_write("============================================================\n")
        if not roles:
            _bat_write("  (当前暂无角色，请按 [A] 新建角色)\n")
        else:
            for idx, (name, prompt) in enumerate(roles, 1):
                mark = " *" if (mode == MODE_PRESET and name == active_disp) else ""
                _bat_write(f"  [{idx}] {name}{mark}\n")
                _bat_write(f"      └─ {_snippet(prompt, 40)}\n")

        _bat_write("------------------------------------------------------------\n")
        _bat_write("  [A] 新增角色          [E] 编辑指定角色\n")
        _bat_write("  [V] 查看角色全文      [D] 删除指定角色\n")
        _bat_write("  [O] 用记事本打开 role_setting.txt\n")
        _bat_write("  [0] 返回角色选择菜单\n")
        _bat_write("============================================================\n")
        try:
            op = input("请选择操作: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            break

        if op == "0" or op == "":
            break

        elif op == "A":
            _bat_write("\n--- 新增角色 (输入 0 取消) ---\n")
            try:
                name = input("角色名称: ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not name or name == "0":
                continue
            _bat_write("请输入提示词内容（输入完成后按空行回车结束，输入 0 取消）：\n")
            cancelled, prompt = _read_multiline_input(allow_empty_keep=False)
            if cancelled or not prompt:
                _bat_write("[提示] 已取消新增。\n")
                time.sleep(0.8)
                continue
            ok, msg, _ = add_role(name, prompt, activate=False)
            _bat_write(f"[{'成功' if ok else '错误'}] {'已新增角色「' + msg + '」' if ok else msg}\n")
            time.sleep(1.0)

        elif op == "V":
            if not roles:
                continue
            try:
                idx_s = input(f"\n请输入要查看的角色编号 (1-{len(roles)}, 0取消): ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not idx_s.isdigit() or not (1 <= int(idx_s) <= len(roles)):
                continue
            rname, rprompt = roles[int(idx_s) - 1]
            os.system("cls")
            _bat_write("============================================================\n")
            _bat_write(f" 角色名称：{rname}\n")
            _bat_write("------------------------------------------------------------\n")
            _bat_write(rprompt + "\n")
            _bat_write("============================================================\n")
            try:
                input("按回车键返回管理菜单...")
            except (EOFError, KeyboardInterrupt):
                pass

        elif op == "E":
            if not roles:
                continue
            try:
                idx_s = input(f"\n请输入要编辑的角色编号 (1-{len(roles)}, 0取消): ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not idx_s.isdigit() or not (1 <= int(idx_s) <= len(roles)):
                continue
            rid = int(idx_s)
            old_name, old_prompt = roles[rid - 1]
            _bat_write(f"\n--- 编辑角色 [{rid}] {old_name} ---\n")
            _bat_write(f"当前提示词：\n{old_prompt}\n")
            _bat_write("------------------------------------------------------------\n")
            try:
                new_name = input(f"新角色名称 (直接回车保持「{old_name}」): ").strip() or old_name
            except (EOFError, KeyboardInterrupt):
                continue
            _bat_write("请输入新提示词（直接回车保持原内容；输入新内容后按空行回车结束，0取消）：\n")
            cancelled, new_prompt = _read_multiline_input(allow_empty_keep=True)
            if cancelled:
                _bat_write("[提示] 已取消编辑。\n")
                time.sleep(0.8)
                continue
            final_prompt = new_prompt if new_prompt else old_prompt
            ok, msg = update_role(rid, new_name, final_prompt, activate=False)
            _bat_write(f"[{'成功' if ok else '错误'}] {'已更新角色「' + msg + '」' if ok else msg}\n")
            time.sleep(1.0)

        elif op == "D":
            if not roles:
                continue
            try:
                idx_s = input(f"\n请输入要删除的角色编号 (1-{len(roles)}, 0取消): ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not idx_s.isdigit() or not (1 <= int(idx_s) <= len(roles)):
                continue
            rid = int(idx_s)
            target_name = roles[rid - 1][0]
            try:
                confirm = input(f"确认永久删除角色「{target_name}」？(输入 y 确认，回车取消): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                continue
            if confirm == "y":
                ok, msg = delete_role(rid)
                _bat_write(f"[{'成功' if ok else '错误'}] {'已删除角色「' + msg + '」' if ok else msg}\n")
                time.sleep(1.0)

        elif op == "O":
            if not os.path.exists(TXT_PATH):
                save_roles_to_file([])
            try:
                subprocess.Popen(["notepad.exe", TXT_PATH])
                _bat_write("\n[提示] 已用记事本打开 role_setting.txt！\n")
                _bat_write("       请在记事本中编辑并按 Ctrl+S 保存，完成后回到此处按【回车键】刷新列表...\n")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
                sync_all_outputs()
                _bat_write("[成功] 已重新解析 role_setting.txt 并同步刷新网页缓存！\n")
                time.sleep(0.8)
            except Exception as e:
                _bat_write(f"[错误] 无法打开记事本: {e}\n")
                time.sleep(1.2)


def list_roles_for_bat():
    roles = list_roles()
    mode, display_name, _ = get_active_prompt_info()
    for idx, (name, prompt) in enumerate(roles, 1):
        is_active = "1" if (mode == MODE_PRESET and name == display_name) else "0"
        short_prompt = prompt.replace("\n", " ")[:60]
        _bat_write(f"{idx}:{name}:{is_active}:{short_prompt}\n")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--list":
            list_roles_for_bat()
        elif cmd == "--list-short":
            list_roles_short_for_bat()
        elif cmd == "--apply" and len(sys.argv) > 2:
            apply_role_cli(sys.argv[2])
        elif cmd == "--apply-none":
            apply_none_cli()
        elif cmd == "--apply-current":
            apply_current_cli()
        elif cmd == "--current-name":
            get_current_name_cli()
        elif cmd == "--custom":
            custom_role_cli()
        elif cmd == "--manage":
            manage_roles_cli()
        elif cmd == "--export-json":
            sync_all_outputs()
        elif cmd == "--set-role" and len(sys.argv) > 2:
            ok, name = set_active_role(sys.argv[2], strict=True, bump_launch=False)
            print(f"Set role to {name}: {ok}")
    else:
        list_roles_for_bat()


if __name__ == "__main__":
    main()
