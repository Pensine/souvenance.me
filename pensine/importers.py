"""Import of the official ChatGPT and Claude exports — pick up your context.

On day 1, the memory already knows years of conversations: each exported
conversation becomes a `conversation_import` event (layer 0), which nightly
consolidation will replay like everything else. The governor filters at
ingestion (exclusion perimeter), the hash deduplicates — re-running the
import is always safe.

Recognized formats (the `conversations.json` file of the official exports):
- ChatGPT: list of conversations with `mapping` (message tree)
- Claude : list of conversations with `chat_messages`
"""

import json
from datetime import datetime, timezone
from pathlib import Path

MAX_CHARS_PER_MESSAGE = 2000
MAX_MESSAGES_PER_CONV = 400


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def detect_format(data) -> str | None:
    if isinstance(data, list) and data:
        if isinstance(data[0], dict):
            if "mapping" in data[0]:
                return "chatgpt"
            if "chat_messages" in data[0]:
                return "claude"
    return None


def parse_chatgpt(data: list) -> list[dict]:
    """ChatGPT export: each conversation carries a `mapping` tree."""
    events = []
    for conv in data:
        messages = []
        for node in (conv.get("mapping") or {}).values():
            msg = node.get("message") if isinstance(node, dict) else None
            if not msg:
                continue
            role = ((msg.get("author") or {}).get("role") or "")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content") or {}
            parts = [p for p in (content.get("parts") or [])
                     if isinstance(p, str) and p.strip()]
            if not parts:
                continue
            messages.append({
                "role": role,
                "text": "\n".join(parts)[:MAX_CHARS_PER_MESSAGE],
                "at": (_dt(msg.get("create_time")) or datetime.now(timezone.utc)).isoformat(),
            })
        if not messages:
            continue
        messages.sort(key=lambda m: m["at"])
        started = _dt(conv.get("create_time")) or _dt(messages[0]["at"])
        events.append({
            "source": "conversation_import",
            "kind": "conversation",
            "occurred_at": started,
            "payload": {
                "provider": "chatgpt",
                "title": conv.get("title") or "(sans titre)",
                "message_count": len(messages),
                "messages": messages[:MAX_MESSAGES_PER_CONV],
            },
        })
    return events


def parse_claude(data: list) -> list[dict]:
    """Claude export: each conversation carries `chat_messages`."""
    events = []
    for conv in data:
        messages = []
        for msg in conv.get("chat_messages") or []:
            text = msg.get("text") or ""
            if not text and isinstance(msg.get("content"), list):
                text = "\n".join(c.get("text", "") for c in msg["content"]
                                 if isinstance(c, dict))
            if not text.strip():
                continue
            role = "user" if msg.get("sender") == "human" else "assistant"
            messages.append({
                "role": role,
                "text": text[:MAX_CHARS_PER_MESSAGE],
                "at": (_dt(msg.get("created_at")) or datetime.now(timezone.utc)).isoformat(),
            })
        if not messages:
            continue
        started = _dt(conv.get("created_at")) or _dt(messages[0]["at"])
        events.append({
            "source": "conversation_import",
            "kind": "conversation",
            "occurred_at": started,
            "payload": {
                "provider": "claude",
                "title": conv.get("name") or "(sans titre)",
                "message_count": len(messages),
                "messages": messages[:MAX_MESSAGES_PER_CONV],
            },
        })
    return events


def parse_file(path: Path) -> tuple[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    fmt = detect_format(data)
    if fmt == "chatgpt":
        return fmt, parse_chatgpt(data)
    if fmt == "claude":
        return fmt, parse_claude(data)
    raise ValueError(
        "Unrecognized format — expected: conversations.json from an official "
        "ChatGPT export (key 'mapping') or Claude export (key 'chat_messages')."
    )
