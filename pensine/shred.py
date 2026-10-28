"""Really forgetting in a journal that erases nothing: crypto-shredding.

The `events` journal is append-only (an SQL trigger refuses UPDATE and
DELETE): that is what makes it possible to re-consolidate everything tomorrow
with a better model. But a right to be forgotten that leaves the text in the
journal is not one.

The reconciliation: when PENSINE_SHRED=1, each new deposit is sealed
(AES-256-GCM) under the key of its SCOPE — by default one scope per deposit,
or one scope per subject chosen at deposit time. The keys live OUTSIDE the
database, in PENSINE_KEYS_DIR, hence outside the SQL dumps. Forgetting a scope:
  1. purge the projections derived from the deposits concerned (memories and
     their embeddings, links, graph edges, relationship states, steps,
     proposals, media); memories that mixed in other deposits are deleted and
     those other deposits are put back up for consolidation: they will be
     recomputed without what was forgotten;
  2. destroy the key. The journal row remains, intact and unreadable:
     append-only holds, the content no longer exists for anyone.

What this does NOT cover (see also the design report): deposits predating
activation (in clear), backups already made of the projections and media,
copies of keys backed up elsewhere, what a remote model provider saw during a
consolidation, and the audit log, which only contains counts.

(`_scelle` / `portee` envelope keys and the `depot_` / `sujet_` scope prefixes
are stored data and stay as they are.)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime
from pathlib import Path

from . import config

ENVELOPE = "_scelle"
VERSION = 1


class ShredError(RuntimeError):
    pass


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # optional dependency: pip install .[shred]
        raise ShredError("PENSINE_SHRED=1 requires the `cryptography` package "
                         "(pip install '.[shred]')") from exc
    return AESGCM(key)


# ---------------------------------------------------------------- scopes

def deposit_scope() -> str:
    """A fresh scope, specific to one deposit."""
    return "depot_" + uuid.uuid4().hex


def subject_scope(label: str) -> str:
    """One scope per subject. The identifier is a digest: the subject itself
    ("santé", a first name…) appears neither in the database nor in a file name."""
    norm = " ".join((label or "").lower().split())
    if not norm:
        raise ValueError("empty subject")
    return "sujet_" + hashlib.sha256(norm.encode()).hexdigest()[:24]


# ------------------------------------------------------------------ keys

def _keys_dir() -> Path:
    d = Path(config.KEYS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _key_path(scope: str) -> Path:
    if not scope or "/" in scope or scope.startswith("."):
        raise ValueError(f"invalid scope: {scope!r}")
    return _keys_dir() / f"{scope}.key"


def key(scope: str, *, create: bool = False) -> bytes | None:
    """Key of the scope; None if it has been destroyed (forgotten scope)."""
    p = _key_path(scope)
    if p.exists():
        return base64.b64decode(p.read_text().strip())
    if not create:
        return None
    k = secrets.token_bytes(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(base64.b64encode(k).decode())
    return k


def destroy_key(scope: str) -> bool:
    """Overwrite then delete the key file. On an SSD or a journaling
    filesystem, overwriting is not a physical guarantee: the guarantee comes
    from the key never having been anywhere else (see backups)."""
    p = _key_path(scope)
    if not p.exists():
        return False
    size = p.stat().st_size
    with open(p, "r+b") as f:
        f.write(secrets.token_bytes(max(size, 64)))
        f.flush()
        os.fsync(f.fileno())
    p.unlink()
    return True


# ---------------------------------------------------------- seal / open

def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()


def seal(payload: dict, scope: str) -> dict:
    k = key(scope, create=True)
    nonce = secrets.token_bytes(12)
    ct = _aesgcm(k).encrypt(nonce, _canon(payload), scope.encode())
    return {ENVELOPE: {"v": VERSION, "portee": scope,
                       "nonce": base64.b64encode(nonce).decode(),
                       "ct": base64.b64encode(ct).decode()}}


def seal_layers(obj, scopes) -> dict:
    """Seal under several scopes, in layers: destroying ONE of the keys is
    enough to make the object unreadable (a candidate born of two deposits is
    forgotten with either one)."""
    out = obj
    for scope in sorted(set(scopes)):
        out = seal(out, scope)
    return out


def open_layers(payload):
    """Inverse of seal_layers; None as soon as a layer has lost its key."""
    out = payload
    for _ in range(64):
        if not is_sealed(_maybe_json(out) if isinstance(out, str) else out):
            return _maybe_json(out) if isinstance(out, str) else out
        out = open_payload(out)
        if out is None:
            return None
    raise ShredError("too many layers")


def is_sealed(payload) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get(ENVELOPE), dict)


def scope_of(payload) -> str | None:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    return payload[ENVELOPE].get("portee") if is_sealed(payload) else None


def open_payload(payload):
    """Return the payload in clear. For a forgotten scope: None.
    An unsealed payload (earlier deposit, or flag off) passes through as is."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return payload
    if not is_sealed(payload):
        return payload
    env = payload[ENVELOPE]
    k = key(env["portee"])
    if k is None:
        return None
    return json.loads(_aesgcm(k).decrypt(base64.b64decode(env["nonce"]),
                                         base64.b64decode(env["ct"]),
                                         env["portee"].encode()))


def open_rows(rows) -> list[dict]:
    """Open the `payload`s of a list of rows; a forgotten row keeps an empty
    payload and carries `forgotten=True`."""
    out = []
    for r in rows:
        r = dict(r)
        if "payload" in r and is_sealed(r["payload"] if isinstance(r["payload"], dict)
                                        else _maybe_json(r["payload"])):
            r["scope"] = scope_of(r["payload"])
            clear = open_payload(r["payload"])
            r["payload"] = clear if clear is not None else {}
            r["forgotten"] = clear is None
        out.append(r)
    return out


def _maybe_json(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def keyed_hash(scope: str, source: str, kind: str, occurred_at: datetime,
               payload: dict) -> str:
    """Deduplication hash of a sealed deposit: an HMAC under the scope key.
    A SHA-256 of the cleartext would let someone, after forgetting, confirm a
    guess ("did this deposit say X?"); once the key is destroyed, the HMAC says nothing."""
    k = key(scope, create=True)
    blob = _canon({"s": source, "k": kind, "o": occurred_at.isoformat(), "p": payload})
    return "h1:" + hmac.new(k, blob, hashlib.sha256).hexdigest()


# --------------------------------------------------------------- forgetting

def _ids(rows, col="id") -> list[int]:
    return [r[col] for r in rows]


def purge_projections(conn, event_ids: list[int]) -> dict:
    """Remove everything derived from these deposits. Returns counts."""
    if not event_ids:
        return {}
    ev = sorted(set(event_ids))
    mems = conn.execute(
        "SELECT id, source_event_ids FROM memories WHERE source_event_ids && %s::bigint[]",
        (ev,)).fetchall()
    mem_ids = _ids(mems)
    # the other deposits of these memories will be re-consolidated, without the forgotten one
    others = sorted({i for m in mems for i in (m["source_event_ids"] or []) if i not in ev})
    counts = {"memoires": len(mem_ids), "a_reconsolider": len(others)}
    if others:
        conn.execute("DELETE FROM consolidation_marks WHERE event_id = ANY(%s)", (others,))
    if mem_ids:
        counts["liens"] = conn.execute(
            "DELETE FROM memory_links WHERE source_id = ANY(%s) OR target_id = ANY(%s)",
            (mem_ids, mem_ids)).rowcount
        conn.execute("UPDATE memories SET superseded_by = NULL WHERE superseded_by = ANY(%s)",
                     (mem_ids,))
        conn.execute("DELETE FROM memories WHERE id = ANY(%s)", (mem_ids,))
    rels = conn.execute(
        "DELETE FROM relations WHERE source_event_ids && %s::bigint[] "
        "RETURNING subject_id, object_id", (ev,)).fetchall()
    states = conn.execute(
        "DELETE FROM relation_states WHERE source_event_ids && %s::bigint[] "
        "RETURNING entity_id", (ev,)).fetchall()
    counts["aretes"], counts["etats_relation"] = len(rels), len(states)
    touched = sorted({i for r in rels for i in (r["subject_id"], r["object_id"]) if i}
                     | {r["entity_id"] for r in states})
    if touched:
        counts["entites"] = conn.execute(
            """DELETE FROM entities e WHERE e.id = ANY(%s)
               AND NOT EXISTS (SELECT 1 FROM relations r
                               WHERE r.subject_id = e.id OR r.object_id = e.id)
               AND NOT EXISTS (SELECT 1 FROM relation_states s WHERE s.entity_id = e.id)
               AND NOT EXISTS (SELECT 1 FROM voiceprints v WHERE v.entity_id = e.id)""",
            (touched,)).rowcount
    counts["etapes"] = conn.execute(
        "DELETE FROM intentions WHERE source_event_ids && %s::bigint[]", (ev,)).rowcount
    # raw night candidates (pensine/integrity.py): those that cite these
    # deposits, and those without a valid source whose night contained them
    counts["candidates"] = conn.execute(
        """DELETE FROM night_candidates WHERE source_event_ids && %s::bigint[]
           OR (cardinality(source_event_ids) = 0 AND batch_event_ids && %s::bigint[])""",
        (ev, ev)).rowcount
    counts["propositions"] = conn.execute(
        "DELETE FROM memory_proposals WHERE event_id = ANY(%s)", (ev,)).rowcount
    media = conn.execute(
        "SELECT m.id, m.storage_path FROM media m JOIN events e ON e.media_id = m.id "
        "WHERE e.id = ANY(%s)", (ev,)).fetchall()
    for m in media:
        # a file deposited twice is stored only once: it is deleted only if
        # no unforgotten deposit points to it any more
        shared = conn.execute(
            """SELECT 1 FROM media m JOIN events e ON e.media_id = m.id
               WHERE m.storage_path = %s AND NOT (e.id = ANY(%s)) LIMIT 1""",
            (m["storage_path"], ev)).fetchone()
        if not shared:
            _unlink_media(m["storage_path"])
        conn.execute(
            """UPDATE media SET storage_path = 'oublie', transcript = NULL,
                      description = NULL, speakers = NULL, exif = NULL,
                      lat = NULL, lon = NULL, place = NULL, place_source = NULL
               WHERE id = %s""", (m["id"],))
    counts["medias"] = len(media)
    # examined forever: a forgotten deposit never goes back into consolidation
    for eid in ev:
        conn.execute("INSERT INTO consolidation_marks (event_id, produced_memory) "
                     "VALUES (%s, false) ON CONFLICT (event_id) DO NOTHING", (eid,))
    return counts


def _unlink_media(storage_path: str | None) -> None:
    if not storage_path or storage_path == "oublie":
        return
    root = Path(config.MEDIA_ROOT).resolve()
    p = Path(storage_path)
    p = (p if p.is_absolute() else root / p).resolve()
    if root in p.parents and p.exists():  # never outside the media folder
        p.unlink()


def forget(conn, *, scope: str | None = None, event_id: int | None = None,
           commit: bool = True) -> dict:
    """Forget a scope (or a deposit's scope). Purge, log, commit the
    transaction, THEN destroy the key: if the destruction fails, the command
    can be re-run without harm."""
    if scope is None:
        if event_id is None:
            raise ValueError("scope or event_id required")
        row = conn.execute("SELECT payload FROM events WHERE id = %s", (event_id,)).fetchone()
        if not row:
            raise ShredError(f"deposit {event_id} not found")
        scope = scope_of(row["payload"])
        if not scope:
            raise ShredError(f"deposit {event_id} is not sealed (predates PENSINE_SHRED=1, or "
                             "flag off): it cannot be forgotten by key destruction")
    ids = _ids(conn.execute(
        "SELECT id FROM events WHERE payload #>> '{_scelle,portee}' = %s", (scope,)).fetchall())
    counts = purge_projections(conn, ids)
    conn.execute(
        """INSERT INTO shred_scopes (id, kind, forgotten_at) VALUES (%s, %s, now())
           ON CONFLICT (id) DO UPDATE SET forgotten_at = now()""",
        (scope, scope.split("_", 1)[0]))
    # no reason anywhere, and only counts in the audit: keeping the reason for
    # a forgetting would mean keeping a trace of what is being forgotten
    from . import db
    db.audit(conn, "shred", "forget", {"depots": len(ids), **counts})
    if commit:
        conn.commit()
    destroyed = destroy_key(scope)
    return {"portee": scope, "depots": len(ids), "cle_detruite": destroyed, **counts}


def register(conn, scope: str) -> None:
    conn.execute("INSERT INTO shred_scopes (id, kind) VALUES (%s, %s) "
                 "ON CONFLICT (id) DO NOTHING", (scope, scope.split("_", 1)[0]))
