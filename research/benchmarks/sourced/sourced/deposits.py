"""From truth to deposits: notes, messages, voice memos, photos, documents.

Every sentence that carries a fact is written from that fact, and its exact
character span in the deposit text is recorded. The gold evidence of each
fact is therefore known by construction, down to the characters, including
in disfluent voice transcripts where the span covers the hesitations too.

This module only produces text and metadata. Binary media (audio, image,
PDF) are rendered from it by `media.py`, so the whole truth/text layer stays
fast, dependency-free and testable.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from .world import Fact, Trap, World, _human_date, article

FILLER = [
    "The weather was grey all morning.",
    "Need to buy coffee filters.",
    "Long day, but a good one.",
    "Finally cleaned the kitchen properly.",
    "The neighbours were playing music again.",
    "Made soup with whatever was left in the fridge.",
    "Trying to go to bed earlier this week.",
    "The train was a few minutes late.",
    "Started a new book, slow so far.",
    "Watered the plants on the balcony.",
]
HESITATIONS = ["um,", "uh,", "you know,", "I mean,", "like,", "so,"]


@dataclass
class Span:
    fact_id: str
    start: int
    end: int
    role: str  # "mention" | "start" | "end" | "future"


@dataclass
class Deposit:
    id: str
    kind: str            # note | message | voice | voice_in | message_in | photo | document
    created_at: str      # ISO datetime (local, no timezone: the life is lived in one zone)
    author: str          # person id of who produced it
    recipient: str | None
    text: str            # Track T rendering (reference transcript, EXIF summary, PDF text)
    fact_ids: list[str] = field(default_factory=list)
    trap_ids: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # media parameters (voice, gps, doc type…)
    file: str | None = None


# --- sentences -------------------------------------------------------------

def _first(w: World, pid: str) -> str:
    return w.person(pid).name.split()[0]


class Speaker:
    """Renders facts from one speaker's point of view, remembering whom it
    already introduced (first mention: "my sister Ana", then "Ana")."""

    def __init__(self, w: World, r: random.Random, speaker: str):
        self.w, self.r, self.speaker = w, r, speaker
        self.introduced: set[str] = set()

    def ref(self, pid: str) -> str:
        if pid == self.speaker:
            return "I"
        p = self.w.person(pid)
        first = p.name.split()[0]
        if pid in self.introduced or p.relation == "self":
            return first
        self.introduced.add(pid)
        if self.speaker == "P0":
            return f"my {p.relation} {first}"
        return first

    def pick(self, *options: str) -> str:
        return self.r.choice(options)

    def sentence(self, f: Fact, role: str, when: str) -> str:
        """`when` is a relative or absolute date phrase ("today", "yesterday",
        "on 3 March 2025") or "" for undated mentions."""
        v, me = f.value, f.subject == self.speaker
        who = self.ref(f.subject)
        since = f" since {date.fromisoformat(f.valid_from).strftime('%B %Y')}" \
            if f.since_stated and role == "mention" else ""
        w_ = f" {when}" if when else ""
        p = f.predicate
        if p == "lives_at":
            if role == "start":
                return self.pick(f"Moved into the new flat at {v['street']}, {v['city']}{w_}.",
                                 f"Got the keys{w_}: the new place is {v['street']}, {v['city']}.")
            return self.pick(f"I've been living at {v['street']} in {v['city']}{since}.",
                             f"Back home at {v['street']}, {v['city']}, the radiator is still noisy.")
        if p == "pays_rent":
            return self.pick(f"Rent went out, {v['amount']} {v['currency']} as every month.",
                             f"Paid the rent, {v['amount']} {v['currency']}.")
        if p == "works_at":
            if role == "start":
                return self.pick(f"First day as {v['title']} at {v['employer']}{w_}.",
                                 f"Started at {v['employer']}{w_}, I'm their new {v['title']}.")
            if role == "future":
                return f"I accepted the {v['title']} job at {v['employer']}, I start{w_}."
            return self.pick(f"I've been working as {article(v['title'])} at {v['employer']}{since}.",
                             f"Busy week at {v['employer']}, the usual {v['title']} stuff.")
        if p == "health":
            if role == "end":
                return self.pick(f"Finally over {v['condition']}{w_}.",
                                 f"Fully recovered{w_}, no more {v['care'].split(' and ')[0]}.")
            return self.pick(f"Doctor says I have {v['condition']}{w_}, so {v['care']} for now.",
                             f"Turns out it's {v['condition']}{w_}. {v['care'].capitalize()} it is.")
        if p == "dating":
            other = self.ref(v["person"])
            return self.pick(f"{other} and I are officially seeing each other{w_}.",
                             f"Had a lovely evening with {other}{w_}, I think we're together now.")
        if p == "project":
            if v["stage"] == "planning":
                return f"Started sketching out {v['project']}{w_}, still just planning."
            if v["stage"] == "building":
                return f"Began actually building {v['project']}{w_}."
            return f"Launched {v['project']}{w_}! It's out there now."
        if p == "commutes":
            if role == "start":
                return f"From{w_ or ' now'} on I'm going to work {v['mode']}."
            return f"Went to work {v['mode']} as usual."
        if p == "hobby":
            if role == "start":
                return f"Signed up for {v['hobby']}{w_}, first session was great."
            return f"Spent the evening on {v['hobby']}, still my favourite thing."
        if p == "gym":
            if role == "start":
                return f"Switched to {v['gym']}{w_}."
            return f"Quick session at {v['gym']} after work."
        if p == "birthday":
            d = date.fromisoformat(v["date"])
            if me:
                return f"My birthday is on {d.day} {d.strftime('%B')}, reminder to plan something."
            return f"{who}'s birthday is on {d.day} {d.strftime('%B')}, must not forget."
        if p == "hometown":
            return f"Miss {v['city']} sometimes, it's where I grew up."
        if p == "allergy":
            return f"Had to send the dish back, I'm allergic to {v['food']}."
        if p == "speaks":
            return f"Practised my {v['language']} with a podcast on the way home."
        if p == "pet":
            if me:
                return f"{'My' if who == 'I' else who + chr(39) + 's'} {v['kind']} {v['name']} " \
                       f"{'woke me up at six again' if who == 'I' else 'is adorable'}."
            return f"{who} has a {v['kind']} called {v['name']}."
        if p == "lives_in":
            if role == "start":
                if me:
                    return f"I moved to {v['city']}{w_}, still unpacking."
                return f"{who} moved to {v['city']}{w_}."
            if me:
                return f"Things are good here in {v['city']}."
            return f"{who} lives in {v['city']} these days."
        if p == "job":
            if me:
                return f"Work is busy, being {article(v['title'])} is never boring."
            return f"{who} works as {article(v['title'])}."
        if p == "met":
            return self.pick(f"Met {self.ref(v['person'])} at {v['venue']}{w_}.",
                             f"Coffee with {self.ref(v['person'])} at {v['venue']}{w_}.")
        if p == "race":
            return f"Ran the {v['race']}{w_}, finished in {v['time']}."
        if p == "appointment":
            return f"{v['what'].capitalize()} appointment{w_}, all fine."
        if p == "news":
            if me:
                return f"Big news: I {v['what']}{w_}!"
            return f"{who} {v['what']}{w_}."
        if p == "visited":
            return f"Walked around {v['venue']}{w_}."
        raise ValueError(p)


def disfluent(sentence: str, r: random.Random, rate: float = 0.18) -> str:
    """Spoken rendering: hesitations and a restart now and then."""
    words = sentence.split(" ")
    out = []
    for i, wd in enumerate(words):
        if i and r.random() < rate:
            out.append(r.choice(HESITATIONS))
        if i == 0 and r.random() < 0.25:
            out.append(wd.rstrip(",.!?") + "-")
        out.append(wd)
    return " ".join(out)


# --- documents -------------------------------------------------------------

def lease_document(w: World, home: Fact, rent: Fact | None, landlord: str) -> tuple[str, dict]:
    name = w.person(home.subject).name
    lines = ["RESIDENTIAL LEASE AGREEMENT", "",
             f"Landlord: {landlord}", f"Tenant: {name}",
             f"Premises: {home.value['street']}, {home.value['city']}",
             f"Lease start date: {_human_date(home.valid_from)}"]
    if rent:
        lines.append(f"Monthly rent: {rent.value['amount']} {rent.value['currency']}")
    lines += ["", "The tenant agrees to keep the premises in good order.",
              "Signed by both parties."]
    return "\n".join(lines), {"doc_type": "lease"}


def offer_document(w: World, job: Fact) -> tuple[str, dict]:
    name = w.person(job.subject).name
    v = job.value
    return "\n".join([
        f"{v['employer'].upper()}", "", "OFFER OF EMPLOYMENT", "",
        f"Dear {name},", "",
        f"We are pleased to offer you the position of {v['title']}.",
        f"Your start date will be {_human_date(job.valid_from)}.",
        "Please sign and return a copy of this letter.", "",
        "Human Resources"]), {"doc_type": "offer_letter"}


def clinic_document(w: World, h: Fact, clinic: str) -> tuple[str, dict]:
    name = w.person(h.subject).name
    return "\n".join([
        f"{clinic.upper()}", "", "VISIT SUMMARY", "",
        f"Patient: {name}", f"Date of visit: {_human_date(h.valid_from)}",
        f"Assessment: {h.value['condition']}", f"Plan: {h.value['care']}",
        "Follow up if symptoms persist."]), {"doc_type": "visit_summary"}


def race_document(w: World, race: Fact) -> tuple[str, dict]:
    name = w.person(race.subject).name
    return "\n".join([
        f"{race.value['race'].upper()}", "", "FINISHER CERTIFICATE", "",
        f"Runner: {name}", f"Date: {_human_date(race.valid_from)}",
        f"Official time: {race.value['time']}"]), {"doc_type": "certificate"}


# --- planning --------------------------------------------------------------

@dataclass
class _Mention:
    day: date
    fact: Fact
    role: str
    when: str
    channel: str  # "owner" | "incoming" | "document" | "photo"


def _plan(w: World, r: random.Random) -> list[_Mention]:
    start = date.fromisoformat(w.start)
    end = start + timedelta(days=w.days)
    last = end - timedelta(days=1)
    out: list[_Mention] = []

    def rel(day: date, of: date) -> str:
        delta = (day - of).days
        return {0: "today", 1: "yesterday"}.get(delta, f"on {_human_date(of.isoformat())}")

    for f in w.facts:
        vf = date.fromisoformat(f.valid_from)
        vt = date.fromisoformat(f.valid_to) if f.valid_to else None
        own = f.subject == w.owner
        channel = "owner" if own or r.random() < 0.5 else "incoming"
        if f.kind == "event":
            if f.predicate == "visited":
                out.append(_Mention(vf, f, "mention", "", "photo"))
                if r.random() < 0.4:
                    out.append(_Mention(vf, f, "mention", "today", "owner"))
                continue
            if f.predicate == "race" and r.random() < 0.5:
                out.append(_Mention(vf, f, "mention", "", "document"))
            d = min(vf + timedelta(days=r.choice([0, 0, 1])), last)
            out.append(_Mention(d, f, "mention", rel(d, vf), channel))
            continue
        if vf < start:  # background state: mentioned while true, inside the window
            hi = min(last, (vt - timedelta(days=1)) if vt else last)
            span = (hi - start).days
            if span < 0:
                continue
            d = start + timedelta(days=r.randint(0, max(0, int(span * 0.7))))
            out.append(_Mention(d, f, "mention", "", channel))
            if span > 4 and r.random() < 0.3:
                d2 = start + timedelta(days=r.randint((d - start).days + 1, span))
                out.append(_Mention(d2, f, "mention", "", channel))
        else:  # starts inside the window: announced on the day or the day after
            if f.predicate == "works_at" and f.version > 0:
                d0 = max(start, vf - timedelta(days=r.randint(3, 10)))
                if d0 < vf:
                    out.append(_Mention(d0, f, "future", f"on {_human_date(f.valid_from)}",
                                        "owner"))
                    out.append(_Mention(d0, f, "future", "", "document"))
            if f.predicate in ("lives_at", "health") and r.random() < 0.8:
                out.append(_Mention(vf, f, "start", "", "document"))
            if f.predicate == "pays_rent":
                continue  # carried by the lease document or later mentions
            d = min(vf + timedelta(days=r.choice([0, 0, 1])), last)
            out.append(_Mention(d, f, "start", rel(d, vf), channel))
        if vt and vt < end and f.predicate == "health":
            out.append(_Mention(vt, f, "end", "today", "owner"))
    # rent versions in the window travel with the lease; make sure each one
    # appears at least once, even without a lease document
    rent_docs = {(m.day, m.fact.id) for m in out if m.channel == "document"}
    for f in w.facts:
        if f.predicate == "pays_rent" and date.fromisoformat(f.valid_from) >= start:
            home = next(h for h in w.facts if h.predicate == "lives_at"
                        and h.valid_from == f.valid_from)
            if (date.fromisoformat(home.valid_from), home.id) not in rent_docs:
                d = min(date.fromisoformat(f.valid_from) + timedelta(days=r.randint(1, 5)), last)
                out.append(_Mention(d, f, "mention", "", "owner"))
    return sorted(out, key=lambda m: (m.day, m.fact.id, m.channel))


def build_deposits(w: World, seed: int | None = None) -> list[Deposit]:
    r = random.Random((seed if seed is not None else w.seed) * 7919 + 1)
    plan = _plan(w, r)
    start = date.fromisoformat(w.start)
    speakers: dict[str, Speaker] = {}
    landlord = f"{r.choice(['Ash', 'Birch', 'Elm', 'Rowan'])} Property Lettings"
    clinic = f"{r.choice(['Northgate', 'Riverside', 'Parkview'])} Medical Practice"
    deposits: list[Deposit] = []
    traps_by_day: dict[date, list[Trap]] = {}
    for t in w.traps:
        if t.kind != "photo_content":
            traps_by_day.setdefault(date.fromisoformat(t.day), []).append(t)
    photo_traps = {t.fact_id: t for t in w.traps if t.kind == "photo_content"}

    def new(kind, day: date, author, recipient=None, hour=None) -> Deposit:
        h = hour if hour is not None else f"{r.randint(7, 22):02d}:{r.randint(0, 59):02d}"
        d = Deposit(id="", kind=kind, created_at=f"{day.isoformat()}T{h}:00",
                    author=author, recipient=recipient, text="")
        deposits.append(d)
        return d

    def speaker(pid: str) -> Speaker:
        if pid not in speakers:
            speakers[pid] = Speaker(w, r, pid)
        return speakers[pid]

    def append(d: Deposit, sentence: str, fact: Fact | None, role: str = "mention",
               spoken: bool = False) -> None:
        if spoken:
            sentence = disfluent(sentence, r)
        sep = "" if not d.text else (" " if spoken or d.kind.startswith("message") else "\n")
        s0 = len(d.text) + len(sep)
        d.text += sep + sentence
        if fact:
            d.spans.append(Span(fact.id, s0, s0 + len(sentence), role))
            if fact.id not in d.fact_ids:
                d.fact_ids.append(fact.id)

    days = sorted({m.day for m in plan} | set(traps_by_day))
    for day in days:
        todays = [m for m in plan if m.day == day]
        # photos and documents: one deposit each
        for m in [m for m in todays if m.channel == "photo"]:
            v = m.fact.value
            d = new("photo", day, w.owner, hour=v["time"])
            d.text = (f"Photo taken on {day.isoformat()} at {v['time']}. "
                      f"GPS: {v['lat']:.5f}, {v['lon']:.5f}.")
            d.spans.append(Span(m.fact.id, 0, len(d.text), "mention"))
            d.fact_ids.append(m.fact.id)
            d.meta = {"lat": v["lat"], "lon": v["lon"], "time": v["time"]}
            if (t := photo_traps.get(m.fact.id)):
                d.trap_ids.append(t.id)
        for m in [m for m in todays if m.channel == "document"]:
            f = m.fact
            d = new("document", day, "", hour=f"{r.randint(9, 17):02d}:00")
            if f.predicate == "lives_at":
                rent = next((x for x in w.facts if x.predicate == "pays_rent"
                             and x.valid_from == f.valid_from), None)
                d.text, d.meta = lease_document(w, f, rent, landlord)
                facts = [f] + ([rent] if rent else [])
            elif f.predicate == "works_at":
                d.text, d.meta = offer_document(w, f)
                facts = [f]
            elif f.predicate == "health":
                d.text, d.meta = clinic_document(w, f, clinic)
                facts = [f]
            else:
                d.text, d.meta = race_document(w, f)
                facts = [f]
            for x in facts:
                key = {"lives_at": "Premises:", "pays_rent": "Monthly rent:",
                       "works_at": "position of", "health": "Assessment:",
                       "race": "Official time:"}[x.predicate]
                i = d.text.index(key)
                j = d.text.find("\n", i)
                j = len(d.text) if j < 0 else j
                d.spans.append(Span(x.id, d.text.rfind("\n", 0, i) + 1, j,
                                    "future" if m.role == "future" else "mention"))
                d.fact_ids.append(x.id)
        # incoming messages: one per (speaker, day)
        incoming = [m for m in todays if m.channel == "incoming"]
        for pid in sorted({m.fact.subject for m in incoming}):
            p = w.person(pid)
            kind = "voice_in" if r.random() < 0.5 else "message_in"
            d = new(kind, day, pid, recipient=w.owner)
            d.meta = {"voice": p.voice} if kind == "voice_in" else {}
            sp = speaker(pid)
            append(d, r.choice(["Hey!", "Hi you,", "Quick update."]), None,
                   spoken=kind == "voice_in")
            for m in [m for m in incoming if m.fact.subject == pid]:
                append(d, sp.sentence(m.fact, m.role, m.when), m.fact, m.role,
                       spoken=kind == "voice_in")
            append(d, r.choice(["Talk soon.", "Miss you!", "Call me this weekend?"]), None,
                   spoken=kind == "voice_in")
        # owner deposits: 1-2 per day, note / voice / message
        own = [m for m in todays if m.channel == "owner"]
        traps = traps_by_day.get(day, [])
        if not own and not traps:
            continue
        n = 1 if len(own) <= 2 else 2
        groups = [own[i::n] for i in range(n)]
        sp = speaker(w.owner)
        for gi, group in enumerate(groups):
            kind = r.choice(["note", "note", "voice", "message"])
            others = [p for p in w.people if p.id != w.owner]
            recipient = r.choice(others).id if kind == "message" else None
            d = new(kind, day, w.owner, recipient=recipient)
            if kind == "voice":
                d.meta = {"voice": w.person(w.owner).voice}
            spoken = kind == "voice"
            items: list = [("f", m) for m in group]
            if gi == 0:
                items += [("t", t) for t in traps]
            items.append(("x", r.choice(FILLER)))
            r.shuffle(items)
            for tag, it in items:
                if tag == "f":
                    append(d, sp.sentence(it.fact, it.role, it.when), it.fact, it.role, spoken)
                elif tag == "t":
                    s0 = len(d.text) + (1 if d.text else 0)
                    append(d, it.sentence, None, spoken=spoken)
                    d.trap_ids.append(it.id)
                    d.meta.setdefault("trap_spans", []).append([it.id, s0, len(d.text)])
                else:
                    append(d, it, None, spoken=spoken)

    deposits.sort(key=lambda d: (d.created_at, d.kind, d.author))
    ext = {"note": "txt", "message": "txt", "message_in": "txt", "voice": "m4a",
           "voice_in": "m4a", "photo": "jpg", "document": "pdf"}
    for i, d in enumerate(deposits, 1):
        d.id = f"D{i:04d}"
        d.file = f"deposits/{d.id}_{d.kind}.{ext[d.kind]}"
    _ = start
    return deposits


def deposit_dicts(deposits: list[Deposit]) -> list[dict]:
    return [asdict(d) for d in deposits]


def as_datetime(d: Deposit) -> datetime:
    return datetime.fromisoformat(d.created_at)
