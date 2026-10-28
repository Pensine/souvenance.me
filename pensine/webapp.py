"""The "Pensine" web app (phase 2) — a timeline of deposits and of the memory.

Read-only, served by the same process as the API (layer 6). Password auth
(PENSINE_WEBAPP_PASSWORD) → signed cookie. Respects the rule of silence:
it is a page you visit; it pushes nothing.
"""

import hmac
import json
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from . import config, db, shred, temporal

router = APIRouter(prefix="/app")

WEBAPP_PASSWORD = os.environ.get("PENSINE_WEBAPP_PASSWORD", "")
SESSION_TTL_S = 12 * 3600
COOKIE = "pensine_session"


def _signer() -> TimestampSigner:
    return TimestampSigner(config.MEDIA_LINK_SECRET or "dev-secret")


def _authed(request: Request) -> bool:
    token = request.cookies.get(COOKIE, "")
    try:
        return _signer().unsign(token, max_age=SESSION_TTL_S) == b"ok"
    except (BadSignature, SignatureExpired):
        return False


LOGIN_HTML = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pensine</title>
<style>body{font-family:system-ui;display:grid;place-items:center;min-height:90vh;
background:#111;color:#eee}form{display:flex;gap:.5rem}
input,button{padding:.6rem 1rem;border-radius:.5rem;border:1px solid #444;
background:#1c1c1c;color:#eee;font-size:1rem}</style>
<form method="post" action="/app/login">
  <input type="password" name="password" placeholder="password" autofocus>
  <button>Enter</button>
</form>"""

APP_HTML = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pensine — timeline</title>
<style>
:root{color-scheme:dark}
body{font-family:system-ui;margin:0;background:#111;color:#eee}
header{position:sticky;top:0;background:#111c;backdrop-filter:blur(8px);
padding:.8rem 1rem;display:flex;gap:.6rem;flex-wrap:wrap;border-bottom:1px solid #2a2a2a}
header input,header select{padding:.45rem .7rem;border-radius:.5rem;
border:1px solid #444;background:#1c1c1c;color:#eee}
main{max-width:44rem;margin:0 auto;padding:1rem}
.item{border-left:2px solid #3a6;margin:.7rem 0;padding:.5rem .9rem;background:#181818;
border-radius:0 .5rem .5rem 0}
.item.memory{border-color:#57c}
.item.read{border-color:#c93}
.item .when{color:#9a9;font-size:.8rem}
.item .kind{display:inline-block;font-size:.72rem;padding:.1rem .5rem;
border-radius:1rem;background:#2a2a2a;margin-left:.5rem}
.item p{margin:.35rem 0;white-space:pre-wrap}
.item audio,.item img{max-width:100%;margin-top:.4rem;border-radius:.4rem}
.empty{color:#888;text-align:center;margin:3rem 0}
</style>
<header>
  <input id="q" placeholder="filter (text, person, place)…">
  <select id="kind"><option value="">all</option><option>audio</option>
  <option>photo</option><option>video</option><option>pdf</option>
  <option value="memory">memories</option>
  <option value="read">agent reads</option></select>
  <select id="year"><option value="">all years</option></select>
</header>
<main id="list"><div class="empty">loading…</div></main>
<script>
const list = document.getElementById('list');
let items = [];
async function load(){
  const r = await fetch('/app/data'); items = (await r.json()).items;
  const years = [...new Set(items.map(i=>i.when.slice(0,4)))].sort().reverse();
  for(const y of years){const o=document.createElement('option');o.textContent=y;
    document.getElementById('year').appendChild(o);}
  render();
}
function render(){
  const q=document.getElementById('q').value.toLowerCase();
  const k=document.getElementById('kind').value;
  const y=document.getElementById('year').value;
  const shown = items.filter(i =>
    (!q || (i.text||'').toLowerCase().includes(q)) &&
    (!k || i.kind===k || (k==='memory'&&i.type==='memory') || (k==='read'&&i.type==='read')) &&
    (!y || i.when.startsWith(y)));
  list.innerHTML = shown.length ? '' : '<div class="empty">nothing here</div>';
  for(const i of shown){
    const d=document.createElement('div');
    d.className='item'+(i.type==='memory'?' memory':'')+(i.type==='read'?' read':'');
    let media='';
    if(i.media_link && i.kind==='audio') media=`<audio controls preload="none" src="${i.media_link}"></audio>`;
    if(i.media_link && i.kind==='photo') media=`<img loading="lazy" src="${i.media_link}">`;
    if(i.media_link && (i.kind==='video'||i.kind==='pdf')) media=`<a href="${i.media_link}">open file</a>`;
    d.innerHTML=`<div class="when">${i.when.slice(0,10)}<span class="kind">${i.kind||i.type}</span></div><p></p>${media}`;
    d.querySelector('p').textContent=i.text||'';
    list.appendChild(d);
  }
}
['q','kind','year'].forEach(id=>document.getElementById(id).addEventListener('input',render));
load();
</script>"""


def describe_read(r: dict) -> str:
    """An agent read in plain words: who, what, and the memories it saw."""
    d = r["detail"]
    who = d.get("client") or "an agent"
    if r["action"] == "recall":
        head = f"{who} searched “{d.get('query', '')}” — {d.get('hits', 0)} memories read"
    elif r["action"] == "mirror":
        q = d.get("question")
        head = f"{who} opened the mirror" + (f" — “{q}”" if q else "")
    elif r["action"] == "listen":
        head = f"{who} replayed a voice memo"
    elif r["action"] == "memory_card":
        head = f"{who} opened a memory card"
    elif r["action"] == "timeline":
        head = f"{who} drew a timeline of “{d.get('query', '')}”"
    else:
        head = f"{who} asked for curation" + (f" — {d['domain']}" if d.get("domain") else "")
    lines = [f"· #{m['id']} " + ((m["content"] or "(no longer exists)")[:120])
             for m in r["memories"]]
    if r["memories"] == [] and r["action"] == "recall" and "memory_ids" not in d:
        lines = ["· (logged before read tracking: memories not recorded)"]
    return "\n".join([head, *lines])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not WEBAPP_PASSWORD:
        return HTMLResponse("PENSINE_WEBAPP_PASSWORD not configured", status_code=503)
    if not _authed(request):
        return HTMLResponse(LOGIN_HTML)
    return HTMLResponse(APP_HTML)


@router.post("/login")
def login(password: str = Form(...)):
    if not WEBAPP_PASSWORD or not hmac.compare_digest(password, WEBAPP_PASSWORD):
        return HTMLResponse(LOGIN_HTML, status_code=401)
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(COOKIE, _signer().sign(b"ok").decode(), httponly=True,
                    max_age=SESSION_TTL_S, samesite="lax")
    return resp


@router.get("/data")
def data(request: Request):
    if not _authed(request):
        return JSONResponse({"error": "auth"}, status_code=401)
    from .mcp_server import _media_link  # temporary signed links

    items = []
    with db.connection() as conn:
        deposits = conn.execute(
            """
            SELECT e.occurred_at, e.payload, m.id AS media_id, m.kind,
                   m.transcript, m.description
            FROM events e JOIN media m ON m.id = e.media_id
            WHERE e.kind = 'deposit'
            ORDER BY e.occurred_at DESC LIMIT 500
            """
        ).fetchall()
        for d in deposits:
            payload = shred.open_payload(d["payload"]) or {}
            text = d["transcript"] or d["description"] or payload.get("note") or ""
            items.append({
                "when": d["occurred_at"].isoformat(),
                "human_when": temporal.humanize_delta(d["occurred_at"]),
                "kind": d["kind"], "type": "deposit",
                "text": text[:600],
                "media_link": _media_link(d["media_id"]),
            })
        memories = conn.execute(
            """
            SELECT valid_from, type, content FROM memories
            WHERE superseded_by IS NULL
            ORDER BY valid_from DESC LIMIT 500
            """
        ).fetchall()
        for m in memories:
            items.append({
                "when": m["valid_from"].isoformat(),
                "human_when": temporal.humanize_delta(m["valid_from"]),
                "kind": m["type"], "type": "memory",
                "text": m["content"][:600], "media_link": None,
            })
        for r in db.agent_reads(conn):
            items.append({
                "when": r["at"].isoformat(),
                "human_when": temporal.humanize_delta(r["at"]),
                "kind": "read", "type": "read",
                "text": describe_read(r), "media_link": None,
            })
        db.audit(conn, "mcp", "webapp_view", {"items": len(items)})
        conn.commit()
    items.sort(key=lambda i: i["when"], reverse=True)
    return {"items": items}
