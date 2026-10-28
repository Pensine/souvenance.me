"""Pensine adapter, through Pensine's own public functions only.

Deposits go in as events (`db.append_event`), one nightly consolidation runs
per simulated day (`nightly.consolidate`, clock frozen to that night), the
store is read back from the `memories` table, and questions go through
`recall()` — the same function the MCP tool calls. Nothing in Pensine is
modified or monkey-patched beyond the frozen clock (same technique as
research/evals/locomo).

Isolation: a throwaway PostgreSQL (docker-compose.yml in this folder, port
5443, project `sourced-eval`). The adapter sets PENSINE_DATABASE_URL itself
before importing pensine; it never reads a .env.

Two modes:
  * `llm`: the configured backend (PENSINE_LLM_BACKEND=openai|ollama|api|
    claude-cli) writes the memories and answers the questions. This is the
    real measurement.
  * `scripted`: no model at all. The consolidation model is replaced, via
    Pensine's `fake` backend, by a deterministic extractor that emits the gold
    facts PLUS known inventions (photo descriptions with a made-up quote,
    plans and hearsay quoted verbatim but stated as done, an altered race
    time). It does not measure Pensine's extraction; it measures what
    Pensine's code-level evidence gate (pensine/evidence.py) catches, and it
    proves the pipe end to end. QA in this mode returns recall()'s context:
    the score is a retrieval hit rate, labelled as such, not an accuracy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..judge import quote_found
from .base import Answer, Citation, DepositView, MemoryRecord, MemorySystem

REPO = Path(__file__).resolve().parents[5]
PORT = int(os.environ.get("SOURCED_DB_PORT", "5443"))
DBNAME = "sourced_eval"

ANSWER_SYSTEM = (
    "You answer questions about {owner}'s life using ONLY the memory context "
    "provided (JSON from a memory engine). Reply with the shortest possible answer: "
    "a few words, a name, a number or a date. Write dates as '8 May 2025'. "
    "If the context does not contain the answer, reply exactly: No information")


def _url(db: str) -> str:
    return f"postgresql://sourced:sourced@127.0.0.1:{PORT}/{db}"


class PensineSystem(MemorySystem):
    name = "pensine"

    def __init__(self, owner: str, mode: str = "scripted", truth: dict | None = None,
                 deposits: list[dict] | None = None):
        self.owner, self.mode = owner, mode
        self.truth, self.gold_deposits = truth, {d["id"]: d for d in deposits or []}
        os.environ["PENSINE_DATABASE_URL"] = _url(DBNAME)
        os.environ["PENSINE_OWNER_NAME"] = owner
        os.environ["PENSINE_CONSTITUTION"] = str(
            REPO / "research" / "evals" / "locomo" / "constitution-eval.yaml")
        if mode == "scripted":
            os.environ["PENSINE_LLM_BACKEND"] = "fake"
            os.environ["PENSINE_VERIFY"] = "code"
        elif os.environ.get("PENSINE_LLM_BACKEND", "claude-cli") == "fake":
            sys.exit("mode llm needs a real backend (PENSINE_LLM_BACKEND)")
        for p in (str(REPO), str(REPO / "consolidation")):
            if p not in sys.path:
                sys.path.insert(0, p)
        self.event_deposit: dict[int, str] = {}
        self.deposit_text: dict[str, str] = {}
        self.gate: list[dict] = []

    # -- lifecycle --------------------------------------------------------
    def reset(self) -> None:
        import psycopg

        with psycopg.connect(_url("sourced"), autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{DBNAME}" WITH (FORCE)')
            c.execute(f'CREATE DATABASE "{DBNAME}"')
        with psycopg.connect(_url(DBNAME)) as c:
            c.execute((REPO / "db" / "schema.sql").read_text(encoding="utf-8"))
            c.commit()
        subprocess.run([sys.executable, str(REPO / "scripts" / "migrate.py")],
                       env={**os.environ, "PENSINE_DATABASE_URL": _url(DBNAME)},
                       check=True, stdout=subprocess.DEVNULL)

    def _freeze(self, at: datetime) -> None:
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: N805
                return at.astimezone(tz) if tz else at.replace(tzinfo=None)

        import nightly
        from pensine import temporal
        nightly.datetime = Frozen
        temporal.datetime = Frozen

    # -- write path -------------------------------------------------------
    def ingest(self, deposits: list[DepositView], day: date) -> None:
        from pensine import db

        with db.connection() as conn:
            for d in deposits:
                if d.text is None:
                    raise NotImplementedError("Track R (raw media) not wired for Pensine yet")
                payload = {"deposit_id": d.id, "kind": d.kind, "author": d.author,
                           "recipient": d.recipient,
                           ("transcript" if d.kind.startswith("voice") else "text"): d.text}
                at = datetime.fromisoformat(d.created_at).replace(tzinfo=timezone.utc)
                eid = db.append_event(conn, source="sourced", kind=d.kind, occurred_at=at,
                                      payload=payload)
                if eid:
                    self.event_deposit[eid] = d.id
                    self.deposit_text[d.id] = d.text
            conn.commit()

    def end_of_day(self, day: date) -> None:
        import nightly
        from pensine import db, llm
        from pensine.governor import Governor

        with db.connection() as conn:
            events = db.unconsolidated_events(conn, limit=200)
            if not events:
                return
            self._freeze(datetime.combine(day, datetime.min.time(), timezone.utc)
                         + timedelta(hours=23))
            if self.mode == "scripted":
                os.environ["PENSINE_FAKE_LLM_RESPONSE"] = json.dumps(
                    self._scripted(conn, events), ensure_ascii=False)
            try:
                r = nightly.consolidate(conn, Governor(), events)
            except (ValueError, llm.LLMUnavailable) as exc:
                # as in production: the night fails, nothing is written, the
                # events stay unconsolidated and the next night retries them
                conn.rollback()
                self.gate.append({"day": day.isoformat(), "failed": type(exc).__name__,
                                  "events_pending": len(events)})
                print(f"night {day} failed ({type(exc).__name__}), "
                      f"{len(events)} events carried over", file=sys.stderr, flush=True)
                return
            conn.commit()
            self.gate.append({"day": day.isoformat(), **{k: r.get(k) for k in (
                "memories_written", "memories_rejected", "memories_corrected",
                "memories_revised")}})
            print(f"night {day}: {r.get('memories_written')} written, "
                  f"{r.get('memories_rejected')} rejected", file=sys.stderr, flush=True)

    def _scripted(self, conn, events) -> dict:
        """The stand-in for the consolidation model (scripted mode only)."""
        assert self.truth, "scripted mode needs the truth"
        firsts = {p["name"]: p["name"].split()[0] for p in self.truth["people"]}
        facts = {f["id"]: f for f in self.truth["facts"]}
        traps = {t["id"]: t for t in self.truth["traps"]}

        def first_names(s: str) -> str:
            for full, first in firsts.items():
                s = s.replace(full, first)
            return s

        out = []
        for e in events:
            dep = self.gold_deposits[self.event_deposit[e["id"]]]
            for s in dep["spans"]:
                f = facts[s["fact_id"]]
                prev = facts.get(f["supersedes"]) if f["supersedes"] else None
                replaces = []
                if prev:
                    row = conn.execute("SELECT id FROM memories WHERE content = %s AND "
                                       "superseded_by IS NULL ORDER BY id DESC LIMIT 1",
                                       (first_names(prev["canonical"]),)).fetchone()
                    replaces = [row["id"]] if row else []
                content = first_names(f["canonical"])
                if f["predicate"] == "race":  # injected: altered number, real quote
                    m, sec = f["value"]["time"].rsplit(":", 1)
                    content = content.replace(f["value"]["time"],
                                              f"{m}:{(int(sec) + 7) % 60:02d}")
                out.append({"type": "episodic" if f["kind"] == "event" else "semantic",
                            "content": content, "confidence": 0.9, "importance": 0.5,
                            "valid_from": f["valid_from"], "valid_to": f["valid_to"],
                            "source_event_ids": [e["id"]],
                            "preuve": [dep["text"][s["start"]:s["end"]]],
                            "remplace": replaces, "raison": "changed"})
            for tid in dep["trap_ids"]:
                t = traps[tid]
                if t["kind"] == "photo_content":  # injected: made-up quote
                    out.append({"type": "episodic", "confidence": 0.6, "importance": 0.3,
                                "content": f"{firsts[self.owner]} photographed a sunset over "
                                           "the water with friends.",
                                "valid_from": t["day"], "source_event_ids": [e["id"]],
                                "preuve": ["a sunset over the water with friends"]})
                else:  # injected: hedged sentence quoted verbatim, stated as done
                    out.append({"type": "semantic", "confidence": 0.7, "importance": 0.4,
                                "content": first_names(t["forbidden"]),
                                "valid_from": t["day"], "source_event_ids": [e["id"]],
                                "preuve": [t["sentence"]]})
        return {"memories": out, "entities": [], "relations": []}

    # -- read path --------------------------------------------------------
    def memories(self) -> list[MemoryRecord]:
        from pensine import db

        with db.connection() as conn:
            rows = conn.execute(
                "SELECT id, content, confidence, valid_from, valid_to, superseded_by, "
                "archived_at, source_event_ids, evidence FROM memories ORDER BY id").fetchall()
        out = []
        for r in rows:
            deps = [self.event_deposit[i] for i in (r["source_event_ids"] or [])
                    if i in self.event_deposit]
            ev = r["evidence"] or {}
            if isinstance(ev, str):
                ev = json.loads(ev)
            cits = []
            for q in ev.get("citations") or []:
                where = next((d for d in deps if quote_found(q, self.deposit_text.get(d, ""))),
                             deps[0] if deps else "")
                cits.append(Citation(where, q))
            out.append(MemoryRecord(
                id=str(r["id"]), content=r["content"],
                valid_from=r["valid_from"].date().isoformat() if r["valid_from"] else None,
                valid_to=r["valid_to"].date().isoformat() if r["valid_to"] else None,
                current=r["valid_to"] is None and r["superseded_by"] is None
                and r["archived_at"] is None,
                confidence=float(r["confidence"]), citations=cits))
        return out

    def answer(self, question: str, asked_at: date) -> Answer:
        from pensine import llm
        from pensine.mcp_server import recall

        self._freeze(datetime.combine(asked_at, datetime.min.time(), timezone.utc)
                     + timedelta(hours=9))
        context = recall(question, depth="source")
        if self.mode == "scripted":
            return Answer(context, abstained=False)
        text = llm.complete(f"Memory context:\n{context}\n\nQuestion: {question}",
                            system=ANSWER_SYSTEM.format(owner=self.owner))
        return Answer(text.strip())

    def describe(self) -> dict:
        from pensine import config

        commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        return {"name": self.name, "mode": self.mode, "pensine_commit": commit,
                "llm_backend": config.LLM_BACKEND, "verify": config.VERIFY,
                "embeddings": config.EMBEDDING_BACKEND,
                "qa_mode": "context" if self.mode == "scripted" else "answer",
                "evidence_gate": self.gate}
