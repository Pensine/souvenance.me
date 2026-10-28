"""Truth first: a synthetic life, generated before any deposit is written.

Everything downstream (deposits, tasks, gold evidence spans) is derived from
the `World` built here. Nothing is ever extracted back from rendered text, so
the gold standard cannot inherit the errors of a model.

Determinism: one `random.Random(seed)` drives every choice; no set iteration,
no wall clock, no hashing of Python objects. Same seed + same parameters =
byte-identical `truth.json`.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

# --- pools -----------------------------------------------------------------
# Real cities (public coordinates, city-centre level) give real GPS for photo
# EXIF; every organisation, street and person is fictional.

FIRST_NAMES = [
    "Maya", "Jonah", "Iris", "Theo", "Lena", "Owen", "Nadia", "Felix", "Clara", "Ravi",
    "Elsa", "Marco", "Hana", "Lucas", "Amara", "Tomas", "Ines", "Kofi", "Greta", "Samir",
    "Zoe", "Anton", "Leila", "Hugo", "Mira", "Dev", "Noor", "Pablo", "Freya", "Yusuf",
    "Alba", "Ezra", "Sana", "Milo", "Ruth", "Kenji", "Dalia", "Oskar", "Talia", "Emeka",
    "Bea", "Cyrus", "Dora", "Elias", "Fatima", "Gideon", "Hollis", "Ida", "Joaquin", "Kaia",
    "Linus", "Maren", "Nico", "Odile", "Priya", "Quinn", "Rosa", "Silas", "Tess", "Umar",
    "Vera", "Wes", "Ximena", "Yara", "Zane", "Aurelio", "Bianca", "Cormac", "Dina", "Edgar",
    "Flora", "Gus", "Hedda", "Ivo", "June", "Kasper", "Lotte", "Matteo", "Nell", "Orla",
]
SURNAMES = [
    "Collins", "Varga", "Okafor", "Lindqvist", "Moreau", "Brennan", "Haddad", "Novak",
    "Castillo", "Fischer", "Mensah", "Ishikawa", "Rossi", "Kowalski", "Duarte", "Abbott",
    "Sorensen", "Petrov", "Achebe", "Delacroix",
]
CITIES = [  # name, lat, lon
    ("Lyon", 45.7640, 4.8357), ("Bristol", 51.4545, -2.5879), ("Porto", 41.1579, -8.6291),
    ("Leipzig", 51.3397, 12.3731), ("Ghent", 51.0543, 3.7174), ("Turin", 45.0703, 7.6869),
    ("Valencia", 39.4699, -0.3763), ("Edinburgh", 55.9533, -3.1883),
    ("Gothenburg", 57.7089, 11.9746), ("Bordeaux", 44.8378, -0.5792),
    ("Rotterdam", 51.9244, 4.4777), ("Montreal", 45.5019, -73.5674),
]
STREETS = [
    "Linden Street", "Quarry Lane", "Harbour Row", "Mill Road", "Juniper Avenue",
    "Saltmarsh Way", "Orchard Close", "Tanner Street", "Beacon Hill Road", "Kiln Lane",
]
EMPLOYERS = [
    "Northwind Analytics", "Kestrel Logistics", "Bramble Health", "Oakline Software",
    "Copperleaf Books", "Harbor & Pine Studio", "Silverfern Energy", "Lumen Robotics",
    "Wrenfield Architects", "Bluecairn Foods",
]
JOB_TITLES = [
    "data analyst", "product designer", "logistics coordinator", "backend engineer",
    "editor", "project manager", "research assistant", "UX researcher", "sales lead",
    "operations manager",
]
HOBBIES = ["pottery", "bouldering", "Spanish lessons", "sourdough baking", "cello",
           "trail running", "life drawing", "open-water swimming"]
CONDITIONS = [  # benign only
    ("a sprained left ankle", "physiotherapy twice a week"),
    ("tennis elbow", "a forearm brace and rest"),
    ("a bad chest cold", "rest and fluids"),
    ("mild tendinitis in the right wrist", "an ice pack and a wrist splint"),
    ("an ear infection", "a seven-day course of antibiotics"),
]
PROJECTS = ["a podcast about urban gardening", "a board game prototype",
            "a houseplant-tracking app", "a zine of family recipes",
            "a short documentary about the river"]
PROJECT_STAGES = ["planning", "building", "launched"]
FOODS = ["peanuts", "shellfish", "kiwi", "sesame"]
LANGUAGES = ["Portuguese", "German", "Japanese", "Italian", "Swedish", "Arabic"]
PET_KINDS = ["cat", "dog"]
PET_NAMES = ["Biscuit", "Pepper", "Juno", "Mochi", "Ziggy", "Olive", "Otis", "Nori"]
COMMUTES = ["by bike", "by tram", "on foot", "by bus"]
GYMS = ["Ironbark Gym", "Cedar Climbing Hall", "Riverside Pool Club"]
VENUES = ["the riverside park", "the old market hall", "the botanical garden",
          "the harbour footpath", "the hilltop viewpoint", "the city library"]
RACES = ["Spring 10K", "Harbour Half Marathon", "Park 5K"]
RACE_MINUTES = {"Spring 10K": (42, 70), "Harbour Half Marathon": (95, 150), "Park 5K": (19, 34)}
# Piper voices trained only on public-domain speech (SPEC section 9). The
# list length matters: the owner draws with r.choice over all five and the
# partner over the four others, which keeps the random stream unchanged.
VOICES = ["en_US-ljspeech-medium", "en_US-kristin-medium", "en_US-norman-medium",
          "en_US-john-medium", "en_GB-cori-medium"]
RELATIONS = ["sister", "brother", "best friend", "friend", "colleague", "cousin",
             "neighbour", "manager"]


# --- data model ------------------------------------------------------------

@dataclass
class Person:
    id: str
    name: str
    relation: str  # "self" for the owner, else relation to the owner
    voice: str = ""  # TTS voice for deposits spoken by this person


@dataclass
class Fact:
    """One atomic, checkable statement with its validity interval.

    `valid_to` is exclusive and None while the fact is still true at the end
    of the window. `slot` groups the versions of a changing attribute
    (subject + predicate); `supersedes` points at the version it replaced.
    """
    id: str
    subject: str           # person id
    predicate: str
    value: dict            # structured object, predicate-specific
    valid_from: str        # ISO date; may precede the window (background fact)
    valid_to: str | None
    kind: str              # "state" | "event"
    slot: str
    version: int = 0
    supersedes: str | None = None
    since_stated: bool = False  # does a deposit state valid_from explicitly?
    canonical: str = ""    # third-person English sentence (gold paraphrase)
    answer: str = ""       # short answer string used by QA


@dataclass
class Trap:
    """A sentence that must NOT become a memory as stated.

    `forbidden` is the false claim a careless writer would store; `kind` is
    plan | hypothetical | negation | hearsay | photo_content.
    """
    id: str
    kind: str
    subject: str
    day: str
    sentence: str
    forbidden: str
    question: str = ""     # an abstention question this trap licenses
    fact_id: str = ""      # photo traps: the visit the photo documents


@dataclass
class World:
    seed: int
    start: str
    days: int
    owner: str
    people: list[Person] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    traps: list[Trap] = field(default_factory=list)
    unstated: list[dict] = field(default_factory=list)  # slots never mentioned

    def person(self, pid: str) -> Person:
        return next(p for p in self.people if p.id == pid)

    def to_dict(self) -> dict:
        return asdict(self)


def article(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def count_changes(facts: list["Fact"], start: str) -> int:
    """A change = a new version of a slot, or a state that begins inside the
    window (onset of a condition, start of a relationship)."""
    return sum(1 for f in facts if f.supersedes or (f.kind == "state" and f.valid_from >= start))


def _d(x: date) -> str:
    return x.isoformat()


def _month_year(x: date) -> str:
    return x.strftime("%B %Y")


# --- generation ------------------------------------------------------------

class _Builder:
    def __init__(self, seed: int, start: date, days: int):
        self.r = random.Random(seed)
        self.start, self.days = start, days
        self.end = start + timedelta(days=days)  # exclusive
        self.facts: list[Fact] = []
        self.people: list[Person] = []
        self.used_names: list[str] = []

    # helpers
    def name(self) -> str:
        if len(self.used_names) >= len(FIRST_NAMES):
            raise ValueError("not enough distinct first names: lower n_facts")
        while True:
            n = f"{self.r.choice(FIRST_NAMES)} {self.r.choice(SURNAMES)}"
            first = n.split()[0]
            if all(u.split()[0] != first for u in self.used_names):
                self.used_names.append(n)
                return n

    def day_in(self, lo: int = 0, hi: int | None = None) -> date:
        hi = self.days - 1 if hi is None else hi
        return self.start + timedelta(days=self.r.randint(lo, max(lo, hi)))

    def background(self) -> date:
        return self.start - timedelta(days=self.r.randint(120, 1500))

    def add(self, subject, predicate, value, valid_from, valid_to=None, kind="state",
            version=0, supersedes=None, since_stated=False) -> Fact:
        f = Fact(id=f"F{len(self.facts) + 1:03d}", subject=subject, predicate=predicate,
                 value=value, valid_from=_d(valid_from),
                 valid_to=_d(valid_to) if valid_to else None, kind=kind,
                 slot=f"{subject}:{predicate}", version=version, supersedes=supersedes,
                 since_stated=since_stated)
        self.facts.append(f)
        return f

    def chain(self, subject, predicate, values: list[dict], change_days: list[date],
              first_from: date, since_stated: bool) -> list[Fact]:
        """A changing slot: len(values) versions, len(values)-1 changes."""
        out, prev = [], None
        bounds = [first_from] + change_days
        for i, v in enumerate(values):
            vt = bounds[i + 1] if i + 1 < len(bounds) else None
            f = self.add(subject, predicate, v, bounds[i], vt, version=i,
                         supersedes=prev.id if prev else None,
                         since_stated=since_stated if i == 0 else True)
            out.append(f)
            prev = f
        return out


def generate_world(seed: int = 7, start: str = "2025-02-03", days: int = 182,
                   n_facts: int = 300, n_changes: int = 40) -> World:
    """Build a life. `n_facts`/`n_changes` are targets; the result is within a
    few units (changes come in whole chains)."""
    b = _Builder(seed, date.fromisoformat(start), days)
    r = b.r
    owner = Person("P0", b.name(), "self", voice=r.choice(VOICES))
    b.people.append(owner)
    home_city = r.choice(CITIES)
    other_cities = [c for c in CITIES if c != home_city]
    r.shuffle(other_cities)

    # --- changing slots of the owner, in priority order -------------------
    changes_left = n_changes
    margin = max(1, days // 10)

    def change_days(k: int) -> list[date]:
        ds = sorted({b.day_in(margin, days - margin) for _ in range(k * 3)})
        r.shuffle(ds)
        return sorted(ds[:k])

    # home (move): 1 change, 2 on long windows with a large budget
    k = (2 if n_changes >= 20 and days >= 90 else 1) if changes_left >= 1 else 0
    homes = [{"street": f"{r.randint(2, 96)} {r.choice(STREETS)}", "city": home_city[0]}]
    for i in range(k):
        homes.append({"street": f"{r.randint(2, 96)} {r.choice(STREETS)}",
                      "city": other_cities[i][0] if r.random() < 0.6 else home_city[0]})
    b.chain("P0", "lives_at", homes, change_days(k), b.background(), r.random() < 0.6)
    changes_left -= k
    rents = [{"amount": r.randrange(650, 1400, 10), "currency": "EUR"} for _ in homes]
    home_facts = [f for f in b.facts if f.predicate == "lives_at"]
    b.chain("P0", "pays_rent", rents, [date.fromisoformat(f.valid_from) for f in home_facts[1:]],
            date.fromisoformat(home_facts[0].valid_from), False)
    changes_left -= len(rents) - 1

    # job: 1 change, 2 on long windows with a large budget
    k = (2 if changes_left >= 20 and days >= 90 else 1) if changes_left >= 1 else 0
    emps = r.sample(EMPLOYERS, k + 1)
    jobs = [{"employer": e, "title": t} for e, t in zip(emps, r.sample(JOB_TITLES, k + 1))]
    b.chain("P0", "works_at", jobs, change_days(k), b.background(), r.random() < 0.7)
    changes_left -= k

    # health: benign condition with onset and recovery inside the window
    if changes_left >= 1:
        cond, care = r.choice(CONDITIONS)
        onset = b.day_in(margin, days - 3 * margin)
        rec = onset + timedelta(days=r.randint(5, max(6, min(30, days // 3))))
        rec = min(rec, b.end - timedelta(days=1))
        b.add("P0", "health", {"condition": cond, "care": care}, onset, rec)
        changes_left -= 1

    # relationship: starts dating someone
    partner = None
    if changes_left >= 1:
        partner = Person(f"P{len(b.people)}", b.name(), "partner",
                         voice=r.choice([v for v in VOICES if v != owner.voice]))
        b.people.append(partner)
        b.add("P0", "dating", {"person": partner.id, "name": partner.name},
              b.day_in(margin, days - margin))
        changes_left -= 1

    # project: stages planning -> building -> launched (2 changes)
    if changes_left >= 2:
        proj = r.choice(PROJECTS)
        stages = [{"project": proj, "stage": s} for s in PROJECT_STAGES]
        b.chain("P0", "project", stages, change_days(2), b.day_in(0, margin), True)
        changes_left -= 2

    optional_owner_chains = [
        ("commutes", lambda: [{"mode": m} for m in r.sample(COMMUTES, 2)]),
        ("hobby", lambda: [{"hobby": h} for h in r.sample(HOBBIES, 2)]),
        ("gym", lambda: [{"gym": g} for g in r.sample(GYMS, 2)]),
    ]
    for pred, mk in optional_owner_chains:
        if changes_left < 1:
            break
        b.chain("P0", pred, mk(), change_days(1), b.background(), False)
        changes_left -= 1

    # --- static owner facts ------------------------------------------------
    bday = date(1985 + r.randint(0, 15), r.randint(1, 12), r.randint(1, 28))
    b.add("P0", "birthday", {"date": bday.isoformat()}, bday)
    b.add("P0", "hometown", {"city": other_cities[-1][0]}, bday)
    b.add("P0", "allergy", {"food": r.choice(FOODS)}, b.background())
    b.add("P0", "speaks", {"language": r.choice(LANGUAGES)}, b.background())
    pet_kind = r.choice(PET_KINDS)
    has_pet = r.random() < 0.5
    if has_pet:
        b.add("P0", "pet", {"kind": pet_kind, "name": r.choice(PET_NAMES)}, b.background())

    # --- other people: each brings 2-4 facts, some change ------------------
    def person_facts(p: Person) -> None:
        nonlocal changes_left
        city = r.choice(CITIES)
        if changes_left >= 1 and r.random() < 0.6:
            new = r.choice([c for c in CITIES if c != city])
            b.chain(p.id, "lives_in", [{"city": city[0]}, {"city": new[0]}],
                    change_days(1), b.background(), False)
            changes_left -= 1
        else:
            b.add(p.id, "lives_in", {"city": city[0]}, b.background())
        if r.random() < 0.7:
            b.add(p.id, "job", {"title": r.choice(JOB_TITLES)}, b.background())
        if r.random() < 0.4:
            b.add(p.id, "pet", {"kind": r.choice(PET_KINDS), "name": r.choice(PET_NAMES)},
                  b.background())
        if r.random() < 0.3:
            bd = date(1980 + r.randint(0, 20), r.randint(1, 12), r.randint(1, 28))
            b.add(p.id, "birthday", {"date": bd.isoformat()}, bd)

    if partner:
        b.add(partner.id, "job", {"title": r.choice(JOB_TITLES)}, b.background())

    voices = [v for v in VOICES if v != owner.voice]  # the owner's voice stays theirs
    rel_cycle = list(RELATIONS)
    # events + people fill the remaining budget; keep ~45 % of facts as events
    event_target = int(n_facts * 0.45)
    while len(b.facts) < n_facts - event_target:
        rel = rel_cycle[(len(b.people) - 1) % len(rel_cycle)]
        p = Person(f"P{len(b.people)}", b.name(), rel, voice=voices[len(b.people) % len(voices)])
        b.people.append(p)
        person_facts(p)

    # --- events: point facts inside the window ------------------------------
    others = [p for p in b.people if p.id != "P0"]
    while len(b.facts) < n_facts:
        roll = r.random()
        day = b.day_in()
        if roll < 0.35:   # visit a place, documented by a photo (GPS + time only)
            here = next(f.value["city"] for f in b.facts if f.predicate == "lives_at"
                        and f.valid_from <= _d(day) and (f.valid_to is None or _d(day) < f.valid_to))
            city = next(c for c in CITIES if c[0] == here) if r.random() < 0.7 \
                else r.choice(other_cities[:4])
            b.add("P0", "visited", {"venue": r.choice(VENUES), "city": city[0],
                                    "lat": round(city[1] + r.uniform(-0.02, 0.02), 5),
                                    "lon": round(city[2] + r.uniform(-0.02, 0.02), 5),
                                    "time": f"{r.randint(8, 19):02d}:{r.randint(0, 59):02d}"},
                  day, kind="event")
        elif roll < 0.6:  # met someone
            p = r.choice(others)
            b.add("P0", "met", {"person": p.id, "name": p.name, "venue": r.choice(VENUES)},
                  day, kind="event")
        elif roll < 0.72:
            race = r.choice(RACES)
            lo, hi = RACE_MINUTES[race]
            m = r.randint(lo, hi)
            t = f"{m // 60}:{m % 60:02d}:{r.randint(0, 59):02d}" if m >= 60 else f"{m}:{r.randint(0, 59):02d}"
            b.add("P0", "race", {"race": race, "time": t}, day, kind="event")
        elif roll < 0.86:
            b.add("P0", "appointment", {"what": r.choice(["dentist", "optician", "GP check-up",
                                                          "haircut", "bank adviser"])},
                  day, kind="event")
        else:
            p = r.choice(others)
            b.add(p.id, "news", {"what": r.choice(["got engaged", "adopted a puppy",
                                                   "passed a driving test",
                                                   "started a new course",
                                                   "ran a first marathon"])},
                  day, kind="event")

    world = World(seed=seed, start=start, days=days, owner="P0", people=b.people,
                  facts=b.facts)
    for f in world.facts:
        f.canonical, f.answer = canonical(world, f)
    world.traps = _traps(b, world, has_pet, pet_kind)
    world.unstated = _unstated(world, has_pet)
    return world


# --- canonical sentences ---------------------------------------------------

def _human_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def canonical(w: World, f: Fact) -> tuple[str, str]:
    n = w.person(f.subject).name
    v = f.value
    on = _human_date(f.valid_from)
    match f.predicate:
        case "lives_at":
            return f"{n} lives at {v['street']}, {v['city']}.", f"{v['street']}, {v['city']}"
        case "pays_rent":
            return f"{n} pays {v['amount']} {v['currency']} a month in rent.", f"{v['amount']} {v['currency']}"
        case "works_at":
            return f"{n} works as {article(v['title'])} at {v['employer']}.", v["employer"]
        case "health":
            return f"{n} had {v['condition']}, treated with {v['care']}.", v["condition"]
        case "dating":
            return f"{n} is dating {v['name']}.", v["name"]
        case "project":
            return f"{n}'s project, {v['project']}, is at the {v['stage']} stage.", v["stage"]
        case "commutes":
            return f"{n} commutes {v['mode']}.", v["mode"]
        case "hobby":
            return f"{n}'s main hobby is {v['hobby']}.", v["hobby"]
        case "gym":
            return f"{n} is a member of {v['gym']}.", v["gym"]
        case "birthday":
            d = date.fromisoformat(v["date"])
            return f"{n}'s birthday is on {d.day} {d.strftime('%B')}.", f"{d.day} {d.strftime('%B')}"
        case "hometown":
            return f"{n} grew up in {v['city']}.", v["city"]
        case "allergy":
            return f"{n} is allergic to {v['food']}.", v["food"]
        case "speaks":
            return f"{n} speaks {v['language']}.", v["language"]
        case "pet":
            return f"{n} has a {v['kind']} named {v['name']}.", v["name"]
        case "lives_in":
            return f"{n} lives in {v['city']}.", v["city"]
        case "job":
            return f"{n} works as {article(v['title'])}.", v["title"]
        case "visited":
            return f"{n} was in {v['city']} on {on}.", v["city"]
        case "met":
            return f"{n} met {v['name']} at {v['venue']} on {on}.", v["venue"]
        case "race":
            return f"{n} ran the {v['race']} on {on} in {v['time']}.", v["time"]
        case "appointment":
            return f"{n} had a {v['what']} appointment on {on}.", on
        case "news":
            return f"{n} {v['what']} around {on}.", v["what"]
    raise ValueError(f.predicate)


# --- traps and never-stated slots -----------------------------------------

def _traps(b: _Builder, w: World, has_pet: bool, pet_kind: str) -> list[Trap]:
    r = b.r
    owner = w.person("P0").name
    first = owner.split()[0]
    traps: list[Trap] = []
    lives = [f for f in w.facts if f.predicate == "lives_at"]
    cities_lived = {f.value["city"] for f in lives}
    dream_city = r.choice([c[0] for c in CITIES if c[0] not in cities_lived])
    others = [p for p in w.people if p.id != "P0"]

    def add(kind, subject, sentence, forbidden, question=""):
        traps.append(Trap(f"T{len(traps) + 1:02d}", kind, subject, _d(b.day_in()),
                          sentence, forbidden, question))

    add("hypothetical", "P0",
        f"If the {dream_city} offer ever comes through, I'd honestly move there in a heartbeat.",
        f"{owner} moved to {dream_city}.", f"When did {first} move to {dream_city}?")
    if not has_pet:
        other_kind = "dog" if pet_kind == "cat" else "cat"
        add("plan", "P0", f"I keep thinking about adopting a {other_kind}, maybe next year.",
            f"{owner} has a {other_kind}.", f"What is the name of {first}'s {other_kind}?")
    add("negation", "P0", "In the end I did not sign up for the marathon, not this year.",
        f"{owner} signed up for a marathon.", f"Which marathon did {first} sign up for?")
    p = r.choice(others)
    add("hearsay", p.id, f"{p.name.split()[0]} said their bike got stolen outside the station.",
        f"{owner}'s bike was stolen.", f"Where was {first}'s bike stolen?")
    add("plan", "P0", "Maybe I'll learn to sail this summer, we'll see.",
        f"{owner} learned to sail.", f"Where did {first} take sailing lessons?")
    if len(traps) < 6 and others:
        q = r.choice(others)
        add("hearsay", q.id, f"Apparently {q.name.split()[0]}'s company might be shutting down.",
            f"{q.name}'s company shut down.", f"When did {q.name.split()[0]}'s company shut down?")
    # every photo is a content trap: it is a neutral, non-figurative image
    for f in w.facts:
        if f.predicate == "visited":
            traps.append(Trap(f"T{len(traps) + 1:02d}", "photo_content", "P0", f.valid_from,
                              "", "Any description of what the photo shows.",
                              f"What could be seen in the photo {first} took on "
                              f"{_human_date(f.valid_from)}?", fact_id=f.id))
    return traps


def _unstated(w: World, has_pet: bool) -> list[dict]:
    first = w.person("P0").name.split()[0]
    qs = [f"What car does {first} drive?",
          f"What is {first}'s blood type?",
          f"Which university did {first} attend?",
          f"What is the name of {first}'s landlord?"]
    if not has_pet:
        qs.append(f"How old is {first}'s pet?")
    # attributes of real people that no deposit ever states
    unknown = ["What car does {n} drive?", "What is {n}'s favourite band?",
               "Which school did {n} go to?", "What is {n}'s middle name?"]
    for i, p in enumerate(p for p in w.people if p.id != w.owner):
        qs.append(unknown[i % len(unknown)].format(n=p.name.split()[0]))
    return [{"question": q} for q in qs]
