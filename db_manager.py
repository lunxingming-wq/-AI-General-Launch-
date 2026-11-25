# -*- coding: utf-8 -*-
"""
Local LLM Server Core - SQLite Database Manager
Provides local persistent storage for conversations, folders, message history,
role assignments, and one-time ephemeral share links (SQLite WAL mode).
"""

import os
import sqlite3
import time
import uuid
from typing import List, Dict, Optional, Tuple

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DB_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "chat_database.db")


def _get_connection():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        role_name TEXT DEFAULT 'Default Assistant',
        model_name TEXT DEFAULT '',
        folder TEXT DEFAULT 'Default',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )
    """)

    cursor.execute("PRAGMA table_info(conversations)")
    columns = [row[1] for row in cursor.fetchall()]
    if "folder" not in columns:
        cursor.execute("ALTER TABLE conversations ADD COLUMN folder TEXT DEFAULT 'Default'")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conv_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        thinking TEXT DEFAULT '',
        tokens INTEGER DEFAULT 0,
        elapsed REAL DEFAULT 0.0,
        is_complete INTEGER DEFAULT 1,
        parent_id TEXT DEFAULT NULL,
        created_at REAL NOT NULL,
        FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("PRAGMA table_info(messages)")
    msg_cols = [row[1] for row in cursor.fetchall()]
    if "parent_id" not in msg_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN parent_id TEXT DEFAULT NULL")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS one_time_links (
        token TEXT PRIMARY KEY,
        link_type TEXT NOT NULL,
        target_id TEXT DEFAULT '',
        max_views INTEGER DEFAULT 1,
        view_count INTEGER DEFAULT 0,
        expires_at REAL NOT NULL,
        is_revoked INTEGER DEFAULT 0,
        created_at REAL NOT NULL,
        note TEXT DEFAULT ''
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS folders (
        name TEXT PRIMARY KEY,
        created_at REAL NOT NULL
    )
    """)
    cursor.execute("INSERT OR IGNORE INTO folders (name, created_at) VALUES ('Default', ?)", (time.time(),))

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_links_token ON one_time_links(token)")

    conn.commit()
    conn.close()


# --- Conversation & Folder Management ---

def create_conversation(title: str = "New Chat", role_name: str = "Default Assistant", model_name: str = "", folder: str = "Default") -> str:
    conv_id = f"conv_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    now = time.time()
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO conversations (id, title, role_name, model_name, folder, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (conv_id, title, role_name, model_name, folder, now, now))
    conn.commit()
    conn.close()
    return conv_id


def list_conversations(folder: Optional[str] = None, limit: int = 100) -> List[Dict]:
    conn = _get_connection()
    cursor = conn.cursor()
    if folder:
        cursor.execute("""
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.conv_id = c.id) as msg_count,
                   (SELECT content FROM messages m WHERE m.conv_id = c.id ORDER BY m.created_at DESC LIMIT 1) as last_msg
            FROM conversations c
            WHERE c.folder = ?
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (folder, limit))
    else:
        cursor.execute("""
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.conv_id = c.id) as msg_count,
                   (SELECT content FROM messages m WHERE m.conv_id = c.id ORDER BY m.created_at DESC LIMIT 1) as last_msg
            FROM conversations c
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (limit,))
    rows = cursor.fetchall()
    res = [dict(r) for r in rows]
    conn.close()
    return res


def list_folders() -> List[str]:
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT folder FROM conversations WHERE folder IS NOT NULL AND folder != ''")
    folders_from_convs = [r[0] for r in cursor.fetchall()]

    cursor.execute("SELECT name FROM folders")
    folders_from_table = [r[0] for r in cursor.fetchall()]
    conn.close()

    all_folders = sorted(list(set(folders_from_convs + folders_from_table + ["Default"])))
    if "Default" in all_folders:
        all_folders.remove("Default")
        all_folders.insert(0, "Default")
    return all_folders


def create_folder(folder_name: str):
    folder_name = folder_name.strip()
    if not folder_name:
        return
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO folders (name, created_at) VALUES (?, ?)", (folder_name, time.time()))
    conn.commit()
    conn.close()


def move_conversation_to_folder(conv_id: str, target_folder: str):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE conversations SET folder = ?, updated_at = ? WHERE id = ?", (target_folder, time.time(), conv_id))
    conn.commit()
    conn.close()


def get_conversation(conv_id: str) -> Optional[Dict]:
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversation(conv_id: str, title: Optional[str] = None, role_name: Optional[str] = None, folder: Optional[str] = None):
    conn = _get_connection()
    cursor = conn.cursor()
    updates = ["updated_at = ?"]
    params = [time.time()]
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if role_name is not None:
        updates.append("role_name = ?")
        params.append(role_name)
    if folder is not None:
        updates.append("folder = ?")
        params.append(folder)
    params.append(conv_id)

    query = f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)
    conn.commit()
    conn.close()


def delete_conversation(conv_id: str):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE conv_id = ?", (conv_id,))
    cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


# --- Message Management ---

def add_message(conv_id: str, role: str, content: str, thinking: str = "", tokens: int = 0, elapsed: float = 0.0, is_complete: int = 1, parent_id: Optional[str] = None) -> str:
    msg_id = f"msg_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    now = time.time()
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (id, conv_id, role, content, thinking, tokens, elapsed, is_complete, parent_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (msg_id, conv_id, role, content, thinking, tokens, elapsed, is_complete, parent_id, now))
    cursor.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
    conn.commit()
    conn.close()
    return msg_id


def update_message(msg_id: str, content: Optional[str] = None, thinking: Optional[str] = None, tokens: Optional[int] = None, elapsed: Optional[float] = None, is_complete: Optional[int] = None):
    conn = _get_connection()
    cursor = conn.cursor()
    updates = []
    params = []
    if content is not None:
        updates.append("content = ?")
        params.append(content)
    if thinking is not None:
        updates.append("thinking = ?")
        params.append(thinking)
    if tokens is not None:
        updates.append("tokens = ?")
        params.append(tokens)
    if elapsed is not None:
        updates.append("elapsed = ?")
        params.append(elapsed)
    if is_complete is not None:
        updates.append("is_complete = ?")
        params.append(is_complete)
    if not updates:
        conn.close()
        return

    params.append(msg_id)
    query = f"UPDATE messages SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)
    conn.commit()
    conn.close()


def edit_message_content(msg_id: str, new_content: str):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE messages SET content = ? WHERE id = ?", (new_content, msg_id))
    conn.commit()
    conn.close()


def fork_conversation_from_message(source_conv_id: str, target_msg_id: str, new_title: Optional[str] = None) -> str:
    """Copy history up to target_msg_id into a new branched conversation."""
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM conversations WHERE id = ?", (source_conv_id,))
    conv = cursor.fetchone()
    if not conv:
        conn.close()
        return create_conversation("Branched Chat")

    old_title = conv["title"]
    role_name = conv["role_name"]
    folder = conv["folder"]
    title = new_title if new_title else f"{old_title} (Branch)"

    new_conv_id = create_conversation(title=title, role_name=role_name, folder=folder)

    cursor.execute("SELECT * FROM messages WHERE conv_id = ? ORDER BY created_at ASC", (source_conv_id,))
    all_msgs = [dict(r) for r in cursor.fetchall()]

    target_idx = -1
    for idx, m in enumerate(all_msgs):
        if m["id"] == target_msg_id:
            target_idx = idx
            break

    msgs_to_copy = all_msgs[:target_idx + 1] if target_idx >= 0 else all_msgs

    for m in msgs_to_copy:
        cursor.execute("""
            INSERT INTO messages (id, conv_id, role, content, thinking, tokens, elapsed, is_complete, parent_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (f"msg_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}", new_conv_id, m["role"], m["content"], m.get("thinking", ""), m.get("tokens", 0), m.get("elapsed", 0.0), 1, None, m["created_at"]))

    conn.commit()
    conn.close()
    return new_conv_id


def get_messages(conv_id: str) -> List[Dict]:
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM messages
        WHERE conv_id = ?
        ORDER BY created_at ASC
    """, (conv_id,))
    rows = cursor.fetchall()
    res = [dict(r) for r in rows]
    conn.close()
    return res


# --- Ephemeral One-Time Share Links ---

def create_one_time_link(link_type: str = "share_conversation", target_id: str = "", max_views: int = 1, expire_seconds: int = 3600, note: str = "") -> Dict:
    token = f"key_{uuid.uuid4().hex}"
    now = time.time()
    expires_at = now + expire_seconds

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO one_time_links (token, link_type, target_id, max_views, view_count, expires_at, is_revoked, created_at, note)
        VALUES (?, ?, ?, ?, 0, ?, 0, ?, ?)
    """, (token, link_type, target_id, max_views, expires_at, now, note))
    conn.commit()
    conn.close()

    return {
        "token": token,
        "link_type": link_type,
        "target_id": target_id,
        "max_views": max_views,
        "expires_at": expires_at,
        "created_at": now,
    }


def validate_and_consume_link(token: str, consume: bool = True) -> Tuple[bool, str, Optional[Dict]]:
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM one_time_links WHERE token = ?", (token,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "This share link does not exist or has already been destroyed.", None

    link = dict(row)
    now = time.time()

    if link["is_revoked"] == 1:
        conn.close()
        return False, "This link has been manually revoked.", link
    if now > link["expires_at"]:
        conn.close()
        return False, "This share link has expired.", link
    if link["view_count"] >= link["max_views"]:
        conn.close()
        return False, "Maximum views reached (burn-after-reading triggered).", link

    if consume:
        new_count = link["view_count"] + 1
        is_rev = 1 if new_count >= link["max_views"] else 0
        cursor.execute("UPDATE one_time_links SET view_count = ?, is_revoked = ? WHERE token = ?", (new_count, is_rev, token))
        conn.commit()
        link["view_count"] = new_count
        link["is_revoked"] = is_rev

    conn.close()
    return True, "OK", link


init_db()
