# -*- coding: utf-8 -*-
"""
思考链解析公共模块 (Thinking Chain Parser - Unified)
统一思考链解析模块，供 server_core.py 调用。
支持 DeepSeek R1 / Qwen-QwQ 风格的 <think>...</think> 标签解析。
"""


def separate_thinking_and_content(raw_text: str, reasoning_buf: str = "") -> tuple:
    """
    分离思考链与正式回复内容。
    - 纯净处理 <think>...</think> 标签，幂等安全，不产生指数膨胀；
    - 若模型未闭合 </think>，保证内容不会被吞空丢失。
    """
    reasoning_clean = (reasoning_buf or "").strip()
    raw = (raw_text or "")

    if "<think>" in raw:
        if "</think>" in raw:
            parts = raw.split("</think>", 1)
            think_inside = parts[0].split("<think>", 1)[-1].strip()
            content = parts[1].strip()
            thinking = f"{reasoning_clean}\n{think_inside}".strip() if reasoning_clean and think_inside else (think_inside or reasoning_clean)
        else:
            think_inside = raw.split("<think>", 1)[-1].strip()
            thinking = f"{reasoning_clean}\n{think_inside}".strip() if reasoning_clean and think_inside else (think_inside or reasoning_clean)
            # 未闭合时若只有思考，content 为空；但若只有纯文本无 reasoning，保证有内容呈现
            content = ""
    elif "</think>" in raw:
        parts = raw.split("</think>", 1)
        think_inside = parts[0].strip()
        content = parts[1].strip()
        thinking = f"{reasoning_clean}\n{think_inside}".strip() if reasoning_clean and think_inside else (think_inside or reasoning_clean)
    else:
        thinking = reasoning_clean
        content = raw.strip()

    # 安全兜底：若 content 为空且 thinking 存在，但 raw_text 已经完成且没有显式标签，则回退为 raw_text
    if not content and not thinking and raw:
        content = raw.strip()

    return thinking, content
