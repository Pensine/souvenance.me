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
from .base import AliasLink, Answer, Citation, DepositView, MemoryRecord, MemorySystem

REPO = Path(__file__).resolve().parents[5]
PORT = int(os.environ.get("SOURCED_DB_PORT", "5443"))
DBNAME = "sourced_eval"

ANSWER_SYSTEM = (
    "You answer questions about {owner}'s life using ONLY the memory context "
    "provided (JSON from a memory engine). Reply with the shortest possible answer: "
    "a few words, a name, a number or a date. Write dates as '8 May 2025'. "
    "When the context gives an event date as an interval (date_evenement), answer "
    "'between A and B' with both dates; never pick a single date inside it. "
    "If the context does not contain the answer, reply exactly: No information")


def _url(db: str) -> str:
    return f"postgresql://sourced:sourced@127.0.0.1:{PORT}/{db}"


def photo_position(d: DepositView) -> dict | None:
    """A photo's position, as Pensine receives it from a phone: the device's
    structured metadata (EXIF in production), never parsed from text nor
    left to the model."""
    if d.position is None:
        return None
    return {"lat": d.position[0], "lon": d.position[1], "source": "exif"}


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
                if gps := photo_position(d):
                    payload["lieu"] = gps
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
            self.gate.append({"day": day.isoformat(), "events": len(events), **{
                k: r.get(k) for k in (
                    "memories_written", "memories_rejected", "memories_corrected",
                    "memories_other_voice",
                    "memories_revised", "batches", "batches_failed", "events_pending",
                    "llm_calls", "answers_repaired", "answers_truncated",
                    "language_checked", "language_mismatched", "time_bounds_admitted",
                    "time_bounds_refused") if k in r}})
            print(f"night {day}: {len(events)} events, {r.get('memories_written')} written, "
                  f"{r.get('memories_rejected')} rejected, "
                  f"{r.get('events_pending', 0)} left pending", file=sys.stderr, flush=True)

    def _scripted(self, conn, events) -> dict:
        """The stand-in for the consolidation model (scripted mode only)."""
        assert self.truth, "scripted mode needs the truth"
        firsts = {p["name"]: p["name"].split()[0] for p in self.truth["people"]}
        people = {p["id"]: p for p in self.truth["people"]}
        facts = {f["id"]: f for f in self.truth["facts"]}
        traps = {t["id"]: t for t in self.truth["traps"]}

        def subject_of(sentence: str) -> str:
            """The careless writer's subject: whoever the sentence opens with."""
            for full, first in sorted(firsts.items(), key=lambda x: -len(x[0])):
                if sentence.startswith(full) or sentence.startswith(first + " "):
                    return first
            return firsts[self.owner]

        def first_names(s: str) -> str:
            for full, first in firsts.items():
                s = s.replace(full, first)
            return s

        out, aliases = [], []
        for e in events:
            dep = self.gold_deposits[self.event_deposit[e["id"]]]
            # the deposit itself names role and name together: an identity
            # claim, which Pensine admits or not (pensine/identity.py)
            for pid, a, b in dep.get("meta", {}).get("alias_spans", []):
                p = people[pid]
                aliases.append({"name": p["name"].split()[0], "alias": p["role"],
                                "role_of_owner": p["relation"],
                                "excerpt": dep["text"][a:b], "source_event_id": e["id"],
                                "confidence": 0.9})
            for s in dep["spans"]:
                f = facts[s["fact_id"]]
                if f.get("layer") == "dating":
                    out += self._dated(e, dep, s, f, people)
                    continue
                if f.get("layer") == "coverage":  # written as deposited, role or name
                    quote = dep["text"][s["start"]:s["end"]]
                    p = people[f["subject"]]
                    by_role = bool(p["role"]) and quote.lower().find(p["role"]) >= 0
                    out.append({"type": "semantic", "content": quote, "confidence": 0.9,
                                "importance": 0.4, "valid_from": dep["created_at"][:10],
                                "source_event_ids": [e["id"]], "preuve": [quote],
                                "subject": p["role"] if by_role else p["name"].split()[0]})
                    continue
                prev = facts.get(f["supersedes"]) if f["supersedes"] else None
                replaces = []
                if prev:
                    row = conn.execute("SELECT id FROM memories WHERE content = %s AND "
                                       "superseded_by IS NULL ORDER BY id DESC LIMIT 1",
                                       (first_names(prev["canonical"]),)).fetchone()
                    replaces = [row["id"]] if row else []
                content = first_names(f["canonical"])
                subject = people[f["subject"]]["name"].split()[0]
                if f.get("layer") == "identity" and f["predicate"] == "employer":
                    # written as deposited, by role: Pensine must resolve who
                    subject = people[f["subject"]]["role"]
                    content = f"{subject[0].upper()}{subject[1:]} works at " \
                              f"{f['value']['employer']}."
                if f["predicate"] == "race":  # injected: altered number, real quote
                    m, sec = f["value"]["time"].rsplit(":", 1)
                    content = content.replace(f["value"]["time"],
                                              f"{m}:{(int(sec) + 7) % 60:02d}")
                out.append({"type": "episodic" if f["kind"] == "event" else "semantic",
                            "content": content, "confidence": 0.9, "importance": 0.5,
                            "valid_from": f["valid_from"], "valid_to": f["valid_to"],
                            "source_event_ids": [e["id"]],
                            "preuve": [dep["text"][s["start"]:s["end"]]],
                            "remplace": replaces, "raison": "changed", "subject": subject})
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
                                "preuve": [t["sentence"]],
                                "subject": subject_of(first_names(t["forbidden"]))})
        return {"memories": out, "entities": [], "relations": [], "aliases": aliases,
                "identity_hypotheses": self._hypotheses(events)}

    def _hypotheses(self, events) -> list[dict]:
        """A careless linker: on the night the last attribute deposit of a
        coverage pair arrives, propose that the role IS the name, citing every
        attribute value they share, generic ones and single ones included.
        Pensine's code must keep only the converging pair and let a later
        "lunch with my flatmate and X" refute the look-alike."""
        tonight = {self.event_deposit[e["id"]] for e in events}
        event_of = {d: i for i, d in self.event_deposit.items()}
        facts = {f["id"]: f for f in self.truth["facts"]}
        people = {p["id"]: p for p in self.truth["people"]}
        out = []
        for x in self.truth.get("coverage", []):
            spans = []
            for d in self.gold_deposits.values():
                for s in d["spans"]:
                    if any(m["fact"] == s["fact_id"] for m in x["mentions"]):
                        quote = d["text"][s["start"]:s["end"]]
                        spans.append((d["created_at"], d["id"], facts[s["fact_id"]], quote,
                                      x["role"] in quote.lower()))
            if not spans or max(spans)[1] not in tonight \
                    or any(sp[1] not in event_of for sp in spans):
                continue
            supports = []
            for _, da, fa, qa, ra in spans:
                for _, dn, fn, qn, rn in spans:
                    if ra and not rn and fa["predicate"] == fn["predicate"] \
                            and fa["value"] == fn["value"]:
                        supports.append({"attribute": next(iter(fa["value"].values())),
                                         "alias_excerpt": qa, "alias_event_id": event_of[da],
                                         "name_excerpt": qn, "name_event_id": event_of[dn]})
            if supports:
                out.append({"name": people[x["name_person"]]["name"].split()[0],
                            "alias": x["role"],
                            "role_of_owner": people[x["role_person"]]["relation"],
                            "supports": supports})
        return out

    def aliases(self) -> list[AliasLink]:
        """The identities Pensine holds as active claims, with their tier."""
        from pensine import db

        with db.connection() as conn:
            rows = conn.execute(
                "SELECT a.alias, e.name, a.tier FROM entity_aliases a "
                "JOIN entities e ON e.id = a.entity_id WHERE a.status = 'active' "
                "ORDER BY a.id").fetchall()
        return [AliasLink(r["alias"], r["name"], r["tier"]) for r in rows]

    @staticmethod
    def _dated(e, dep, s, f, people) -> list[dict]:
        """A bracketed fact, as a careful model would write it: the memory
        states what the deposit says ("not yet" / "already") and proposes a
        bound quoting it; Pensine's code computes the date from the deposit
        and derives the interval. Injected: an `exact` bound on the same
        relation quote, which the code must refuse (invented precision)."""
        quote = dep["text"][s["start"]:s["end"]]
        who = people[f["subject"]]["name"].split()[0]
        item = f["value"]["item"]
        key = f"{who} has the {item}"
        if s["role"] == "not_yet":
            content, bounds = f"{who} does not have the {item} yet.", [
                {"side": "earliest", "excerpt": quote, "source_event_id": e["id"]}]
        else:
            content, bounds = f"{who} has the {item}.", [
                {"side": "latest", "excerpt": quote, "source_event_id": e["id"]},
                {"side": "exact", "excerpt": quote, "source_event_id": e["id"]}]
        return [{"type": "semantic", "content": content, "confidence": 0.9,
                 "importance": 0.4, "valid_from": dep["created_at"][:10],
                 "source_event_ids": [e["id"]], "preuve": [quote], "subject": who,
                 "event_key": key, "event_bounds": bounds}]

    # -- read path --------------------------------------------------------
    def memories(self) -> list[MemoryRecord]:
        from pensine import db

        with db.connection() as conn:
            # the subject is the entity Pensine resolved (through an identity
            # claim when the memory names a role), not the text it was given
            rows = conn.execute(
                "SELECT m.id, m.content, m.confidence, m.valid_from, m.valid_to, "
                "m.superseded_by, m.archived_at, m.source_event_ids, m.evidence, "
                "e.name AS subject FROM memories m "
                "LEFT JOIN entities e ON e.id = m.subject_entity_id ORDER BY m.id").fetchall()
            # the interval Pensine derives in code for each memory's fact
            from pensine import dating
            timed = dating.for_memories(conn, [r["id"] for r in rows])
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
                confidence=float(r["confidence"]), citations=cits,
                subject=r["subject"] or "",
                event_earliest=_bound(timed.get(r["id"]), "earliest"),
                event_latest=_bound(timed.get(r["id"]), "latest")))
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


def _bound(iv: dict | None, side: str) -> str | None:
    """One end of a Pensine interval as an ISO date; a contradiction exposes
    nothing (the system itself does not claim a date then)."""
    if not iv or iv.get("conflict") or not iv.get(side):
        return None
    return iv[side]["date"].isoformat()
