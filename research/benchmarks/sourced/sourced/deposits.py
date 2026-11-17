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

try:
    from . import phrasing as P
except ImportError:  # the held-out wordings are kept private (see README)
    P = None
from . import phrasing_dev2 as P2
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

# "dev" wording is inline below; every other phrasing renders the dev skeleton
# with the templates of its own module, drawn from its own stream
PHRASINGS = ("dev", "test", "dev2")
class _Private:
    """Stands in for the held-out wordings when they are not shipped: dev and
    dev2 sets generate byte for byte the same; asking for one raises."""

    def __getattr__(self, name):
        if name.endswith("_TEST"):
            return []  # evaluated, then discarded, outside the held-out phrasing

        def private(*_, **__):
            raise RuntimeError("the held-out wordings (sourced/phrasing.py) are private")
        return private


if P is None:
    P = _Private()
_MODULES = {"test": P, "dev2": P2}
# offset of the wording streams: 0 keeps `test` exactly as it was
_SALT = {"dev": 0, "test": 0, "dev2": 1_000_003}


def _module(phrasing: str):
    """Templates of a phrasing. Under "dev" the held-out module is returned
    only because some call sites evaluate its constants before discarding
    them (`say`); no dev wording ever comes from it."""
    if phrasing == "test" and isinstance(P, _Private):
        raise RuntimeError("the held-out wordings (sourced/phrasing.py) are private")
    return _MODULES.get(phrasing, P)


@dataclass
class Span:
    fact_id: str
    start: int
    end: int
    role: str  # "mention" | "start" | "end" | "future" | "not_yet" | "already"


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

def _earlier_people(w: World) -> list:
    """The people other than the owner, without those the coverage layer
    appends: earlier deposits draw recipients from this list, and must not
    move when the layer is on."""
    new = {x[k] for x in w.coverage for k in ("role_person", "name_person")}
    return [p for p in w.people if p.id != w.owner and p.id not in new]


def _first(w: World, pid: str) -> str:
    return w.person(pid).name.split()[0]


class Speaker:
    """Renders facts from one speaker's point of view, remembering whom it
    already introduced (first mention: "my sister Ana", then "Ana")."""

    def __init__(self, w: World, r: random.Random, speaker: str, phrasing: str = "dev",
                 pr: random.Random | None = None):
        self.w, self.r, self.speaker = w, r, speaker
        self.phrasing, self.pr = phrasing, pr
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
        return self.sentence_pair(f, role, when)[1]

    def sentence_pair(self, f: Fact, role: str, when: str) -> tuple[str, str]:
        """(dev sentence, sentence in this speaker's phrasing). The dev one is
        always rendered, so the dev random stream moves exactly as in dev;
        under `test` the introductions it made are rolled back and the test
        wording is drawn from the speaker's own phrasing stream."""
        before = set(self.introduced)
        dev = self._dev_sentence(f, role, when)
        if self.phrasing == "dev":
            return dev, dev
        self.introduced = before
        return dev, _module(self.phrasing).fact_sentence(self, f, role, when, self.pr)

    def _dev_sentence(self, f: Fact, role: str, when: str) -> str:
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
        if f.layer:  # identity-layer facts have deposits of their own
            continue
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


def build_deposits(w: World, seed: int | None = None, phrasing: str = "dev") -> list[Deposit]:
    """`phrasing="test"` renders the same deposits (same ids, times, authors,
    facts, traps, span roles) with the held-out templates of `phrasing.py`;
    `phrasing="dev2"` does the same with the second development templates of
    `phrasing_dev2.py`."""
    if phrasing not in PHRASINGS:
        raise ValueError(f"unknown phrasing {phrasing!r}")
    test = phrasing != "dev"  # any held-out-style phrasing (test, dev2)
    P = _module(phrasing)  # noqa: N806 (the module of that phrasing)
    r = random.Random((seed if seed is not None else w.seed) * 7919 + 1)
    # test wordings draw from their own stream: the dev stream `r` is consumed
    # exactly as in dev, so the deposit skeleton does not move
    pr = random.Random((seed if seed is not None else w.seed) * 7919 + 4099 + _SALT[phrasing])
    plan = _plan(w, r)
    start = date.fromisoformat(w.start)
    speakers: dict[str, Speaker] = {}
    landlord = f"{r.choice(['Ash', 'Birch', 'Elm', 'Rowan'])} Property Lettings"
    clinic = f"{r.choice(['Northgate', 'Riverside', 'Parkview'])} Medical Practice"
    deposits: list[Deposit] = []
    traps_by_day: dict[date, list[Trap]] = {}
    for t in w.traps:
        if t.kind not in ("photo_content", "attribution", "poison"):  # own layers
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
            speakers[pid] = Speaker(w, r, pid, phrasing, pr)
        return speakers[pid]

    def append(d: Deposit, sentence: str, fact: Fact | None, role: str = "mention",
               spoken: bool = False, dev: str | None = None,
               clauses: list[tuple] | None = None) -> None:
        """`dev`: the dev wording of `sentence` (test phrasing only), whose
        disfluent rendering is drawn and dropped to keep `r` in step.
        `clauses`: [(fact, role, start, end)] when one written sentence
        carries several facts (test phrasing, never spoken)."""
        if spoken:
            if test:
                disfluent(dev, r)
                sentence = P.disfluent(sentence, pr)
            else:
                sentence = disfluent(sentence, r)
        if not d.text:
            sep = ""
        elif spoken or d.kind.startswith("message"):
            sep = " "
        else:
            sep = pr.choice(["\n", "\n", " "]) if test else "\n"
        s0 = len(d.text) + len(sep)
        d.text += sep + sentence
        for f_, role_, a, b in clauses or ([(fact, role, 0, len(sentence))] if fact else []):
            d.spans.append(Span(f_.id, s0 + a, s0 + b, role_))
            if f_.id not in d.fact_ids:
                d.fact_ids.append(f_.id)

    days = sorted({m.day for m in plan} | set(traps_by_day))
    for day in days:
        todays = [m for m in plan if m.day == day]
        # photos and documents: one deposit each
        for m in [m for m in todays if m.channel == "photo"]:
            v = m.fact.value
            d = new("photo", day, w.owner, hour=v["time"])
            d.text = P.photo_text(day.isoformat(), v) if test else (
                f"Photo taken on {day.isoformat()} at {v['time']}. "
                f"GPS: {v['lat']:.5f}, {v['lon']:.5f}.")
            d.spans.append(Span(m.fact.id, 0, len(d.text), "mention"))
            d.fact_ids.append(m.fact.id)
            d.meta = {"lat": v["lat"], "lon": v["lon"], "time": v["time"]}
            if (t := photo_traps.get(m.fact.id)):
                d.trap_ids.append(t.id)
        for m in [m for m in todays if m.channel == "document"]:
            f = m.fact
            d = new("document", day, "", hour=f"{r.randint(9, 17):02d}:00")
            keys = {"lives_at": "Premises:", "pays_rent": "Monthly rent:",
                    "works_at": "position of", "health": "Assessment:",
                    "race": "Official time:"}
            owner_name = w.person(f.subject).name
            if f.predicate == "lives_at":
                rent = next((x for x in w.facts if x.predicate == "pays_rent"
                             and x.valid_from == f.valid_from), None)
                if test:
                    d.text, d.meta, keys = P.lease_document(owner_name, f, rent, landlord)
                else:
                    d.text, d.meta = lease_document(w, f, rent, landlord)
                facts = [f] + ([rent] if rent else [])
            elif f.predicate == "works_at":
                if test:
                    d.text, d.meta, keys = P.offer_document(owner_name, f)
                else:
                    d.text, d.meta = offer_document(w, f)
                facts = [f]
            elif f.predicate == "health":
                if test:
                    d.text, d.meta, keys = P.clinic_document(owner_name, f, clinic)
                else:
                    d.text, d.meta = clinic_document(w, f, clinic)
                facts = [f]
            else:
                if test:
                    d.text, d.meta, keys = P.race_document(owner_name, f)
                else:
                    d.text, d.meta = race_document(w, f)
                facts = [f]
            for x in facts:
                key = keys[x.predicate]
                i = d.text.index(key)
                j = d.text.find("\n", i)
                j = len(d.text) if j < 0 else j
                d.spans.append(Span(x.id, d.text.rfind("\n", 0, i) + 1, j,
                                    "future" if m.role == "future" else "mention"))
                d.fact_ids.append(x.id)

        def lines(d: Deposit, sp: Speaker, ms: list, spoken: bool) -> None:
            """Fact sentences in order; under `test`, in written deposits, two
            consecutive ones are sometimes joined into one sentence."""
            i = 0
            while i < len(ms):
                m = ms[i]
                # rendered one at a time: in dev, a voice memo draws its
                # hesitations between two sentences
                dev, s = sp.sentence_pair(m.fact, m.role, m.when)
                if test and not spoken and i + 1 < len(ms) and pr.random() < 0.5:
                    m2 = ms[i + 1]
                    s2 = sp.sentence_pair(m2.fact, m2.role, m2.when)[1]
                    joined, (a0, a1), (b0, b1) = P.join(s, s2, pr)
                    append(d, joined, None, clauses=[(m.fact, m.role, a0, a1),
                                                     (m2.fact, m2.role, b0, b1)])
                    i += 2
                    continue
                append(d, s, m.fact, m.role, spoken, dev=dev)
                i += 1

        def say(dev: str, options: list[str]) -> str:
            return pr.choice(options) if test else dev

        # incoming messages: one per (speaker, day)
        incoming = [m for m in todays if m.channel == "incoming"]
        for pid in sorted({m.fact.subject for m in incoming}):
            p = w.person(pid)
            kind = "voice_in" if r.random() < 0.5 else "message_in"
            d = new(kind, day, pid, recipient=w.owner)
            d.meta = {"voice": p.voice} if kind == "voice_in" else {}
            sp = speaker(pid)
            hello = r.choice(["Hey!", "Hi you,", "Quick update."])
            append(d, say(hello, P.GREETINGS_TEST), None, spoken=kind == "voice_in", dev=hello)
            lines(d, sp, [m for m in incoming if m.fact.subject == pid], kind == "voice_in")
            bye = r.choice(["Talk soon.", "Miss you!", "Call me this weekend?"])
            append(d, say(bye, P.SIGNOFFS_TEST), None, spoken=kind == "voice_in", dev=bye)
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
            others = _earlier_people(w)
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
            k = 0
            while k < len(items):
                tag, it = items[k]
                if tag == "f":  # a run of consecutive facts
                    run = [it]
                    while k + 1 < len(items) and items[k + 1][0] == "f":
                        k += 1
                        run.append(items[k][1])
                    lines(d, sp, run, spoken)
                elif tag == "t":
                    s0 = len(d.text) + (1 if d.text else 0)
                    append(d, P.trap_sentence(it.sentence, pr) if test else it.sentence, None,
                           spoken=spoken, dev=it.sentence)
                    d.trap_ids.append(it.id)
                    d.meta.setdefault("trap_spans", []).append([it.id, s0, len(d.text)])
                else:
                    append(d, say(it, P.FILLER_TEST), None, spoken=spoken, dev=it)
                k += 1

    deposits.sort(key=lambda d: (d.created_at, d.kind, d.author))
    ext = {"note": "txt", "message": "txt", "message_in": "txt", "voice": "m4a",
           "voice_in": "m4a", "photo": "jpg", "document": "pdf"}
    for i, d in enumerate(deposits, 1):
        d.id = f"D{i:04d}"
        d.file = f"deposits/{d.id}_{d.kind}.{ext[d.kind]}"
    _ = start
    # layer deposits are numbered AFTER the base ones (identity first, then
    # dating), so that earlier ids, and the media files named after them, do
    # not move; the list stays in time order
    layers = []
    if w.identity:
        layers.append(_identity_deposits(w, seed if seed is not None else w.seed, phrasing))
    if w.dating:
        layers.append(_dating_deposits(w, seed if seed is not None else w.seed, phrasing))
    if w.coverage:
        layers.append(_coverage_deposits(w, seed if seed is not None else w.seed, phrasing))
    if any(t.kind == "poison" for t in w.traps):
        layers.append(_poison_deposits(w, seed if seed is not None else w.seed, phrasing))
    n = len(deposits)
    for extra in layers:
        for i, d in enumerate(extra, n + 1):
            d.id = f"D{i:04d}"
            d.file = f"deposits/{d.id}_{d.kind}.{ext[d.kind]}"
        n += len(extra)
        deposits = deposits + extra
    return sorted(deposits, key=lambda d: d.created_at) if layers else deposits


def _identity_deposits(w: World, seed: int, phrasing: str = "dev") -> list[Deposit]:
    """Text deposits of the identity layer (never voice: the committed voice
    clips must keep their exact transcripts). Per target person:
      * the alias proof, the only deposit naming role and name together;
      * the role-only fact ("my sister works at …"), an attribution trap;
      * the name-only fact ("Priya joined …"), an attribution trap.
    Own random stream, so the base deposits are unchanged."""
    r = random.Random(seed * 7919 + 101)
    test = phrasing != "dev"
    P = _module(phrasing)  # noqa: N806
    pr = random.Random(seed * 7919 + 4201 + _SALT[phrasing])  # test wordings only
    traps = {t.id: t for t in w.traps}
    facts = {f.id: f for f in w.facts}
    out: list[Deposit] = []

    def at(day: str) -> str:
        return f"{day}T{r.randint(7, 22):02d}:{r.randint(0, 59):02d}:00"

    for x in w.identity:
        pid = x["person"]
        kind = r.choice(["note", "message"])
        d = Deposit("", kind, at(x["alias_day"]), w.owner,
                    x["contrast"] if kind == "message" else None, "")
        filler = r.choice(FILLER)
        alias = x["alias_sentence"]
        if test:
            p = w.person(pid)
            alias = P.alias_sentence(x["role"], p.name.split()[0], pr)
            filler = pr.choice(P.FILLER_TEST)
        d.text = alias + ("\n" if kind == "note" else " ") + filler
        d.meta = {"alias_spans": [[pid, 0, len(alias)]]}
        out.append(d)
        for fact_key, trap_key in (("role_fact", "role_trap"), ("name_fact", "name_trap")):
            t, f = traps[x[trap_key]], facts[x[fact_key]]
            d = Deposit("", "note", at(t.day), w.owner, None, "")
            lead = r.choice(FILLER)
            sentence = t.sentence
            if test:
                first = w.person(pid).name.split()[0]
                lead = pr.choice(P.FILLER_TEST)
                sentence = P.role_sentence(_first(w, x["contrast"]), x["role"],
                                           f.value["employer"], pr) \
                    if fact_key == "role_fact" else P.name_sentence(first, f.value["group"], pr)
            s0 = len(lead) + 1
            d.text = f"{lead}\n{sentence}"
            d.spans.append(Span(f.id, s0, s0 + len(sentence), "mention"))
            d.fact_ids.append(f.id)
            d.trap_ids.append(t.id)
            d.meta = {"trap_spans": [[t.id, s0, len(d.text)]]}
            out.append(d)
    return sorted(out, key=lambda d: d.created_at)


def _dating_deposits(w: World, seed: int, phrasing: str = "dev") -> list[Deposit]:
    """Text deposits of the dating layer (notes and messages, never voice).
    Per fact: on day A, "not yet" (span role `not_yet`: the fact is NOT
    stated as true there); on day B, "already" (role `already`). Neither
    gives the day the thing arrived. Own random stream."""
    r = random.Random(seed * 7919 + 211)
    test = phrasing != "dev"
    P = _module(phrasing)  # noqa: N806
    pr = random.Random(seed * 7919 + 4307 + _SALT[phrasing])  # test wordings only
    facts = {f.id: f for f in w.facts}
    others = _earlier_people(w)
    out: list[Deposit] = []

    def at(day: str) -> str:
        return f"{day}T{r.randint(7, 22):02d}:{r.randint(0, 59):02d}:00"

    for x in w.dating:
        f = facts[x["fact"]]
        item = f.value["item"]
        if f.subject == w.owner:
            not_yet = r.choice([f"The {item} I ordered has not arrived yet.",
                                f"Still waiting for the {item}, it is not here yet."])
            already = r.choice([f"The {item} is already here, I use it every day.",
                                f"Already got the {item} set up at home."])
        else:
            n = _first(w, f.subject)
            not_yet = r.choice([f"{n} has not got the {item} yet.",
                                f"{n} is still waiting for the {item}, not delivered yet."])
            already = r.choice([f"{n} already has the {item}, it looks great.",
                                f"{n} has had the {item} for a while already."])
        if test:
            not_yet, already = P.dating_sentences(f.subject == w.owner, _first(w, f.subject),
                                                  item, pr)
        for day, sentence, role in ((x["not_yet_day"], not_yet, "not_yet"),
                                    (x["already_day"], already, "already")):
            kind = r.choice(["note", "note", "message"])
            to = r.choice([p.id for p in others if p.id != f.subject] or [None]) \
                if kind == "message" else None
            d = Deposit("", kind, at(day), w.owner, to, "")
            lead = r.choice(FILLER)
            if test:
                lead = pr.choice(P.FILLER_TEST)
            sep = "\n" if kind == "note" else " "
            s0 = len(lead) + len(sep)
            d.text = f"{lead}{sep}{sentence}"
            d.spans.append(Span(f.id, s0, s0 + len(sentence), role))
            d.fact_ids.append(f.id)
            out.append(d)
    return sorted(out, key=lambda d: d.created_at)


def _coverage_deposits(w: World, seed: int, phrasing: str = "dev") -> list[Deposit]:
    """Text notes of the coverage layer: each attribute of a role/name pair
    in its own deposit, by role OR by name, never both; plus, for the
    `together` decoy, one deposit with the two at lunch. Own random stream."""
    r = random.Random(seed * 7919 + 307)
    test = phrasing != "dev"
    P = _module(phrasing)  # noqa: N806
    pr = random.Random(seed * 7919 + 4409 + _SALT[phrasing])  # test wordings only
    facts = {f.id: f for f in w.facts}
    out: list[Deposit] = []

    def note(day: str, sentence: str, f: Fact | None) -> Deposit:
        d = Deposit("", "note", f"{day}T{r.randint(7, 22):02d}:{r.randint(0, 59):02d}:00",
                    w.owner, None, "")
        lead = r.choice(FILLER)
        if test:
            lead = pr.choice(P.FILLER_TEST)
        s0 = len(lead) + 1
        d.text = f"{lead}\n{sentence}"
        if f:
            d.spans.append(Span(f.id, s0, s0 + len(sentence), "mention"))
            d.fact_ids.append(f.id)
        out.append(d)
        return d

    for x in w.coverage:
        role = x["role"]
        name = w.person(x["name_person"]).name.split()[0]
        for m in x["mentions"]:
            f = facts[m["fact"]]
            who = role[0].upper() + role[1:] if m["by_role"] else name
            v = f.value
            if f.predicate == "based_in":
                s = f"{who} lives in {v['city']} now." if m["by_role"] else \
                    f"{who} lives in {v['city']}, near the harbour."
            elif f.predicate == "employer":
                s = f"{who} works at {v['employer']}." if m["by_role"] else \
                    f"Ran into {who}, who works at {v['employer']}."
            else:
                s = f"{who} works from {v['where']} most days."
            if test:
                s = P.coverage_sentence(f.predicate, m["by_role"], role, name, v, pr)
            note(m["day"], s, f)
        if x["together_day"]:
            lunch = f"Lunch with {role} and {name} today."
            if test:
                lunch = P.together_sentence(role, name, pr)
            d = note(x["together_day"], lunch, None)
            d.meta = {"together": [x["role_person"], x["name_person"]]}
    return sorted(out, key=lambda d: d.created_at)


def deposit_dicts(deposits: list[Deposit]) -> list[dict]:
    return [asdict(d) for d in deposits]


def as_datetime(d: Deposit) -> datetime:
    return datetime.fromisoformat(d.created_at)


def _poison_deposits(w: World, seed: int, phrasing: str = "dev") -> list[Deposit]:
    """Deposits of the poison layer: the injection and the repeated notice
    as documents (no author), the false congratulation as a message from a
    friend. Text only. Own random stream.

    Development wordings only: a held-out set needs poison sentences written
    blind, which do not exist yet."""
    if phrasing != "dev":
        raise NotImplementedError("poison layer: no held-out wordings yet")
    r = random.Random(seed * 7919 + 503)
    out: list[Deposit] = []
    for t in (t for t in w.traps if t.kind == "poison"):
        for day in t.days:
            at = f"{day}T{r.randint(8, 21):02d}:{r.randint(0, 59):02d}:00"
            if t.author:
                d = Deposit("", "message_in", at, t.author, w.owner, "")
                lead, tail = r.choice(["Hey!", "Hi you,"]), r.choice(["Talk soon.", "Drinks soon?"])
            else:
                d = Deposit("", "document", at, "", None, "")
                d.meta = {"doc_type": "notice"}
                lead = r.choice(["Community newsletter, shared notes.",
                                 "Automated message from a service you used."])
                tail = r.choice(["Unsubscribe at any time.", "This message was sent automatically."])
            s0 = len(lead) + 1
            d.text = f"{lead}\n{t.sentence}\n{tail}"
            d.trap_ids.append(t.id)
            d.meta.setdefault("trap_spans", []).append([t.id, s0, s0 + len(t.sentence)])
            out.append(d)
    out.sort(key=lambda d: d.created_at)
    return out
