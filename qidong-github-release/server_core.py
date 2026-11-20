# -*- coding: utf-8 -*-
"""
Local LLM Server Core & Web Hub
- Root path / serves the official Web UI (web/index.html) or mobile fallback
- /mobile (/m) provides a responsive mobile Web UI with role management
- Persistent server-side storage (SQLite WAL high-concurrency)
- Active generation cancellation via /api/chat/stop
- Multimodal image upload (OpenAI Vision spec)
- Burn-after-reading one-time conversation share links
"""

import os
import sys
import json
import time
import asyncio
import aiohttp
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

TARGET_DIR = os.path.dirname(os.path.abspath(__file__))
if TARGET_DIR not in sys.path:
    sys.path.insert(0, TARGET_DIR)

WEB_DIR = os.path.join(TARGET_DIR, "web")

import db_manager
import role_manager
import network_helper
from thinking_parser import separate_thinking_and_content

LLAMA_BACKEND_URL = "http://127.0.0.1:8081"
SERVER_PORT = 8080

app = FastAPI(title="Local LLM Server Core & Web Hub")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists(os.path.join(WEB_DIR, "_app")):
    app.mount("/_app", StaticFiles(directory=os.path.join(WEB_DIR, "_app")), name="_app")

# Active generation tasks: msg_id -> asyncio.Task
active_generation_tasks: Dict[str, asyncio.Task] = {}
# Conversation active generation mapping: conv_id -> msg_id
active_conv_to_msg: Dict[str, str] = {}

# =====================================================
# 1. Conversation & Message Management API
# =====================================================

@app.get("/api/conversations")
async def get_conversations():
    convs = db_manager.list_conversations()
    if not convs:
        db_manager.create_conversation("New Chat")
        convs = db_manager.list_conversations()
    return {"status": "ok", "conversations": convs}

@app.post("/api/conversations")
async def create_new_conversation(req: Request):
    data = await req.json()
    title = data.get("title", "New Chat")
    role_name = data.get("role_name", "Default Assistant")
    folder = data.get("folder", "Default")
    conv_id = db_manager.create_conversation(title=title, role_name=role_name, folder=folder)
    return {"status": "ok", "conv_id": conv_id}

@app.get("/api/conversations/{conv_id}")
async def get_conversation_detail(conv_id: str):
    conv = db_manager.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db_manager.get_messages(conv_id)
    return {"status": "ok", "conversation": conv, "messages": messages}

@app.put("/api/conversations/{conv_id}")
async def update_conv(conv_id: str, req: Request):
    data = await req.json()
    title = data.get("title")
    role_name = data.get("role_name")
    folder = data.get("folder")
    db_manager.update_conversation(conv_id, title=title, role_name=role_name, folder=folder)
    return {"status": "ok"}

@app.delete("/api/conversations/{conv_id}")
async def delete_conv(conv_id: str):
    db_manager.delete_conversation(conv_id)
    return {"status": "ok"}

# =====================================================
# 2. Core Chat Streaming & Persistence (Multimodal + Sampling)
# =====================================================

async def run_server_side_chat(conv_id: str, assistant_msg_id: str, messages_payload: List[Dict], sampling_params: Dict, client_queue: asyncio.Queue):
    full_raw = ""
    full_thinking = ""
    token_count = 0
    t0 = time.time()

    llama_req_body = {
        "messages": messages_payload,
        "stream": True,
        "temperature": float(sampling_params.get("temperature", 0.7)),
        "top_p": float(sampling_params.get("top_p", 0.9)),
    }
    if "repeat_penalty" in sampling_params:
        llama_req_body["repeat_penalty"] = float(sampling_params["repeat_penalty"])
    if "max_tokens" in sampling_params and int(sampling_params["max_tokens"]) > 0:
        llama_req_body["max_tokens"] = int(sampling_params["max_tokens"])

    try:
        timeout = aiohttp.ClientTimeout(total=1800, sock_read=300)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(f"{LLAMA_BACKEND_URL}/v1/chat/completions", json=llama_req_body) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    err_msg = f"[LLaMA Engine Error {resp.status}]: {err_txt}"
                    db_manager.update_message(assistant_msg_id, content=err_msg, is_complete=1)
                    await client_queue.put(f"data: {json.dumps({'error': err_msg})}\n\n")
                    return

                buffer = ""
                async for chunk_bytes in resp.content:
                    raw_str = chunk_bytes.decode("utf-8", errors="ignore")
                    buffer += raw_str

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line_s = line.strip()
                        if not line_s:
                            continue

                        try:
                            client_queue.put_nowait(f"{line_s}\n\n")
                        except Exception:
                            pass

                        if line_s.startswith("data: "):
                            data_str = line_s[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                r_c = delta.get("reasoning_content", "")
                                c_c = delta.get("content", "")

                                if r_c:
                                    full_thinking += r_c
                                    token_count += 1
                                if c_c:
                                    full_raw += c_c
                                    token_count += 1

                                cur_think, cur_cont = separate_thinking_and_content(full_raw, full_thinking)
                                elapsed = round(time.time() - t0, 1)

                                if token_count % 10 == 0:
                                    db_manager.update_message(
                                        assistant_msg_id,
                                        content=cur_cont if cur_cont else full_raw,
                                        thinking=cur_think,
                                        tokens=token_count,
                                        elapsed=elapsed,
                                        is_complete=0
                                    )
                            except Exception:
                                pass
    except asyncio.CancelledError:
        full_raw += "\n[Generation stopped]"
    except Exception as e:
        full_raw += f"\n[Background generation error: {e}]"
    finally:
        cur_think, cur_cont = separate_thinking_and_content(full_raw, full_thinking)
        elapsed = round(time.time() - t0, 1)
        db_manager.update_message(
            assistant_msg_id,
            content=cur_cont if cur_cont else full_raw,
            thinking=cur_think,
            tokens=token_count,
            elapsed=elapsed,
            is_complete=1
        )
        try:
            client_queue.put_nowait("data: [DONE]\n\n")
        except Exception:
            pass
        active_generation_tasks.pop(assistant_msg_id, None)
        active_conv_to_msg.pop(conv_id, None)

def _resolve_role_system_prompt(role_name: str) -> Optional[str]:
    """Resolve system prompt by frontend role name; returns None in Native Default mode (no system injection)."""
    r = (role_name or "").strip()
    if r in (role_manager.NONE_TOKEN, role_manager.NONE_DISPLAY, "Native Default", "原生默认"):
        return None
    if r in (role_manager.TEMP_TOKEN, role_manager.TEMP_DISPLAY):
        mode, _, prompt = role_manager.get_active_prompt_info()
        return prompt if (mode == role_manager.MODE_TEMP and prompt) else None
    if r:
        for r_name, r_prompt in role_manager.list_roles():
            if r_name == r:
                return r_prompt
    mode, _, prompt = role_manager.get_active_prompt_info()
    if mode == role_manager.MODE_NONE or not prompt:
        return None
    return prompt

@app.post("/api/chat/send")
async def send_chat_message(req: Request):
    data = await req.json()
    conv_id = data.get("conv_id")
    user_prompt = data.get("prompt", "").strip()
    role_name = data.get("role_name", "")
    sampling = data.get("sampling", {})
    image_base64 = data.get("image_base64")

    if not conv_id or (not user_prompt and not image_base64):
        raise HTTPException(status_code=400, detail="Missing conv_id or content (prompt / image)")

    display_prompt = user_prompt if user_prompt else "[Image sent]"
    user_msg_id = db_manager.add_message(conv_id, role="user", content=display_prompt)

    conv = db_manager.get_conversation(conv_id)
    if conv and conv.get("title") in ("New Chat", "新对话"):
        short_title = display_prompt[:16] + ("..." if len(display_prompt) > 16 else "")
        db_manager.update_conversation(conv_id, title=short_title)

    system_prompt = _resolve_role_system_prompt(role_name)

    history_msgs = db_manager.get_messages(conv_id)
    payload_msgs = []
    if system_prompt:
        payload_msgs.append({"role": "system", "content": system_prompt})
    elif os.environ.get("LLAMA_CUSTOM_TEMPLATE") == "1":
        # Send empty system message in custom template mode to override default role baked at startup
        payload_msgs.append({"role": "system", "content": ""})

    # Build message history (excluding latest message handled separately for Vision)
    for m in history_msgs[:-1]:
        payload_msgs.append({
            "role": m["role"],
            "content": m["content"]
        })

    # Latest message: assemble multimodal Vision structure if image is attached
    if image_base64:
        content_items = []
        if user_prompt:
            content_items.append({"type": "text", "text": user_prompt})
        img_url = image_base64 if image_base64.startswith("data:") else f"data:image/jpeg;base64,{image_base64}"
        content_items.append({"type": "image_url", "image_url": {"url": img_url}})
        payload_msgs.append({"role": "user", "content": content_items})
    else:
        payload_msgs.append({"role": "user", "content": user_prompt})

    assistant_msg_id = db_manager.add_message(conv_id, role="assistant", content="", is_complete=0)
    client_queue = asyncio.Queue(maxsize=2000)

    task = asyncio.create_task(run_server_side_chat(conv_id, assistant_msg_id, payload_msgs, sampling, client_queue))
    active_generation_tasks[assistant_msg_id] = task
    active_conv_to_msg[conv_id] = assistant_msg_id

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'init', 'msg_id': assistant_msg_id, 'conv_id': conv_id})}\n\n"
            while True:
                msg = await client_queue.get()
                yield msg
                if "[DONE]" in msg:
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# Regenerate last assistant response
@app.post("/api/chat/regenerate")
async def regenerate_last_message(req: Request):
    data = await req.json()
    conv_id = data.get("conv_id")
    role_name = data.get("role_name", "")
    sampling = data.get("sampling", {})

    if not conv_id:
        raise HTTPException(status_code=400, detail="Missing conv_id")

    msgs = db_manager.get_messages(conv_id)
    if not msgs:
        raise HTTPException(status_code=400, detail="No message history to regenerate")

    # Reset last message if it is from assistant
    if msgs[-1]["role"] == "assistant":
        last_id = msgs[-1]["id"]
        assistant_msg_id = last_id
        db_manager.update_message(assistant_msg_id, content="", thinking="", tokens=0, is_complete=0)
        history_msgs = msgs[:-1]
    else:
        assistant_msg_id = db_manager.add_message(conv_id, role="assistant", content="", is_complete=0)
        history_msgs = msgs

    system_prompt = _resolve_role_system_prompt(role_name)

    payload_msgs = []
    if system_prompt:
        payload_msgs.append({"role": "system", "content": system_prompt})
    elif os.environ.get("LLAMA_CUSTOM_TEMPLATE") == "1":
        payload_msgs.append({"role": "system", "content": ""})
    for m in history_msgs:
        payload_msgs.append({"role": m["role"], "content": m["content"]})

    client_queue = asyncio.Queue(maxsize=2000)
    task = asyncio.create_task(run_server_side_chat(conv_id, assistant_msg_id, payload_msgs, sampling, client_queue))
    active_generation_tasks[assistant_msg_id] = task
    active_conv_to_msg[conv_id] = assistant_msg_id

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'init', 'msg_id': assistant_msg_id, 'conv_id': conv_id})}\n\n"
            while True:
                msg = await client_queue.get()
                yield msg
                if "[DONE]" in msg:
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# Stop active generation task
@app.post("/api/chat/stop")
async def stop_chat_generation(req: Request):
    data = await req.json()
    conv_id = data.get("conv_id")
    msg_id = data.get("msg_id")

    target_msg_id = msg_id or active_conv_to_msg.get(conv_id)
    if target_msg_id and target_msg_id in active_generation_tasks:
        task = active_generation_tasks.get(target_msg_id)
        if task and not task.done():
            task.cancel()
        active_generation_tasks.pop(target_msg_id, None)
        if conv_id:
            active_conv_to_msg.pop(conv_id, None)
        return {"status": "ok", "message": "Generation task cancelled"}
    return {"status": "ok", "message": "No active task running"}

# =====================================================
# 3. Role Card Management API
# =====================================================

@app.get("/api/roles")
async def get_roles_api():
    return {"status": "ok", **role_manager.get_roles_payload()}

@app.post("/api/roles")
async def create_role_api(req: Request):
    data = await req.json()
    name = data.get("name", "")
    prompt = data.get("prompt", "")
    activate = bool(data.get("activate", True))
    ok, msg, new_id = role_manager.add_role(name, prompt, activate=activate)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": new_id, **role_manager.get_roles_payload()}

@app.put("/api/roles/{role_id}")
async def update_role_api(role_id: int, req: Request):
    data = await req.json()
    name = data.get("name", "")
    prompt = data.get("prompt", "")
    activate = bool(data.get("activate", False))
    ok, msg = role_manager.update_role(role_id, name, prompt, activate=activate)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", **role_manager.get_roles_payload()}

@app.delete("/api/roles/{role_id}")
async def delete_role_api(role_id: int):
    ok, msg = role_manager.delete_role(role_id)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"status": "ok", **role_manager.get_roles_payload()}

@app.post("/api/roles/active")
async def set_active_role_api(req: Request):
    data = await req.json()
    mode = data.get("mode", role_manager.MODE_PRESET)
    if mode == role_manager.MODE_NONE:
        ok, msg = role_manager.set_active_none(bump_launch=False)
    elif mode == role_manager.MODE_TEMP:
        ok, msg = role_manager.set_active_temp(data.get("temp_prompt", ""), bump_launch=False)
    else:
        ref = data.get("role_name") or data.get("role_id") or ""
        ok, msg = role_manager.set_active_role(ref, strict=True, bump_launch=False)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", **role_manager.get_roles_payload()}

# =====================================================
# 4. One-Time Secure Links & Share Page
# =====================================================

@app.post("/api/links/create")
async def create_link_api(req: Request):
    data = await req.json()
    link_type = data.get("link_type", "share_conversation")
    target_id = data.get("target_id", "")
    max_views = int(data.get("max_views", 1))
    expire_seconds = int(data.get("expire_seconds", 3600))

    link_info = db_manager.create_one_time_link(
        link_type=link_type,
        target_id=target_id,
        max_views=max_views,
        expire_seconds=expire_seconds
    )
    return {"status": "ok", "link": link_info}

@app.get("/share/{token}", response_class=HTMLResponse)
async def view_shared_conversation(token: str):
    is_valid, reason, link = db_manager.validate_and_consume_link(token, consume=True)
    if not is_valid:
        return HTMLResponse(content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Link Expired</title>
            <style>
                body {{ background: #0c0d14; color: #f8fafc; font-family: -apple-system, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }}
                .card {{ background: rgba(26, 23, 40, 0.85); border: 1px solid rgba(244, 63, 94, 0.3); border-radius: 20px; padding: 36px; max-width: 400px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.6); backdrop-filter: blur(16px); }}
                h2 {{ color: #fb7185; font-size: 20px; margin-bottom: 10px; }}
                p {{ color: #94a3b8; font-size: 13.5px; line-height: 1.6; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div style="font-size: 48px; margin-bottom: 12px;">🌸</div>
                <h2>This Burn-After-Reading Link Has Been Destroyed</h2>
                <p>{reason}</p>
            </div>
        </body>
        </html>
        """, status_code=403)

    conv_id = link["target_id"]
    conv = db_manager.get_conversation(conv_id)
    messages = db_manager.get_messages(conv_id) if conv else []

    msg_html_list = []
    for m in messages:
        role_label = "👤 User" if m["role"] == "user" else "🤖 Assistant"
        box_class = "user-msg" if m["role"] == "user" else "ai-msg"
        think_html = f'<details class="think-box"><summary>💭 Thinking Process</summary><pre>{m["thinking"]}</pre></details>' if m.get("thinking") else ""
        content_html = f'<div class="msg-content">{m["content"]}</div>'
        msg_html_list.append(f"""
        <div class="msg-bubble {box_class}">
            <div class="msg-header">{role_label}</div>
            {think_html}
            {content_html}
        </div>
        """)

    msgs_body = "".join(msg_html_list) if msg_html_list else "<p style='color:#94a3b8; text-align:center;'>No messages found</p>"

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{conv.get('title', 'Shared Chat') if conv else 'Shared Chat'}</title>
        <style>
            body {{ background: #0c0d14; color: #fdf2f8; font-family: -apple-system, sans-serif; margin: 0; padding: 16px; display: flex; justify-content: center; }}
            .container {{ width: 100%; max-width: 740px; }}
            .header {{ background: rgba(30, 27, 46, 0.8); border: 1px solid rgba(236, 72, 153, 0.25); border-radius: 16px; padding: 18px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }}
            .badge {{ display: inline-block; background: linear-gradient(135deg, #ec4899, #8b5cf6); color: #fff; font-size: 11px; padding: 4px 10px; border-radius: 20px; font-weight: bold; margin-bottom: 8px; }}
            .msg-bubble {{ background: rgba(24, 21, 37, 0.85); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; padding: 16px; margin-bottom: 16px; backdrop-filter: blur(12px); }}
            .user-msg {{ border-left: 4px solid #38bdf8; }}
            .ai-msg {{ border-left: 4px solid #ec4899; }}
            .msg-header {{ font-size: 13px; font-weight: 600; color: #f472b6; margin-bottom: 8px; }}
            .msg-content {{ font-size: 14.5px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; color: #f1f5f9; }}
            .think-box {{ background: rgba(15, 12, 25, 0.9); border: 1px solid rgba(168, 85, 247, 0.2); border-radius: 10px; padding: 10px; margin-bottom: 10px; font-size: 12.5px; color: #c084fc; }}
            .think-box pre {{ white-space: pre-wrap; margin: 6px 0 0 0; font-family: inherit; color: #cbd5e1; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <span class="badge">✨ Burn-After-Reading Private Share</span>
                <h2 style="margin: 0 0 6px 0; font-size: 18px; color:#fdf2f8;">{conv.get('title', 'Shared Conversation') if conv else 'Shared Conversation'}</h2>
                <div style="font-size: 12px; color: #a1a1aa;">This link has been destroyed on the local server; refreshing will no longer show this page.</div>
            </div>
            {msgs_body}
        </div>
    </body>
    </html>
    """)

# =====================================================
# 5. Web UI & Responsive Mobile Client
# =====================================================

@app.get("/")
async def serve_root_index(request: Request):
    index_file = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html")
    return await mobile_web_index()

@app.get("/mobile", response_class=HTMLResponse)
@app.get("/m", response_class=HTMLResponse)
async def mobile_web_index():
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Local LLM · Mobile Workstation</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --accent: #7c3aed;
            --accent-hover: #6d28d9;
            --user-bubble: #0284c7;
            --ai-bubble: #334155;
            --border: #334155;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
        body { background: var(--bg-color); color: var(--text-main); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        
        /* Top navigation */
        header { background: var(--card-bg); border-bottom: 1px solid var(--border); padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; z-index: 10; }
        .brand { font-size: 17px; font-weight: bold; color: var(--text-main); display: flex; align-items: center; gap: 6px; }
        .brand span { color: #a855f7; }
        .top-actions { display: flex; gap: 8px; align-items: center; }
        .role-pill { background: #4c1d95; color: #e9d5ff; font-size: 12px; font-weight: bold; padding: 5px 12px; border-radius: 14px; border: 1px solid #7c3aed; cursor: pointer; }
        .btn-icon { background: #334155; color: #cbd5e1; border: none; padding: 6px 10px; border-radius: 8px; font-size: 13px; cursor: pointer; font-weight: 500; }
        
        /* Conversation drawer (mobile slide-out) */
        .drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 90; display: none; opacity: 0; transition: opacity 0.25s ease; }
        .drawer { position: fixed; top: 0; bottom: 0; left: 0; width: 280px; background: var(--card-bg); border-right: 1px solid var(--border); z-index: 100; transform: translateX(-100%); transition: transform 0.25s ease; display: flex; flex-direction: column; }
        .drawer.open { transform: translateX(0); }
        .drawer-overlay.open { display: block; opacity: 1; }
        .drawer-header { padding: 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; font-weight: bold; }
        .drawer-list { flex: 1; overflow-y: auto; padding: 10px; }
        .conv-item { padding: 12px; border-radius: 8px; margin-bottom: 6px; background: #0f172a; border: 1px solid transparent; font-size: 14px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
        .conv-item.active { border-color: var(--accent); background: #2e1065; color: #f5f3ff; font-weight: bold; }
        
        /* Main chat viewport */
        #chat-messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; }
        .bubble-row { display: flex; flex-direction: column; max-width: 88%; }
        .bubble-row.user { align-self: flex-end; align-items: flex-end; }
        .bubble-row.assistant { align-self: flex-start; align-items: flex-start; }
        .bubble-header { font-size: 11px; font-weight: 600; margin-bottom: 4px; color: var(--text-sub); }
        .user .bubble-header { color: #38bdf8; }
        .assistant .bubble-header { color: #c084fc; }
        .bubble { padding: 12px 16px; border-radius: 16px; font-size: 14.5px; line-height: 1.6; word-break: break-word; }
        .user .bubble { background: var(--user-bubble); color: #ffffff; border-bottom-right-radius: 4px; }
        .assistant .bubble { background: var(--ai-bubble); color: #f8fafc; border-bottom-left-radius: 4px; border: 1px solid var(--border); }
        
        .thinking-card { background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 10px; padding: 8px 12px; margin-bottom: 8px; font-size: 12px; color: #c084fc; }
        .thinking-card summary { cursor: pointer; font-weight: bold; outline: none; }
        .thinking-card pre { margin-top: 6px; white-space: pre-wrap; color: #cbd5e1; font-family: inherit; font-size: 11.5px; }

        /* Bottom composer bar */
        footer { background: var(--card-bg); border-top: 1px solid var(--border); padding: 10px 14px; display: flex; gap: 8px; align-items: flex-end; }
        #chat-input { flex: 1; background: #0f172a; color: #ffffff; border: 1px solid var(--border); border-radius: 12px; padding: 10px 14px; font-size: 14.5px; resize: none; max-height: 100px; min-height: 42px; outline: none; font-family: inherit; }
        #chat-input:focus { border-color: var(--accent); }
        #btn-send { background: var(--accent); color: #ffffff; border: none; width: 44px; height: 42px; border-radius: 12px; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
        #btn-send:active { background: var(--accent-hover); }
        #btn-send.stop-btn { background: #e11d48; }

        /* Mobile role selector and editor sheet */
        .m-role-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.68); z-index: 120; display: none; align-items: flex-end; justify-content: center; }
        .m-role-overlay.open { display: flex; }
        .m-role-sheet { width: 100%; max-width: 520px; max-height: 82vh; background: var(--card-bg); border-top-left-radius: 18px; border-top-right-radius: 18px; border: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
        .m-role-head { padding: 14px 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; font-weight: bold; }
        .m-role-body { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
        .m-role-card { padding: 12px; border-radius: 10px; background: #0f172a; border: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; cursor: pointer; }
        .m-role-card.active { border-color: #a855f7; background: #2e1065; }
        .m-role-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .m-role-preview { font-size: 12px; color: var(--text-sub); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        .m-role-form { padding: 14px; display: none; flex-direction: column; gap: 10px; }
        .m-role-form.open { display: flex; }
        .m-role-form input, .m-role-form textarea { width: 100%; background: #0f172a; color: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 10px; font-size: 14px; font-family: inherit; outline: none; }
        .m-role-form textarea { min-height: 130px; resize: vertical; }
    </style>
</head>
<body>
    <div id="drawer-overlay" class="drawer-overlay" onclick="toggleDrawer(false)"></div>
    <div id="drawer" class="drawer">
        <div class="drawer-header">
            <span>Conversations</span>
            <button class="btn-icon" onclick="createNewSession()">+ New Chat</button>
        </div>
        <div id="drawer-conv-list" class="drawer-list"></div>
    </div>

    <div id="m-role-overlay" class="m-role-overlay" onclick="if(event.target===this) closeMobileRoleSheet()">
        <div class="m-role-sheet">
            <div class="m-role-head">
                <span id="m-role-title">🎭 Role Presets &amp; Editor</span>
                <div style="display:flex;gap:6px;">
                    <button id="m-role-add-btn" class="btn-icon" style="background:#7c3aed;color:#fff;" onclick="openMobileRoleEditor(null)">+ New</button>
                    <button class="btn-icon" onclick="closeMobileRoleSheet()">✕</button>
                </div>
            </div>
            <div id="m-role-list" class="m-role-body"></div>
            <div id="m-role-form" class="m-role-form">
                <input id="m-role-name" type="text" placeholder="Role name" />
                <textarea id="m-role-prompt" placeholder="System prompt (multiline supported)..."></textarea>
                <div style="display:flex;justify-content:flex-end;gap:8px;">
                    <button class="btn-icon" onclick="showMobileRoleList()">Cancel</button>
                    <button class="btn-icon" style="background:#7c3aed;color:#fff;" onclick="saveMobileRole()">Save &amp; Apply</button>
                </div>
            </div>
        </div>
    </div>

    <header>
        <div class="brand">
            <button class="btn-icon" onclick="toggleDrawer(true)" style="margin-right: 4px;">☰</button>
            <span>✦ Local AI</span>
        </div>
        <div class="top-actions">
            <div id="role-badge" class="role-pill" onclick="openMobileRoleSheet()">🎭 Loading</div>
            <button class="btn-icon" onclick="exportCurrentChat()">📥 Export</button>
        </div>
    </header>

    <div id="chat-messages"></div>

    <footer>
        <textarea id="chat-input" placeholder="Type a message (Enter to send)..." rows="1" onkeydown="handleInputKey(event)"></textarea>
        <button id="btn-send" onclick="handleSendOrStop()">➔</button>
    </footer>

    <script>
        let currentConvId = null;
        let currentRoleName = "__NONE__";
        let currentRoleDisplay = "Native Default";
        let isGenerating = false;
        let activeRoles = [];
        let activeMode = "preset";
        let tempPrompt = "";
        let editingMobileRoleId = null;

        async function initApp() {
            await loadRoles();
            await loadConversations();
        }

        function updateMobileRoleBadge() {
            const badge = document.getElementById("role-badge");
            if (activeMode === "none" || currentRoleName === "__NONE__") {
                badge.innerText = "⚪ Native Default";
            } else if (activeMode === "temp" || currentRoleName === "__TEMP__") {
                badge.innerText = "⚡ Temp Role";
            } else {
                const shortName = currentRoleDisplay.length > 7 ? currentRoleDisplay.slice(0, 6) + ".." : currentRoleDisplay;
                badge.innerText = "🎭 " + shortName;
            }
        }

        async function loadRoles() {
            try {
                const res = await fetch("/api/roles", { cache: "no-store" });
                const data = await res.json();
                activeRoles = data.roles || [];
                activeMode = data.mode || "preset";
                tempPrompt = data.temp_prompt || "";
                currentRoleName = data.active_role || "__NONE__";
                currentRoleDisplay = data.active_display || currentRoleName;
                updateMobileRoleBadge();
            } catch(e){}
        }

        async function openMobileRoleSheet() {
            await loadRoles();
            showMobileRoleList();
            document.getElementById("m-role-overlay").classList.add("open");
        }

        function closeMobileRoleSheet() {
            document.getElementById("m-role-overlay").classList.remove("open");
        }

        function showMobileRoleList() {
            editingMobileRoleId = null;
            document.getElementById("m-role-title").innerText = "🎭 Role Presets & Editor";
            document.getElementById("m-role-add-btn").style.display = "inline-block";
            document.getElementById("m-role-form").classList.remove("open");
            const listEl = document.getElementById("m-role-list");
            listEl.style.display = "flex";
            listEl.innerHTML = "";

            // Native Default
            const noneCard = document.createElement("div");
            noneCard.className = "m-role-card" + (activeMode === "none" ? " active" : "");
            noneCard.innerHTML = '<div class="m-role-top"><span>⚪ Native Default (No Role)</span></div><div class="m-role-preview">Reply directly using the model\\'s built-in behavior</div>';
            noneCard.onclick = async () => {
                await fetch("/api/roles/active", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({mode:"none"}) });
                await loadRoles();
                closeMobileRoleSheet();
            };
            listEl.appendChild(noneCard);

            if (tempPrompt) {
                const tCard = document.createElement("div");
                tCard.className = "m-role-card" + (activeMode === "temp" ? " active" : "");
                tCard.innerHTML = '<div class="m-role-top"><span>⚡ Temporary Custom Role</span></div>';
                const p = document.createElement("div"); p.className = "m-role-preview"; p.innerText = tempPrompt;
                tCard.appendChild(p);
                tCard.onclick = async () => {
                    await fetch("/api/roles/active", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({mode:"temp", temp_prompt:tempPrompt}) });
                    await loadRoles();
                    closeMobileRoleSheet();
                };
                listEl.appendChild(tCard);
            }

            activeRoles.forEach(r => {
                const card = document.createElement("div");
                card.className = "m-role-card" + (activeMode === "preset" && currentRoleName === r.name ? " active" : "");
                const top = document.createElement("div");
                top.className = "m-role-top";
                const nm = document.createElement("span");
                nm.innerText = r.name;
                nm.style.fontWeight = "600";
                const ops = document.createElement("div");
                ops.style.display = "flex"; ops.style.gap = "6px";
                const eb = document.createElement("button");
                eb.className = "btn-icon"; eb.innerText = "✏️";
                eb.onclick = (e) => { e.stopPropagation(); openMobileRoleEditor(r); };
                const db = document.createElement("button");
                db.className = "btn-icon"; db.innerText = "🗑️";
                db.onclick = async (e) => {
                    e.stopPropagation();
                    if (!confirm('Delete role "' + r.name + '"?')) return;
                    await fetch("/api/roles/" + r.id, { method: "DELETE" });
                    await loadRoles();
                    showMobileRoleList();
                };
                ops.appendChild(eb); ops.appendChild(db);
                top.appendChild(nm); top.appendChild(ops);
                const prev = document.createElement("div");
                prev.className = "m-role-preview";
                prev.innerText = r.prompt;
                card.appendChild(top); card.appendChild(prev);
                card.onclick = async () => {
                    await fetch("/api/roles/active", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({mode:"preset", role_name:r.name}) });
                    await loadRoles();
                    closeMobileRoleSheet();
                };
                listEl.appendChild(card);
            });
        }

        function openMobileRoleEditor(roleOrNull) {
            editingMobileRoleId = roleOrNull ? roleOrNull.id : null;
            document.getElementById("m-role-title").innerText = roleOrNull ? "✏️ Edit Role" : "➕ New Role";
            document.getElementById("m-role-add-btn").style.display = "none";
            document.getElementById("m-role-list").style.display = "none";
            document.getElementById("m-role-form").classList.add("open");
            document.getElementById("m-role-name").value = roleOrNull ? roleOrNull.name : "";
            document.getElementById("m-role-prompt").value = roleOrNull ? roleOrNull.prompt : "";
        }

        async function saveMobileRole() {
            const name = document.getElementById("m-role-name").value.trim();
            const prompt = document.getElementById("m-role-prompt").value.trim();
            if (!name || !prompt) { alert("Please fill in both role name and prompt."); return; }
            const url = editingMobileRoleId ? ("/api/roles/" + editingMobileRoleId) : "/api/roles";
            const method = editingMobileRoleId ? "PUT" : "POST";
            const res = await fetch(url, {
                method,
                headers: {"Content-Type":"application/json"},
                body: JSON.stringify({ name, prompt, activate: true })
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert(err.detail || "Save failed");
                return;
            }
            await loadRoles();
            closeMobileRoleSheet();
        }

        async function loadConversations() {
            try {
                const res = await fetch("/api/conversations");
                const data = await res.json();
                const list = data.conversations || [];
                const container = document.getElementById("drawer-conv-list");
                container.innerHTML = "";

                if (!list.length) {
                    await createNewSession();
                    return;
                }

                if (!currentConvId || !list.find(c => c.id === currentConvId)) {
                    currentConvId = list[0].id;
                }

                list.forEach(c => {
                    const item = document.createElement("div");
                    item.className = "conv-item" + (c.id === currentConvId ? " active" : "");
                    item.innerText = "✦ " + c.title;
                    item.onclick = () => {
                        currentConvId = c.id;
                        toggleDrawer(false);
                        loadConversations();
                        loadMessages(currentConvId);
                    };
                    container.appendChild(item);
                });

                loadMessages(currentConvId);
            } catch(e){}
        }

        async function createNewSession() {
            try {
                const res = await fetch("/api/conversations", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ title: "New Chat", role_name: currentRoleName })
                });
                const data = await res.json();
                currentConvId = data.conv_id;
                toggleDrawer(false);
                await loadConversations();
            } catch(e){}
        }

        async function loadMessages(convId) {
            const container = document.getElementById("chat-messages");
            container.innerHTML = "";
            try {
                const res = await fetch("/api/conversations/" + convId);
                const data = await res.json();
                (data.messages || []).forEach(m => renderBubble(m.role, m.content, m.thinking));
                container.scrollTop = container.scrollHeight;
            } catch(e){}
        }

        function renderBubble(role, content, thinking = "") {
            const container = document.getElementById("chat-messages");
            const isUser = role === "user";
            const row = document.createElement("div");
            row.className = "bubble-row " + (isUser ? "user" : "assistant");

            const header = document.createElement("div");
            header.className = "bubble-header";
            header.innerText = isUser ? "👤 Me" : "✦ " + currentRoleDisplay;
            row.appendChild(header);

            const bubble = document.createElement("div");
            bubble.className = "bubble";

            if (thinking && !isUser) {
                const thinkCard = document.createElement("details");
                thinkCard.className = "thinking-card";
                thinkCard.innerHTML = "<summary>💭 Thinking Process</summary><pre>" + thinking + "</pre>";
                bubble.appendChild(thinkCard);
            }

            const textDiv = document.createElement("div");
            textDiv.innerText = content;
            bubble.appendChild(textDiv);

            row.appendChild(bubble);
            container.appendChild(row);
            container.scrollTop = container.scrollHeight;
            return textDiv;
        }

        function toggleDrawer(show) {
            document.getElementById("drawer").classList.toggle("open", show);
            document.getElementById("drawer-overlay").classList.toggle("open", show);
        }

        function handleInputKey(e) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSendOrStop();
            }
        }

        async function handleSendOrStop() {
            const btn = document.getElementById("btn-send");
            if (isGenerating) {
                isGenerating = false;
                btn.innerText = "➔";
                btn.classList.remove("stop-btn");
                fetch("/api/chat/stop", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ conv_id: currentConvId })
                });
                return;
            }

            const input = document.getElementById("chat-input");
            const text = input.value.trim();
            if (!text || !currentConvId) return;

            input.value = "";
            renderBubble("user", text);

            isGenerating = true;
            btn.innerText = "⏹";
            btn.classList.add("stop-btn");

            const liveDiv = renderBubble("assistant", "💭 ● ○ ○");

            try {
                const res = await fetch("/api/chat/send", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ conv_id: currentConvId, prompt: text, role_name: currentRoleName })
                });

                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let fullText = "";

                while (isGenerating) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    const chunk = decoder.decode(value);
                    const lines = chunk.split("\\n");
                    for (const line of lines) {
                        if (line.startsWith("data: ")) {
                            const dataStr = line.slice(6).trim();
                            if (dataStr === "[DONE]") break;
                            try {
                                const parsed = JSON.parse(dataStr);
                                const delta = parsed.choices?.[0]?.delta?.content || "";
                                if (delta) {
                                    fullText += delta;
                                    liveDiv.innerText = fullText;
                                    document.getElementById("chat-messages").scrollTop = document.getElementById("chat-messages").scrollHeight;
                                }
                            } catch(e){}
                        }
                    }
                }
            } catch(e) {
                liveDiv.innerText = "[Connection interrupted or completed]";
            } finally {
                isGenerating = false;
                btn.innerText = "➔";
                btn.classList.remove("stop-btn");
                loadMessages(currentConvId);
            }
        }

        function exportCurrentChat() {
            window.location.href = "/api/conversations/" + currentConvId;
        }

        window.onload = initApp;
    </script>
</body>
</html>
""")

# =====================================================
# 6. Static Web UI Assets & Engine Reverse Proxy
# =====================================================

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "Local AI Server Core", "port": SERVER_PORT}

@app.get("/api/system/status")
async def system_status():
    from model_manager import get_system_vram_info, get_system_ram_info
    gpu_name, vram_total, vram_used, vram_free = get_system_vram_info()
    ram_total, ram_used, ram_avail = get_system_ram_info()

    backend_status = "offline"
    try:
        timeout = aiohttp.ClientTimeout(total=1.0)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(f"{LLAMA_BACKEND_URL}/health") as r:
                backend_status = "ready" if r.status == 200 else "loading"
    except Exception:
        backend_status = "offline"

    return {
        "status": "ok",
        "backend": backend_status,
        "gpu": {
            "name": gpu_name,
            "total_gb": vram_total,
            "used_gb": vram_used,
            "free_gb": vram_free
        },
        "ram": {
            "total_gb": ram_total,
            "used_gb": ram_used,
            "avail_gb": ram_avail
        }
    }

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
async def catch_all_proxy(request: Request, full_path: str):
    """
    General reverse proxy:
    1. Serve static files from web/ if they exist.
    2. Forward /props, /models, /slots, /completion, /v1/chat/completions, etc. to llama-server (8081).
    3. Stream SSE/chunked responses transparently back to the client.
    """
    if request.method == "GET":
        local_file = os.path.join(WEB_DIR, full_path)
        if os.path.exists(local_file) and os.path.isfile(local_file):
            return FileResponse(local_file)

    target_url = f"{LLAMA_BACKEND_URL}/{full_path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    role_mode_hdr = None
    for hk in list(headers.keys()):
        if hk.lower() == "x-llama-role-mode":
            role_mode_hdr = headers.pop(hk)

    body = await request.body()

    # Unified system prompt adaptation for /chat/completions and /v1/chat/completions
    if request.method == "POST" and body and full_path.rstrip("/").endswith("chat/completions"):
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
                msgs = payload["messages"]
                use_custom_tpl = (os.environ.get("LLAMA_CUSTOM_TEMPLATE") == "1")
                if role_mode_hdr == "none":
                    if use_custom_tpl:
                        if msgs and msgs[0].get("role") == "system":
                            msgs[0]["content"] = ""
                        else:
                            msgs.insert(0, {"role": "system", "content": ""})
                    else:
                        if msgs and msgs[0].get("role") == "system" and not str(msgs[0].get("content", "")).strip():
                            msgs.pop(0)
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                elif role_mode_hdr is None:
                    # Fallback injection for direct OpenAI API clients without an explicit system message
                    has_sys = any(m.get("role") == "system" for m in msgs)
                    if not has_sys:
                        m_mode, _, m_prompt = role_manager.get_active_prompt_info()
                        if m_mode != role_manager.MODE_NONE and m_prompt:
                            msgs.insert(0, {"role": "system", "content": m_prompt})
                            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except Exception:
            pass
    client = None
    try:
        timeout = aiohttp.ClientTimeout(total=1800, sock_read=300)
        client = aiohttp.ClientSession(timeout=timeout)
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=body if body else None,
            params=dict(request.query_params)
        )

        content_type = resp.headers.get("Content-Type", "")
        resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "content-encoding", "transfer-encoding")}

        is_streaming = (
            "text/event-stream" in content_type.lower()
            or "chunked" in resp.headers.get("Transfer-Encoding", "").lower()
            or full_path.endswith("completions")
            or full_path.endswith("completion")
        )

        if is_streaming:
            resp_headers["Cache-Control"] = "no-cache"
            resp_headers["X-Accel-Buffering"] = "no"
            resp_headers["Connection"] = "keep-alive"

            async def stream_generator():
                try:
                    async for chunk in resp.content.iter_any():
                        if chunk:
                            yield chunk
                finally:
                    resp.close()
                    if client and not client.closed:
                        await client.close()

            return StreamingResponse(
                stream_generator(),
                status_code=resp.status,
                headers=resp_headers,
                media_type=content_type or "text/event-stream"
            )
        else:
            resp_body = await resp.read()
            resp.close()
            if client and not client.closed:
                await client.close()
            return Response(
                content=resp_body,
                status_code=resp.status,
                headers=resp_headers,
                media_type=content_type or None
            )
    except Exception as e:
        if client and not client.closed:
            await client.close()
        return JSONResponse({"status": "loading", "error": f"Proxy to llama-server: {e}"}, status_code=503)

async def _backend_monitor_task():
    was_healthy = False
    while True:
        await asyncio.sleep(2.0)
        try:
            timeout = aiohttp.ClientTimeout(total=1.5)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(f"{LLAMA_BACKEND_URL}/health") as r:
                    if r.status == 200:
                        was_healthy = True
                    else:
                        if was_healthy:
                            # llama-server crashed or stopped
                            was_healthy = False
                            try:
                                import memory_optimizer
                                memory_optimizer.restore()
                            except Exception:
                                pass
        except Exception:
            if was_healthy:
                was_healthy = False
                try:
                    import memory_optimizer
                    memory_optimizer.restore()
                except Exception:
                    pass

def _cleanup_on_shutdown():
    try:
        import memory_optimizer
        memory_optimizer.restore()
    except Exception:
        pass

import atexit
atexit.register(_cleanup_on_shutdown)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(_backend_monitor_task())

@app.on_event("shutdown")
async def on_shutdown():
    _cleanup_on_shutdown()

def run():
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="warning")

if __name__ == "__main__":
    run()
