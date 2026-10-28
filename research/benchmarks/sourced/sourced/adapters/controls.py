"""Control systems that validate the harness itself (never published as
competitors).

* `OracleSystem` reads the truth: it must score 0 % invention, 100 % excerpt
  support and full recall. If it does not, the scorer is wrong.
* `InjectedSystem` is the oracle plus inventions injected at a known rate,
  drawn from the traps (plans stated as done, photo descriptions, hearsay
  attributed to the owner). The scorer must recover the injected rate.
* `VerbatimSystem` is a real baseline: it stores every sentence it receives,
  verbatim, citing itself, and answers by lexical retrieval. It cannot invent
  at write time; it shows what "no abstraction" costs on QA.
"""

from __future__ import annotations

import random
import re
from datetime import date

from ..judge import normalize
from .base import Answer, Citation, DepositView, MemoryRecord, MemorySystem


class OracleSystem(MemorySystem):
    name = "control:oracle"

    def __init__(self, truth: dict, deposits: list[dict], questions: list[dict]):
        self.truth, self.questions = truth, {q["question"]: q for q in questions}
        self.spans: dict[str, list[tuple[str, str]]] = {}
        for d in deposits:
            for s in d["spans"]:
                self.spans.setdefault(s["fact_id"], []).append(
                    (d["id"], d["text"][s["start"]:s["end"]]))
        self.seen: set[str] = set()
        self.dep_facts = {d["id"]: d["fact_ids"] for d in deposits}

    def ingest(self, deposits: list[DepositView], day: date) -> None:
        for d in deposits:
            self.seen |= set(self.dep_facts.get(d.id, []))

    def memories(self) -> list[MemoryRecord]:
        out = []
        for f in self.truth["facts"]:
            if f["id"] not in self.seen:
                continue
            out.append(MemoryRecord(f"M{f['id']}", f["canonical"], f["valid_from"],
                                    f["valid_to"], current=f["valid_to"] is None,
                                    confidence=1.0,
                                    citations=[Citation(d, e) for d, e in self.spans[f["id"]]]))
        return out

    def answer(self, question: str, asked_at: date) -> Answer:
        q = self.questions.get(question)
        if not q or q["answer_type"] == "abstain":
            return Answer("No information", abstained=True)
        return Answer(q["gold"], abstained=False)


class InjectedSystem(OracleSystem):
    name = "control:injected"

    def __init__(self, truth, deposits, questions, rate: float = 0.1, seed: int = 0):
        super().__init__(truth, deposits, questions)
        self.rate, self.r = rate, random.Random(seed)
        self.deposits = deposits

    def memories(self) -> list[MemoryRecord]:
        good = super().memories()
        n_bad = round(len(good) * self.rate / (1 - self.rate))
        owner = next(p for p in self.truth["people"] if p["id"] == self.truth["owner"])["name"]
        traps = [t for t in self.truth["traps"] if t["kind"] != "photo_content"]
        photos = [d for d in self.deposits if d["kind"] == "photo" and d["id"] in
                  {c.deposit_id for m in good for c in m.citations}]
        bad = []
        for i in range(n_bad):
            if photos and i % 2 == 0:
                p = photos[i % len(photos)]
                bad.append(MemoryRecord(f"X{i}", f"The photo shows a sunset over the water, "
                                                 f"{owner} smiling with friends.",
                                        p["created_at"][:10], None, True, 0.4,
                                        [Citation(p["id"], p["text"][:40])]))
            elif traps:
                t = traps[i % len(traps)]
                bad.append(MemoryRecord(f"X{i}", t["forbidden"], t["day"], None, True, 0.3))
        return good + bad


class VerbatimSystem(MemorySystem):
    name = "baseline:verbatim"

    def __init__(self):
        self.store: list[MemoryRecord] = []

    def reset(self) -> None:
        self.store = []

    def ingest(self, deposits: list[DepositView], day: date) -> None:
        for d in deposits:
            if not d.text:
                continue
            for k, s in enumerate(re.split(r"(?<=[.!?])\s+|\n+", d.text)):
                s = s.strip()
                if len(s) > 12:
                    self.store.append(MemoryRecord(f"{d.id}.{k}", s, d.created_at, None, None,
                                                   None, [Citation(d.id, s)]))

    def memories(self) -> list[MemoryRecord]:
        return list(self.store)

    def answer(self, question: str, asked_at: date) -> Answer:
        qt = set(normalize(question).split()) - {"what", "when", "where", "who", "how", "did",
                                                 "does", "is", "was", "the", "a", "on", "in",
                                                 "of", "to", "at", "now"}
        best, score = None, 0
        for m in self.store:
            s = len(qt & set(normalize(m.content).split()))
            if s > score:
                best, score = m, s
        if not best or score < 2:
            return Answer("No information", abstained=True)
        return Answer(f"{best.content} (recorded {best.valid_from})", abstained=False,
                      citations=best.citations)
