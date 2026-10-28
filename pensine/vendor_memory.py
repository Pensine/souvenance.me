"""What an assistant thinks it knows about you: import and comparison.

Assistants keep a portrait of their user. Since 2026, part of it can be
recovered: Claude's data export contains memory documents and projects, and
you can always ask the assistant to copy out verbatim what it retains. The
exact format is undocumented and changes: this module therefore accepts
several shapes and requires none.

Two separate uses:
  · IMPORT — each item becomes a "second-hand" event: another system wrote
    it, interpreted it, often without a date. Consolidation treats it with
    lower confidence than your direct deposits.
  · MIRROR — a measurement: what the assistant knows and your memory does not,
    what your memory knows and it does not, what you share. The thresholds are
    parameters, the distribution is published with the result: this is a
    reproducible experiment, not a verdict.

(Payload keys such as `seconde_main`, `date_connue`, `extrait` and the result
classes `partage` / `voisin` / `absent` are stored or returned data and stay
French.)
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
MAX_ENTRY_CHARS = 1500

_BULLET = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s+(.*)$")
_DATE_PREFIX = re.compile(
    r"^\s*\[?\s*(\d{4}-\d{2}-\d{2})(?:[T ][\d:]+Z?)?\s*\]?\s*[-–:]?\s*")


# --------------------------------------------------------------------------- dates

def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- text

def _chunks(text: str) -> list[str]:
    """Split a paragraph that is too long at sentence ends."""
    if len(text) <= MAX_ENTRY_CHARS:
        return [text]
    out, cur = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sentence) + 1 > MAX_ENTRY_CHARS:
            out.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        out.append(cur)
    return out


def split_text(text: str) -> list[dict]:
    """Split a copied-out memory into items.

    A bulleted list yields one item per bullet (continuation lines are
    attached to it); otherwise, one item per paragraph. Headings are not
    items: they become the `section` of the items that follow. A date at the
    start of a line ("[2026-03-02] - …") becomes `saved_at`.
    """
    lines = text.splitlines()
    bullets = sum(1 for ln in lines if _BULLET.match(ln))
    use_bullets = bullets >= 3 and bullets >= 0.3 * sum(1 for ln in lines if ln.strip())
    entries: list[dict] = []
    section, buf = None, []

    def flush():
        if buf:
            raw = " ".join(s.strip() for s in buf if s.strip())
            m = _DATE_PREFIX.match(raw)
            saved = m.group(1) if m else None
            raw = raw[m.end():] if m else raw
            for piece in _chunks(raw.strip()):
                if any(c.isalnum() for c in piece):  # no stray punctuation
                    entries.append({"text": piece, "section": section, "saved_at": saved})
            buf.clear()

    for ln in lines:
        h = _HEADING.match(ln)
        if h:
            flush()
            section = h.group(1).strip()
            continue
        if use_bullets:
            if _BULLET.match(ln):
                flush()
                buf.append(_BULLET.sub("", ln, count=1))
            elif ln.strip():
                buf.append(ln)
            else:
                flush()
        else:
            if ln.strip():
                buf.append(ln)
            else:
                flush()
    flush()
    return entries


def front_matter(text: str) -> tuple[dict, str]:
    """The "--- key: value ---" header of a memory document, and the rest.

    The header is not a memory: it is the document's context (its name, its
    description). Each item inherits it — it is often there, and only there,
    that it is written which sphere of life the item belongs to.
    """
    if not text.lstrip().startswith("---"):
        return {}, text
    lines = text.lstrip().splitlines()
    meta, end = {}, None
    for i, ln in enumerate(lines[1:], start=1):
        if ln.strip() == "---":
            end = i
            break
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    if end is None:
        return {}, text
    return meta, "\n".join(lines[end + 1:])


# --------------------------------------------------------------------------- JSON

_TEXT_KEYS = ("content", "text", "memory", "value", "summary", "body")
_DATE_KEYS = ("created_at", "updated_at", "saved_at", "date")


def _is_project(obj) -> bool:
    return isinstance(obj, dict) and "name" in obj and any(
        k in obj for k in ("docs", "prompt_template", "description", "is_starter_project"))


def _from_json(data) -> tuple[list[dict], list[dict]]:
    """Memories and projects from a JSON of unknown format, assuming nothing."""
    entries, projects = [], []

    def walk(node, section=None):
        if isinstance(node, str):
            for e in split_text(node):
                entries.append({**e, "section": e["section"] or section})
        elif isinstance(node, list):
            for item in node:
                walk(item, section)
        elif isinstance(node, dict):
            if _is_project(node):
                projects.append(node)
                return
            text = next((node[k] for k in _TEXT_KEYS if isinstance(node.get(k), str)), None)
            if text:
                saved = next((node[k] for k in _DATE_KEYS if node.get(k)), None)
                for e in split_text(text):
                    entries.append({**e, "section": e["section"] or node.get("title")
                                    or node.get("name") or section,
                                    "saved_at": e["saved_at"] or saved})
                return
            for k, v in node.items():
                if isinstance(v, (list, dict)) or (isinstance(v, str) and len(v) > 40):
                    walk(v, section or k)

    walk(data)
    return entries, projects


def _project_payload(p: dict) -> dict:
    docs = []
    for d in p.get("docs") or []:
        if isinstance(d, dict):
            docs.append({"filename": d.get("filename") or d.get("name"),
                         "extrait": (d.get("content") or "")[:2000]})
    return {"name": p.get("name"), "description": p.get("description") or "",
            "instructions": (p.get("prompt_template") or "")[:4000],
            "created_at": p.get("created_at"), "docs": docs}


# --------------------------------------------------------------------------- reading

def read_path(path: Path) -> tuple[list[dict], list[dict], list[str]]:
    """(memory items, projects, notes) from a file or a folder.

    A folder is read as an unzipped export: every memory file (memories/
    folder, memories.json, text files) and the projects (projects/*.json or
    projects.json). conversations.json is left to scripts/import_history.py,
    which already handles it.
    """
    notes: list[str] = []
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    entries, projects = [], []
    for f in files:
        if f.name == "conversations.json":
            notes.append(f"{f}: conversations → scripts/import_history.py")
            continue
        if f.name in ("users.json",):
            continue
        if f.suffix.lower() in TEXT_SUFFIXES:
            meta, body = front_matter(f.read_text(encoding="utf-8", errors="replace"))
            new = split_text(body)
            doc = " — ".join(x for x in (meta.get("name"), meta.get("description")) if x)
            for e in new:
                if doc:
                    e["document"] = doc
            pr = []
        elif f.suffix.lower() == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                notes.append(f"{f}: unreadable JSON, ignored")
                continue
            new, pr = _from_json(data)
        else:
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        for e in new:
            # The full path, not just the name: an item inherits its document's
            # context. A bullet in the projects/ACME/ folder that does not
            # repeat "ACME" stays in the excluded sphere — without this, the
            # constitution's filter let it through.
            e["file"] = f.relative_to(path).as_posix() if path.is_dir() else f.name
            e["file_mtime"] = mtime
        for p in pr:
            p["_file_mtime"] = mtime
            p["_file"] = f.relative_to(path).as_posix() if path.is_dir() else f.name
        entries += new
        projects += pr
    return entries, projects, notes


def to_events(entries: list[dict], projects: list[dict], vendor: str) -> list[dict]:
    """Second-hand events, ready for the governor and the log.

    Without a date of its own, an item takes the exported file's date: stable
    from one import to the next (the hash deduplicates), and honest — it is an
    export date, which consolidation knows not to take for a life date.
    """
    events = []
    for e in entries:
        saved = _dt(e.get("saved_at"))
        events.append({
            "source": "vendor_memory", "kind": "memory_entry",
            "occurred_at": saved or e["file_mtime"],
            "payload": {"vendor": vendor, "text": e["text"], "section": e.get("section"),
                        "file": e.get("file"), "document": e.get("document"),
                        "date_connue": bool(saved),
                        "seconde_main": True},
        })
    for p in projects:
        events.append({
            "source": "vendor_memory", "kind": "project",
            "occurred_at": _dt(p.get("created_at")) or p["_file_mtime"],
            "payload": {"vendor": vendor, **_project_payload(p), "file": p.get("_file"),
                        "seconde_main": True},
        })
    return events


# --------------------------------------------------------------------------- mirror

def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def compare(vendor: list[dict], own: list[dict], *, shared: float = 0.80,
            near: float = 0.65) -> dict:
    """Compare two memories, item by item, by similarity of meaning.

    vendor / own: lists of {"id", "text", "vec"}. For each of the assistant's
    items, its nearest memory of yours; and the reverse. Classes:
    "partage" (≥ shared), "voisin" (≥ near), otherwise "absent".
    """
    def best(item, pool):
        top = max(((cosine(item["vec"], o["vec"]), o) for o in pool),
                  key=lambda x: x[0], default=(0.0, None))
        return top

    def klass(s):
        return "partage" if s >= shared else "voisin" if s >= near else "absent"

    v_rows = []
    for v in vendor:
        s, o = best(v, own)
        v_rows.append({"id": v["id"], "text": v["text"], "score": round(s, 4),
                       "classe": klass(s), "plus_proche": o and {"id": o["id"], "text": o["text"]}})
    o_rows = []
    for o in own:
        s, v = best(o, vendor)
        o_rows.append({"id": o["id"], "text": o["text"], "score": round(s, 4),
                       "classe": klass(s), "plus_proche": v and {"id": v["id"], "text": v["text"]}})

    def stats(rows):
        n = len(rows)
        scores = sorted(r["score"] for r in rows)
        q = (lambda p: scores[min(n - 1, int(p * n))] if n else None)
        counts = {c: sum(1 for r in rows if r["classe"] == c)
                  for c in ("partage", "voisin", "absent")}
        return {"n": n, "classes": counts,
                "pourcentages": {c: round(100 * k / n, 1) if n else 0.0
                                 for c, k in counts.items()},
                "quantiles": {"p10": q(0.1), "p25": q(0.25), "p50": q(0.5),
                              "p75": q(0.75), "p90": q(0.9)}}

    return {"seuils": {"partage": shared, "voisin": near},
            "assistant_vers_moi": {"stats": stats(v_rows), "elements": v_rows},
            "moi_vers_assistant": {"stats": stats(o_rows), "elements": o_rows}}
