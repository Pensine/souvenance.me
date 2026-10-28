"""MCP Apps cards: small interfaces displayed in the conversation.

A tool declares `_meta.ui.resourceUri`; the host (Claude, or any client that
implements the MCP Apps extension) reads the matching HTML resource, displays
it in a sandboxed frame and passes it the tool result. A client that does not
know the extension simply ignores the card and reads the JSON: nothing
breaks.

The frame forbids any script coming from elsewhere. The official browser module
(@modelcontextprotocol/ext-apps 2.0.3, MIT, copied into vendor/) is therefore
inlined into each page at load time, along with the shared stylesheet.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).parent
MIME = "text/html;profile=mcp-app"
BUNDLE = HERE / "vendor" / "ext-apps-app-with-deps-2.0.3.js"
NAMES = ("listen", "memory", "timeline")


def uri(name: str) -> str:
    return f"ui://pensine/{name}.html"


@lru_cache(maxsize=1)
def _bundle() -> str:
    """The ESM module rewritten as a classic script: `export {a as B}` becomes
    `globalThis.ExtApps = {B: a}`, the only form that can run inline."""
    src = BUNDLE.read_text(encoding="utf-8")

    def to_global(m: re.Match) -> str:
        pairs = []
        for part in m.group(1).split(","):
            local, _, exported = part.strip().partition(" as ")
            pairs.append(f"{(exported or local).strip()}:{local.strip()}")
        return "globalThis.ExtApps={" + ",".join(pairs) + "};"

    out, n = re.subn(r"export\s*\{([^}]+)\};?\s*$", to_global, src)
    if n != 1:
        raise RuntimeError("ext-apps bundle: final export not found")
    return out


@lru_cache(maxsize=None)
def html(name: str, bundle: str | None = None) -> str:
    """The full page of a card, ready to serve."""
    page = (HERE / f"{name}.html").read_text(encoding="utf-8")
    base = (HERE / "base.css").read_text(encoding="utf-8")
    page = page.replace("/*__BASE_CSS__*/", base)
    return page.replace("/*__EXT_APPS_BUNDLE__*/", bundle if bundle is not None else _bundle())
