"""Tasks derived from the truth, never written by hand.

Two families:
  * write-time integrity: the gold is the fact list itself, with the deposits
    and character spans that carry each fact (`evidence_index`), plus the
    traps that must not become memories;
  * question answering, asked "now" (the day after the window ends), in seven
    categories. Abstention questions are part of the set and of the headline
    score: they cannot be filtered out (see SPEC.md, "lesson from LoCoMo").
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .deposits import Deposit
from .world import Fact, World, _human_date, article

CATEGORIES = ("present", "past", "when", "duration", "event", "attribution", "abstention")


@dataclass
class Question:
    id: str
    category: str
    question: str
    asked_at: str            # ISO date: the "now" of the question
    answer_type: str         # text | date | duration_days | abstain
    gold: str                # canonical answer ("" for abstain)
    aliases: list[str] = field(default_factory=list)
    tolerance_days: int = 0
    fact_ids: list[str] = field(default_factory=list)
    deposit_ids: list[str] = field(default_factory=list)
    source: str = ""         # trap id / "unstated" for abstention questions


def evidence_index(deposits: list[Deposit]) -> dict[str, list[dict]]:
    """fact id -> [{deposit, start, end, role}] in chronological order."""
    idx: dict[str, list[dict]] = {}
    for d in deposits:
        for s in d.spans:
            idx.setdefault(s.fact_id, []).append(
                {"deposit": d.id, "start": s.start, "end": s.end, "role": s.role,
                 "excerpt": d.text[s.start:s.end]})
    return idx


def first_seen(deposits: list[Deposit]) -> dict[str, str]:
    """fact id -> datetime of the first deposit that carries it."""
    seen: dict[str, str] = {}
    for d in deposits:
        for f in d.fact_ids:
            seen.setdefault(f, d.created_at)
    return seen


def derive_questions(w: World, deposits: list[Deposit], seed: int | None = None,
                     abstention_share: float = 0.2) -> list[Question]:
    r = random.Random((seed if seed is not None else w.seed) * 104729 + 3)
    start = date.fromisoformat(w.start)
    end = start + timedelta(days=w.days)
    now = end.isoformat()
    ev = evidence_index(deposits)
    mentioned = set(ev)
    first = w.person(w.owner).name.split()[0]
    qs: list[Question] = []

    def name(pid: str) -> str:
        return w.person(pid).name.split()[0]

    def q(cat, text, atype, gold, facts: list[Fact], aliases=None, tol=0, source=""):
        deps = sorted({e["deposit"] for f in facts for e in ev.get(f.id, [])})
        qs.append(Question("", cat, text, now, atype, gold, aliases or [], tol,
                           [f.id for f in facts], deps, source))

    by_slot: dict[str, list[Fact]] = {}
    for f in w.facts:
        if f.id in mentioned:
            by_slot.setdefault(f.slot, []).append(f)

    def ask_value(f: Fact, as_of: str | None) -> tuple[str, str, list[str]] | None:
        """Question text (present or as-of), gold, aliases for a state fact."""
        n = name(f.subject)
        v = f.value
        when = f" on {_human_date(as_of)}" if as_of else " now"
        verb_now = as_of is None
        match f.predicate:
            case "lives_at":
                return (f"In which city {'does' if verb_now else 'did'} {n} live{when}?",
                        v["city"], [v["street"]])
            case "works_at":
                return (f"Which company {'does' if verb_now else 'did'} {n} work for{when}?",
                        v["employer"], [])
            case "pays_rent":
                return (f"How much rent {'does' if verb_now else 'did'} {n} pay per month{when}?",
                        str(v["amount"]), [f"{v['amount']} {v['currency']}"])
            case "project":
                return (f"What stage {'is' if verb_now else 'was'} {n}'s project, "
                        f"{v['project']}, at{when}?", v["stage"], [])
            case "commutes":
                return (f"How {'does' if verb_now else 'did'} {n} get to work{when}?",
                        v["mode"].split()[-1], [v["mode"]])
            case "hobby":
                return (f"What {'is' if verb_now else 'was'} {n}'s main hobby{when}?",
                        v["hobby"], [])
            case "gym":
                return (f"Which gym {'is' if verb_now else 'was'} {n} a member of{when}?",
                        v["gym"], [])
            case "lives_in":
                return (f"In which city {'does' if verb_now else 'did'} {n} live{when}?",
                        v["city"], [])
            case "job":
                return (f"What {'is' if verb_now else 'was'} {n}'s job{when}?", v["title"], [])
            case "dating":
                return (f"Who {'is' if verb_now else 'was'} {n} dating{when}?",
                        v["name"].split()[0], [v["name"]])
            case "pet":
                return (f"What is the name of {n}'s {v['kind']}?", v["name"], [])
            case "allergy":
                return (f"What is {n} allergic to?", v["food"], [])
            case "hometown":
                return (f"Where did {n} grow up?", v["city"], [])
            case "speaks":
                return (f"Which foreign language does {n} practise?", v["language"], [])
            case "birthday":
                d = date.fromisoformat(v["date"])
                return (f"When is {n}'s birthday?", f"{d.day} {d.strftime('%B')}", [])
        return None

    # present: every mentioned slot whose latest version is still valid now
    for slot, versions in by_slot.items():
        f = versions[-1]
        if f.kind != "state" or f.valid_to is not None:
            continue
        a = ask_value(f, None)
        if a:
            q("present", a[0], "text", a[1], [f], a[2])

    # past: superseded versions, asked as of a day inside their validity
    for slot, versions in by_slot.items():
        for f in versions:
            if not f.valid_to or f.kind != "state" or f.predicate == "health":
                continue
            lo = max(start, date.fromisoformat(f.valid_from))
            hi = date.fromisoformat(f.valid_to) - timedelta(days=1)
            if hi < lo:
                continue
            day = lo + timedelta(days=r.randint(0, (hi - lo).days))
            a = ask_value(f, day.isoformat())
            if a:
                q("past", a[0], "text", a[1], [f], a[2])

    # when: states that begin inside the window
    for f in w.facts:
        if f.id not in mentioned or f.kind != "state" or f.valid_from < w.start:
            continue
        n, v = name(f.subject), f.value
        text = {
            "lives_at": f"When did {n} move to {v.get('street', '')}?",
            "works_at": f"When did {n} start working at {v.get('employer', '')}?",
            "health": f"When was {n} diagnosed with {v.get('condition', '')}?",
            "dating": f"When did {n} start dating {v.get('name', '').split(' ')[0]}?",
            "project": f"When did {n}'s project reach the {v.get('stage', '')} stage?",
            "lives_in": f"When did {n} move to {v.get('city', '')}?",
            "commutes": f"When did {n} start commuting {v.get('mode', '')}?",
            "hobby": f"When did {n} take up {v.get('hobby', '')}?",
            "gym": f"When did {n} switch to {v.get('gym', '')}?",
        }.get(f.predicate)
        if text:
            q("when", text, "date", f.valid_from, [f], tol=0)

    # duration: closed intervals inside the window, and gaps between changes
    for f in w.facts:
        if f.id in mentioned and f.predicate == "health" and f.valid_to:
            days = (date.fromisoformat(f.valid_to) - date.fromisoformat(f.valid_from)).days
            q("duration", f"How many days did {name(f.subject)}'s {f.value['condition']} last, "
              "from diagnosis to recovery?", "duration_days", str(days), [f], tol=1)
    owner_changes = [f for f in w.facts if f.subject == w.owner and f.id in mentioned
                     and f.kind == "state" and f.valid_from >= w.start
                     and f.predicate in ("lives_at", "works_at", "dating", "project")]
    owner_changes.sort(key=lambda f: f.valid_from)
    for a, b in zip(owner_changes, owner_changes[1:]):
        if a.valid_from == b.valid_from:
            continue
        gap = (date.fromisoformat(b.valid_from) - date.fromisoformat(a.valid_from)).days
        q("duration", f"How many days passed between these two changes in {first}'s life: "
          f"\"{a.canonical}\" and \"{b.canonical}\"?", "duration_days", str(gap), [a, b], tol=1)

    # events
    photo_days: dict[str, list[Fact]] = {}
    for f in w.facts:
        if f.id not in mentioned or f.kind != "event":
            continue
        n, v, on = name(f.subject), f.value, _human_date(f.valid_from)
        if f.predicate == "visited":
            photo_days.setdefault(f.valid_from, []).append(f)
        elif f.predicate == "race":
            q("event", f"What was {n}'s finishing time at the {v['race']} on {on}?", "text",
              v["time"], [f])
        elif f.predicate == "met":
            q("event", f"Where did {n} meet {v['name'].split()[0]} on {on}?", "text",
              v["venue"], [f])
        elif f.predicate == "appointment":
            q("event", f"On what date did {n} have {article(v['what'])} appointment?", "date",
              f.valid_from, [f], tol=0)
    for day, fs in photo_days.items():
        cities = {f.value["city"] for f in fs}
        if len(cities) == 1:
            q("event", f"In which city was {first} on {_human_date(day)}?", "text",
              fs[0].value["city"], fs)

    # attribution: who did what — only when the answer is unique
    news = [f for f in w.facts if f.id in mentioned and f.predicate == "news"]
    for f in news:
        same = [g for g in news if g.value["what"] == f.value["what"]
                and abs((date.fromisoformat(g.valid_from) - date.fromisoformat(f.valid_from)).days) < 15]
        if len(same) == 1:
            q("attribution", f"Who {f.value['what']} around {_human_date(f.valid_from)}?", "text",
              name(f.subject), [f], [w.person(f.subject).name])
    moves = [f for f in w.facts if f.id in mentioned and f.predicate == "lives_in"
             and f.valid_from >= w.start]
    for f in moves:
        same = [g for g in moves if g.value["city"] == f.value["city"]]
        if len(same) == 1:
            q("attribution", f"Who moved to {f.value['city']} on {_human_date(f.valid_from)}?",
              "text", name(f.subject), [f], [w.person(f.subject).name])

    # abstention: traps, never-stated slots, photo content — a fixed share
    answerable = len(qs)
    target = max(3, round(answerable * abstention_share / (1 - abstention_share)))
    pool = [(t.question, t.id) for t in w.traps if t.question and t.kind != "photo_content"]
    pool += [(u["question"], "unstated") for u in w.unstated]
    photo = [(t.question, t.id) for t in w.traps if t.kind == "photo_content"]
    r.shuffle(photo)
    pool += photo[:max(1, target // 3)]
    r.shuffle(pool)
    for text, src in pool[:target]:
        q("abstention", text, "abstain", "", [], source=src)

    # one question text, one answer: ambiguous duplicates are dropped
    golds: dict[str, set[str]] = {}
    for x in qs:
        golds.setdefault(x.question, set()).add(x.gold)
    seen: set[str] = set()
    qs = [x for x in qs if len(golds[x.question]) == 1
          and not (x.question in seen or seen.add(x.question))]
    qs.sort(key=lambda x: (CATEGORIES.index(x.category), x.question))
    for i, x in enumerate(qs, 1):
        x.id = f"Q{i:03d}"
    return qs


def question_dicts(qs: list[Question]) -> list[dict]:
    return [asdict(x) for x in qs]
