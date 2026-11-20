# -*- coding: utf-8 -*-
"""
Unified Thinking Chain Parser
Supports DeepSeek R1 / Qwen-QwQ style <think>...</think> tag separation.
"""


def separate_thinking_and_content(raw_text: str, reasoning_buf: str = "") -> tuple:
    """
    Separate thinking/reasoning content from the final response body.
    Idempotent and safe when </think> has not yet been closed.
    """
    reasoning_clean = (reasoning_buf or "").strip()
    raw = raw_text or ""

    if "<think>" in raw:
        if "</think>" in raw:
            parts = raw.split("</think>", 1)
            think_inside = parts[0].split("<think>", 1)[-1].strip()
            content = parts[1].strip()
            thinking = f"{reasoning_clean}\n{think_inside}".strip() if reasoning_clean and think_inside else (think_inside or reasoning_clean)
        else:
            think_inside = raw.split("<think>", 1)[-1].strip()
            thinking = f"{reasoning_clean}\n{think_inside}".strip() if reasoning_clean and think_inside else (think_inside or reasoning_clean)
            content = ""
    elif "</think>" in raw:
        parts = raw.split("</think>", 1)
        think_inside = parts[0].strip()
        content = parts[1].strip()
        thinking = f"{reasoning_clean}\n{think_inside}".strip() if reasoning_clean and think_inside else (think_inside or reasoning_clean)
    else:
        thinking = reasoning_clean
        content = raw.strip()

    if not content and not thinking and raw:
        content = raw.strip()

    return thinking, content
