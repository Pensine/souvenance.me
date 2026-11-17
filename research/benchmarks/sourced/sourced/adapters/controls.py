"""Control systems that validate the harness itself (never published as
competitors).

* `OracleSystem` reads the truth: it must score 0 % invention, 100 % excerpt
  support and full recall. If it does not, the scorer is wrong.
* `InjectedSystem` is the oracle plus inventions injected at a known rate,
  drawn from the traps (plans stated as done, photo descriptions, hearsay
  attributed to the owner). The scorer must recover the injected rate. With
  `misattribution`, a known share of its true memories also declares the
  wrong subject; the scorer must recover that share as the attribution
  error rate. With `imprecision`, a known share of the bounded_date
  questions is answered with one exact date (the middle of the gold
  interval) instead of the interval; the scorer must recover that share as
  the invented precision rate.
* `VerbatimSystem` is a real baseline: it stores every sentence it receives,
  verbatim, citing itself, and answers by lexical retrieval. It cannot invent
  at write time; it shows what "no abstraction" costs on QA.
"""

from __future__ import annotations

import random
import re
from datetime import date

from ..judge import normalize
from .base import AliasLink, Answer, Citation, DepositView, MemoryRecord, MemorySystem


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
        self.seen_deps: set[str] = set()
        self.today = ""
        self.alias_dep = {pid: d["id"] for d in deposits
                          for pid, *_ in d["meta"].get("alias_spans", [])}
        from ..tasks import asserted
        self.dep_facts = {d["id"]: asserted(d) for d in deposits}

    def ingest(self, deposits: list[DepositView], day: date) -> None:
        self.today = day.isoformat()
        for d in deposits:
            self.seen |= set(self.dep_facts.get(d.id, []))
            self.seen_deps.add(d.id)

    def memories(self) -> list[MemoryRecord]:
        out = []
        names = {p["id"]: p["name"] for p in self.truth["people"]}
        bracketed = {x["fact"]: x for x in self.truth.get("dating", [])}
        for f in self.truth["facts"]:
            if f["id"] not in self.seen:
                continue
            x = bracketed.get(f["id"])
            # a bracketed fact: the oracle knows only what the deposits bound
            lo, hi = (x["not_yet_day"], x["already_day"]) if x else (None, None)
            out.append(MemoryRecord(f"M{f['id']}", f["canonical"],
                                    None if x else f["valid_from"],
                                    f["valid_to"], current=f["valid_to"] is None,
                                    confidence=1.0,
                                    citations=[Citation(d, e) for d, e in self.spans[f["id"]]],
                                    subject=names[f["subject"]], event_earliest=lo,
                                    event_latest=hi))
        return out

    def aliases(self) -> list[AliasLink]:
        """Every identity the deposits seen so far make knowable: proven when
        written together, inferred when only converging."""
        names = {p["id"]: p for p in self.truth["people"]}
        out = []
        for x in self.truth.get("identity", []):
            if self.alias_dep.get(x["person"]) in self.seen_deps:
                p = names[x["person"]]
                out.append(AliasLink(p["role"], p["name"].split()[0], "proven"))
        for x in self.truth.get("coverage", []):
            if x["same"] and max(m["day"] for m in x["mentions"]) <= self.today:
                p = names[x["role_person"]]
                out.append(AliasLink(p["role"], p["name"].split()[0], "inferred"))
        return out

    def answer(self, question: str, asked_at: date) -> Answer:
        q = self.questions.get(question)
        if not q or q["answer_type"] == "abstain":
            return Answer("No information", abstained=True)
        if q["answer_type"] == "interval":
            lo, hi = (date.fromisoformat(x) for x in q["gold"].split("/"))
            return Answer(f"Between {_human(lo)} and {_human(hi)}.", abstained=False)
        return Answer(q["gold"], abstained=False)


def _human(d: date) -> str:
    return f"{d.day} {d.strftime('%B')} {d.year}"


class InjectedSystem(OracleSystem):
    name = "control:injected"

    def __init__(self, truth, deposits, questions, rate: float = 0.1, seed: int = 0,
                 misattribution: float = 0.0, imprecision: float = 0.0,
                 false_links: int = 0):
        super().__init__(truth, deposits, questions)
        self.rate, self.r = rate, random.Random(seed)
        self.misattribution = misattribution
        self.deposits = deposits
        bounded = sorted(q["id"] for q in questions if q["answer_type"] == "interval")
        self.imprecise = set(random.Random(2).sample(bounded, round(len(bounded) * imprecision)))
        self.false_links = false_links

    def aliases(self) -> list[AliasLink]:
        """The oracle's links plus `false_links` decoy links (a coverage
        decoy's role tied to its look-alike name), as a careless linker would."""
        good = super().aliases()
        names = {p["id"]: p for p in self.truth["people"]}
        decoys = [x for x in self.truth.get("coverage", []) if not x["same"]]
        bad = [AliasLink(names[x["role_person"]]["role"],
                         names[x["name_person"]]["name"].split()[0], "inferred")
               for x in decoys[:self.false_links]]
        return good + bad

    def answer(self, question: str, asked_at: date) -> Answer:
        q = self.questions.get(question)
        if q and q["id"] in self.imprecise:
            lo, hi = (date.fromisoformat(x) for x in q["gold"].split("/"))
            return Answer(f"On {_human(lo + (hi - lo) / 2)}.", abstained=False)
        return super().answer(question, asked_at)

    def memories(self) -> list[MemoryRecord]:
        good = super().memories()
        if self.misattribution:
            # the content stays true; only the declared subject is wrong, so
            # invention and attribution are measured independently
            facts = {f"M{f['id']}": f for f in self.truth["facts"]}
            names = {p["id"]: p["name"] for p in self.truth["people"]}
            k = round(len(good) * self.misattribution)
            for m in random.Random(1).sample(good, k):
                true = facts[m.id]["subject"]
                m.subject = names[self.truth["owner"]] if true != self.truth["owner"] else \
                    next(n for pid, n in names.items() if pid != true)
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
