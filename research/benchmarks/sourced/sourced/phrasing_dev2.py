"""Second development phrasing (`--phrasing dev2`).

Same interface as the held-out module that `deposits.py` dispatches to: the
deposit skeleton (ids, times, authors, facts, traps, span roles) is the dev
one, only the words change. Written without looking at the held-out
templates, so tuning a system on this set leaves `test` sealed.

Deliberately hard for a rule-based "who is this sentence about" reader:
other people are often not the first word of the sentence (apposition,
possessives, passive, a name after a preposition, reported first-hand
speech), roles come without "my" ("the landlady", "our flatmate"), owner
facts drop the subject, voice transcripts are lower-cased with hesitations.

Contract kept for the ground truth:
  * every fact sentence states the fact's answer literally (same tokens);
  * a dated sentence keeps the exact day ("today", "yesterday", a date);
  * "not yet" sentences carry a negation the judge reads as such, "already"
    sentences carry none, and neither narrows the bracketed date;
  * trap sentences keep a hedge and stay one sentence;
  * role and name of the identity/coverage people appear together only
    where the dev deposits put them together;
  * no word that would answer a never-stated slot (vehicle, blood type,
    university, shoe size, favourite music group, schooling, middle name).
"""

from __future__ import annotations

import random
import re
import zlib
from datetime import date, datetime

PHRASINGS = ("dev", "test", "dev2")

# --- fixed lines -----------------------------------------------------------
# No first name of the pool, no relation word, no answer-like value.

FILLER_DEV2 = [
    "Rain on and off, never enough to bother with an umbrella.",
    "The kettle has started making a clicking noise.",
    "Folded the laundry at last.",
    "Ate lunch standing at the counter again.",
    "Left my headphones at home, very quiet day.",
    "The lift was out of order all afternoon.",
    "Bread went stale faster than expected.",
    "Sorted out the desk drawers, found three pens that work.",
    "Fell asleep on the sofa far too early.",
    "The bakery downstairs had run out of croissants.",
    "Bought a fern on a whim.",
    "Windy evening, the shutters rattled for hours.",
]
GREETINGS_DEV2 = ["Hiya!", "Morning!", "Hello hello.", "Right, news.", "Evening!", "Hey there!"]
SIGNOFFS_DEV2 = ["Hugs.", "More soon.", "Ring me when you can.", "Write back!",
                 "Look after yourself x", "Speak later."]
# names deposits.py reads from the module it dispatches to
FILLER_TEST = FILLER_DEV2
GREETINGS_TEST = GREETINGS_DEV2
SIGNOFFS_TEST = SIGNOFFS_DEV2
FILLER = FILLER_DEV2
GREETINGS = GREETINGS_DEV2
SIGNOFFS = SIGNOFFS_DEV2

HESITATIONS = ["er,", "erm,", "hmm,", "well,", "ah,", "right,", "okay,"]


# --- helpers ---------------------------------------------------------------

def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _article(noun: str) -> str:
    vowel = noun[:1].lower() in "aeiou" and not noun.startswith("UX")
    return ("an " if vowel else "a ") + noun


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _date_forms(d: date) -> list[str]:
    """Several spellings of one exact day (the year is always kept)."""
    m = d.strftime("%B")
    return [f"{d.day} {m} {d.year}", f"the {_ordinal(d.day)} of {m} {d.year}",
            f"{m} {d.day}, {d.year}"]


def _when(when: str, pr: random.Random) -> str:
    """Re-spell the dev date phrase without moving the day it designates."""
    if not when:
        return ""
    if when == "today":
        return pr.choice(["today", "earlier today", "this morning"])
    if when == "yesterday":
        return pr.choice(["yesterday", "last night", "yesterday"])
    if when.startswith("on "):
        d = datetime.strptime(when[3:], "%d %B %Y").date()
        return "on " + pr.choice(_date_forms(d))
    return when


def _bare(t: str) -> str:
    """'on 3 March 2025' -> '3 March 2025' (for 'from …', 'starting …')."""
    return t[3:] if t.startswith("on ") else t


def _sp(t: str) -> str:
    return f" {t}" if t else ""


def _stable(*parts: str) -> int:
    """Deterministic layout choice for documents and photos (no stream)."""
    return zlib.crc32("|".join(parts).encode("utf-8"))


# relation spelled differently on first mention, sometimes without "my":
# (subject form, object form, possessive form); a subject form may end on
# an apposition comma, so it is always followed by its verb
_STYLES = {
    "neighbour": [("my neighbour {n}", "my neighbour {n}", "my neighbour {n}'s"),
                  ("{n} from next door", "{n} from next door", "{n}'s"),
                  ("{n}, our neighbour,", "{n} (our neighbour)", "our neighbour {n}'s")],
    "colleague": [("my colleague {n}", "my colleague {n}", "my colleague {n}'s"),
                  ("{n} from work", "{n} from work", "{n}'s"),
                  ("{n}, a colleague,", "{n} (a colleague)", "{n}'s")],
    "manager": [("my manager {n}", "my manager {n}", "my manager {n}'s"),
                ("{n}, the boss,", "{n} (the boss)", "the boss {n}'s"),
                ("{n} (my manager)", "{n} (my manager)", "{n}'s")],
}
_DEFAULT_STYLES = [("my {r} {n}", "my {r} {n}", "my {r} {n}'s"),
                   ("{n} (my {r})", "{n} (my {r})", "{n}'s"),
                   ("{n}, my {r},", "{n} (my {r})", "my {r} {n}'s")]


def _names(sp, pid: str, pr: random.Random) -> dict:
    """How speaker `sp` designates person `pid`, as subject / object /
    possessive. The first mention by the owner carries the relation, in one
    style for the whole sentence; later mentions use the first name."""
    if pid == sp.speaker:
        return {"subj": "I", "obj": "me", "poss": "my"}
    p = sp.w.person(pid)
    n = p.name.split()[0]
    plain = {"subj": n, "obj": n, "poss": f"{n}'s"}
    if pid in sp.introduced or p.relation == "self":
        return plain
    sp.introduced.add(pid)
    if sp.speaker != "P0" or p.relation == "partner":
        return plain
    st = pr.choice(_STYLES.get(p.relation, _DEFAULT_STYLES))
    return {k: x.format(n=n, r=p.relation) for k, x in zip(("subj", "obj", "poss"), st)}


def _since(t: str) -> str:
    return "since " + _bare(t) if t else "since today"


def _asof(t: str) -> str:
    return "as of " + _bare(t) if t else "as of now"


# --- fact sentences --------------------------------------------------------

def fact_sentence(sp, f, role: str, when: str, pr: random.Random) -> str:
    """One sentence (sometimes two short ones) stating fact `f` from the
    point of view of speaker `sp`. `role`: mention | start | end | future."""
    v, p = f.value, f.predicate
    me = f.subject == sp.speaker
    t = _when(when, pr)
    w_ = _sp(t)
    lead = _cap(t) + ", " if t else ""  # a date phrase opening the sentence
    since = ""
    if f.since_stated and role == "mention":
        since = date.fromisoformat(f.valid_from).strftime("%B %Y")
    pick = pr.choice

    if p == "lives_at":
        st, city = v["street"], v["city"]
        if role == "start":
            return pick([f"Keys collected{w_}: {st}, {city} is home now.",
                         f"{st} in {city} is the new address, moved in{w_}.",
                         f"Moving day{w_}, everything in boxes at {st}, {city}.",
                         f"{lead}{'the' if lead else 'The'} flat at {st}, {city} became mine."])
        if since:
            return pick([f"{st}, {city} has been my address since {since}.",
                         f"Living at {st} in {city}, ever since {since}.",
                         f"Since {since} home has meant {st}, {city}."])
        return pick([f"Back at {st}, {city}, the boiler is grumbling again.",
                     f"Home at {st} ({city}) felt cold tonight.",
                     f"The stairs at {st}, {city} seem steeper every week."])

    if p == "pays_rent":
        a, c = v["amount"], v["currency"]
        return pick([f"{a} {c} gone on rent this month.",
                     f"Rent day: transferred {a} {c}.",
                     f"The monthly {a} {c} for the flat went out."])

    if p == "works_at":
        e, ti = v["employer"], v["title"]
        if role == "start":
            return pick([f"Day one at {e}{w_}, their new {ti} is me.",
                         f"{_cap(t) if t else 'Today'}: first shift at {e}, officially {_article(ti)}.",
                         f"New badge says {ti}, {e}; started{w_}.",
                         f"{e} has had a new {ti} {_since(t)}: me."])
        if role == "future":
            b = _bare(t)
            if not b:
                return pick([f"Signed the contract with {e} as {ti}.",
                             f"The {ti} role at {e} is mine."])
            return pick([f"Signed the contract with {e} as {ti}, starting {b}.",
                         f"The {ti} role at {e} is mine, first day {t}.",
                         f"{e} said yes, so {_article(ti)} from {b} onwards."])
        if since:
            return pick([f"{_cap(_article(ti))} at {e} since {since}, and still learning.",
                         f"Been with {e} since {since}, working as {_article(ti)}.",
                         f"{e} has had me as their {ti} since {since}."])
        return pick([f"Another long day at {e}, the usual {ti} juggling.",
                     f"Being the {ti} at {e} has its moments.",
                     f"Meetings all afternoon at {e}, part of the {ti} job."])

    if p == "health":
        cond, care = v["condition"], v["care"]
        if role == "end":
            return pick([f"Over {cond}{w_}, finally.",
                         f"{_cap(cond)} is behind me{w_}.",
                         f"Signed off as recovered from {cond}{w_}."])
        return pick([f"Diagnosis{w_}: {cond}, so {care} for now.",
                     f"The doctor confirmed {cond}{w_}; {care} until it settles.",
                     f"{lead or 'So, '}found out it's {cond}, with {care} prescribed."])

    if p == "dating":
        o = _names(sp, v["person"], pr)
        return pick([f"{_cap(o['subj'])} and I made it official{w_}.",
                     f"Things with {o['obj']} turned into a real relationship{w_}.",
                     f"{lead}{o['subj'] if lead else _cap(o['subj'])} asked if we're together, "
                     f"and yes, we are."])

    if p == "project":
        pj, stg = v["project"], v["stage"]
        if stg == "planning":
            return pick([f"Kicked off {pj}{w_}, planning only for now.",
                         f"{_cap(pj)}: first sketches{w_}, still the planning stage.",
                         f"Notebook out{w_}, planning {pj}."])
        if stg == "building":
            return pick([f"Building {pj} for real {_since(t)}.",
                         f"{_cap(pj)} moved from paper to building{w_}.",
                         f"Started building {pj}{w_}, finally hands-on."])
        return pick([f"{_cap(pj)} launched{w_}!",
                     f"It's live: {pj}, launched{w_}.",
                     f"Launched {pj}{w_}, out in the world now."])

    if p == "commutes":
        m = v["mode"]
        if role == "start":
            return pick([f"From {_bare(t) or 'now'} on, it's {m} to work.",
                         f"New routine{w_}: getting to work {m}.",
                         f"First day commuting {m}{w_}."])
        return pick([f"Work and back {m}, as always.",
                     f"The usual commute {m}, nothing new.",
                     f"Got to the office {m}, same as every day."])

    if p == "hobby":
        h = v["hobby"]
        if role == "start":
            return pick([f"Took up {h}{w_}, first session went well.",
                         f"{_cap(h)} is the new thing, first go{w_}.",
                         f"Signed myself up for {h}{w_}."])
        return pick([f"An evening of {h}, nothing better.",
                     f"{_cap(h)} again tonight, still the highlight of my week.",
                     f"Lost track of time doing {h}."])

    if p == "gym":
        g = v["gym"]
        if role == "start":
            return pick([f"Joined {g}{w_}, the old membership is cancelled.",
                         f"{g} is my gym now, signed up{w_}.",
                         f"{_cap(t) if t else 'Today'}: switched over to {g}."])
        return pick([f"Short workout at {g}.",
                     f"{g} was packed tonight.",
                     f"Half an hour at {g} before dinner."])

    if p == "birthday":
        d = date.fromisoformat(v["date"])
        dm = pick([f"{d.day} {d.strftime('%B')}", f"{d.strftime('%B')} {d.day}"])
        if me and sp.speaker == "P0":
            return pick([f"Note to self: my birthday is {dm}, plan something.",
                         f"{dm}, my birthday, is coming round again.",
                         f"Birthday on {dm} this year too, obviously."])
        if me:
            return pick([f"My birthday's on {dm}, you'd better remember!",
                         f"Reminder: {dm} is my birthday.",
                         f"{dm} is the big day, my birthday, in case you forgot."])
        o = _names(sp, f.subject, pr)
        return pick([f"{_cap(o['poss'])} birthday: {dm}, must not forget.",
                     f"{dm} is {o['poss']} birthday, gift needed.",
                     f"{_cap(o['subj'])} celebrates a birthday on {dm} every year.",
                     f"In the calendar for {dm}, {o['poss']} birthday."])

    if p == "hometown":
        c = v["city"]
        return pick([f"{c}, where I grew up, came up in conversation.",
                     f"Grew up in {c} and still miss it.",
                     f"Missing the streets of {c}, the town I grew up in."])

    if p == "allergy":
        fo = v["food"]
        return pick([f"Asked twice about {fo} at the restaurant, being allergic and all.",
                     f"{_cap(fo)} in the sauce, so the dish went back; I'm allergic.",
                     f"Allergic to {fo}, so I read every label in the shop."])

    if p == "speaks":
        lg = v["language"]
        return pick([f"Half an hour of {lg} practice on the way home.",
                     f"My {lg} is improving, podcast every morning.",
                     f"Practised {lg} with an app before bed."])

    if p == "pet":
        k, nm = v["kind"], v["name"]
        if me:
            return pick([f"{nm}, my {k}, was up at dawn again.",
                         f"My {k} {nm} knocked a glass off the table.",
                         f"{nm} (the {k}) has claimed my chair."])
        o = _names(sp, f.subject, pr)
        return pick([f"{nm} is {o['poss']} {k}.",
                     f"{nm}, {_article(k)}, lives with {o['obj']}.",
                     f"{_cap(o['poss'])} {k}, {nm}, is adorable.",
                     f"There's {_article(k)} called {nm} at {o['poss']} place."])

    if p == "lives_in":
        c = v["city"]
        if me:
            if role == "start":
                return pick([f"Writing from {c}! Moved here{w_}.",
                             f"New city: {c}, moved{w_}, still unpacking.",
                             f"Officially living in {c} {_asof(t)}.",
                             f"Big move done{w_}, I live in {c} now."])
            return pick([f"Life in {c} is treating me well.",
                         f"All good here in {c}.",
                         f"Still loving {c}, honestly, best place I've lived.",
                         f"{c} is home and I'm happy here.",
                         f"Settled in {c} for good, it seems."])
        o = _names(sp, f.subject, pr)
        if role == "start":
            return pick([f"{c} is where {o['subj']} lives now, moved{w_}.",
                         f"Heard from {o['obj']}: moved to {c}{w_}.",
                         f"{lead}{o['subj'] if lead else _cap(o['subj'])} relocated to {c}.",
                         f"The move to {c} happened{w_}, so {o['subj']} is a {c} resident now.",
                         f"According to {o['obj']}, the move to {c} was done{w_}."])
        return pick([f"Video call with {o['obj']}, who lives in {c} these days.",
                     f"{c} still suits {o['obj']}, by the sound of it.",
                     f"Sent a parcel to {o['obj']} in {c}, where they live.",
                     f"{_cap(o['subj'])} has been based in {c} for a long while."])

    if p == "job":
        ti = v["title"]
        if me:
            return pick([f"Being {_article(ti)} keeps me busy.",
                         f"Work as {_article(ti)} is full on this month.",
                         f"Another week as {_article(ti)}, tiring but fun.",
                         f"My {ti} job is eating all my time."])
        o = _names(sp, f.subject, pr)
        return pick([f"{_cap(_article(ti))}, that's what {o['subj']} does for a living.",
                     f"Over coffee {o['subj']} talked about life as {_article(ti)}.",
                     f"{_cap(o['poss'])} job? {_cap(ti)}.",
                     f"According to {o['obj']}, being {_article(ti)} is exhausting.",
                     f"{_cap(o['subj'])} is employed as {_article(ti)}."])

    if p == "met":
        o = _names(sp, v["person"], pr)["obj"]
        ve = v["venue"]
        return pick([f"Bumped into {o} at {ve}{w_}.",
                     f"{_cap(ve)}{w_}, coffee with {o}.",
                     f"Caught up with {o}{w_}, we walked around {ve}."])

    if p == "race":
        rc, tm = v["race"], v["time"]
        return pick([f"The {rc}{w_}: crossed the line in {tm}.",
                     f"Finished the {rc}{w_}, {tm} on the clock.",
                     f"{tm} at the {rc}{w_}, legs are gone."])

    if p == "appointment":
        wh = v["what"]
        return pick([f"The {wh} appointment was{w_ or ' today'}, all fine.",
                     f"Went to the {wh} appointment{w_}, nothing to report.",
                     f"Ticked off the {wh} appointment{w_}."])

    if p == "news":
        wh = v["what"]
        if me:
            return pick([f"Guess what, I {wh}{w_}!", f"Huge news: I {wh}{w_}.",
                         f"Had to tell you first, I {wh}{w_}."])
        o = _names(sp, f.subject, pr)
        return pick([f"Big news from {o['obj']}, who {wh}{w_}.",
                     f"{lead}{o['subj'] if lead else _cap(o['subj'])} {wh}, so happy for them.",
                     f"Guess who {wh}{w_}? {_cap(o['obj'])}.",
                     f"Word from {o['obj']}: {wh}{w_}."])

    if p == "visited":
        ve = v["venue"]
        return pick([f"Wandered through {ve}{w_}.",
                     f"An hour at {ve}{w_}, slow and quiet.",
                     f"{_cap(ve)}{w_}, just walking."])

    raise ValueError(p)


# first words of the templates above that are not proper nouns: lowered
# when the sentence becomes the second clause of a joined line
_COMMON_STARTS = {
    "a", "an", "the", "my", "our", "keys", "moving", "living", "since", "back", "home",
    "rent", "day", "today", "new", "signed", "been", "in", "another", "being", "meetings",
    "over", "diagnosis", "so", "things", "kicked", "notebook", "building",
    "started", "launched", "it's", "from", "first", "work", "got", "took", "lost", "joined", "short", "half", "note", "birthday", "reminder", "calendar",
    "grew", "missing", "asked", "allergic", "practised", "there's", "writing", "officially",
    "life", "all", "heard", "video", "sent", "bumped", "caught", "finished", "went",
    "ticked", "guess", "big", "huge", "wandered", "yesterday", "earlier", "this", "last",
}


def join(s1: str, s2: str, pr: random.Random) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """Two fact sentences written as one line; the spans of both clauses."""
    if s1.endswith("."):
        a, glue = s1[:-1], pr.choice(["; ", " and ", ", plus ", " - ", ". Also: "])
    else:  # ends on "!" or "?": keep it
        a, glue = s1, pr.choice([" ", " Also: "])
    head = s2.split(" ", 1)[0].rstrip(",:;").lower()
    if glue in ("; ", " and ", ", plus ", " - ") and head in _COMMON_STARTS:
        s2 = s2[:1].lower() + s2[1:]
    joined = f"{a}{glue}{s2}"
    b0 = len(a) + len(glue)
    return joined, (0, len(a)), (b0, len(joined))


def disfluent(sentence: str, pr: random.Random, rate: float = 0.16) -> str:
    """Voice transcript style: lower case throughout (as a speech recogniser
    writes it), hesitations, now and then a repeated word."""
    words = sentence.lower().split(" ")
    out = []
    for i, wd in enumerate(words):
        if i and pr.random() < rate:
            out.append(pr.choice(HESITATIONS))
        if i == 1 and pr.random() < 0.2:
            out.append(wd.rstrip(",.!?:;"))
        out.append(wd)
    return " ".join(out)


# --- traps -----------------------------------------------------------------
# The dev trap sentences come from fixed templates in world.py; each is
# re-said with a hedge kept, still one sentence ending with a full stop.

def trap_sentence(sentence: str, pr: random.Random) -> str:
    pick = pr.choice
    if (m := re.fullmatch(r"If the (.+) offer ever comes through, I'd honestly move there "
                          r"in a heartbeat\.", sentence)):
        c = m.group(1)
        return pick([f"If {c} comes back with an offer, I might just move there.",
                     f"Part of me hopes the {c} offer works out, so I could move there.",
                     f"Moving to {c} would be a dream if that job ever happens."])
    if (m := re.fullmatch(r"I keep thinking about adopting a (\w+), maybe next year\.", sentence)):
        k = m.group(1)
        return pick([f"Considering {_article(k)} at some point, though not before next year.",
                     f"{_cap(_article(k))} would be lovely, maybe once things calm down.",
                     f"Thinking {_article(k)} might suit the flat one day."])
    if sentence == "In the end I did not sign up for the marathon, not this year.":
        return pick(["The marathon sign-up deadline came and went, and I didn't register.",
                     "No marathon for me this year, I did not sign up after all.",
                     "Skipped the marathon registration, not this year."])
    if (m := re.fullmatch(r"(\S+) said their bike got stolen outside the station\.", sentence)):
        n = m.group(1)
        return pick([f"{n} said someone took their bike from outside the station.",
                     f"Apparently {n}'s bike vanished from the rack by the station.",
                     f"Heard it from {n}: apparently their bike got stolen at the station."])
    if sentence == "Maybe I'll learn to sail this summer, we'll see.":
        return pick(["Sailing lessons this summer, maybe, if the weather allows.",
                     "I might try sailing when summer comes, nothing booked.",
                     "Thinking about learning to sail in the summer."])
    if (m := re.fullmatch(r"Apparently (\S+)'s company might be shutting down\.", sentence)):
        n = m.group(1)
        return pick([f"Rumour has it {n}'s company could close.",
                     f"{n} said their company might fold before long.",
                     f"Apparently things look grim at {n}'s company, closure is on the table."])
    return sentence


# --- identity, dating and coverage layers ----------------------------------

def alias_sentence(role: str, first: str, pr: random.Random) -> str:
    """The only deposit naming a target by role and by name together."""
    return pr.choice([f"{first}, {role}, came over for dinner tonight.",
                      f"Spent the evening with {first} ({role}).",
                      f"{_cap(role)}, {first}, rang this evening and we talked for an hour.",
                      f"Waited at the station with {first} tonight; that's {role}, for the record."])


def role_sentence(c_first: str, role: str, employer: str, pr: random.Random) -> str:
    """The target by role only, next to another named person."""
    opts = [f"{c_first} asked where {role} works these days: {employer}.",
            f"{employer} is where {role} works, I explained to {c_first}.",
            f"Over coffee {c_first} heard from me that {role} works at {employer}."]
    if " from " not in role:
        opts.append(f"{c_first} was surprised that {role}'s employer is {employer}.")
    return pr.choice(opts)


def name_sentence(first: str, group: str, pr: random.Random) -> str:
    """The target by name only: joined a group today."""
    return pr.choice([f"{_cap(group)} welcomed a new member today: {first}.",
                      f"As of today {first} sings with {group}.",
                      f"First rehearsal with {group} today for {first}, who joined this morning.",
                      f"Guess who joined {group} today? {first}."])


def dating_sentences(is_owner: bool, first: str, item: str,
                     pr: random.Random) -> tuple[str, str]:
    """("not yet" sentence, "already" sentence). The first carries a negation
    the judge reads; the second none, and never says when it arrived."""
    if is_owner:
        not_yet = pr.choice([f"No {item} so far, the delivery keeps slipping.",
                             f"The {item} hasn't turned up.",
                             f"Checked the tracking: the {item} is still in transit.",
                             f"The {item} I ordered? Not delivered."])
        already = pr.choice([f"The {item} has been here for a while now, worth every penny.",
                             f"Using the {item} most evenings these days.",
                             f"Glad I bought the {item}, it has earned its spot in the flat."])
    else:
        not_yet = pr.choice([f"The {item} {first} ordered hasn't arrived.",
                             f"No {item} for {first} so far, the courier keeps rescheduling.",
                             f"{first} is still without the {item}.",
                             f"Asked {first} about the {item}: not there yet."])
        already = pr.choice([f"{first}'s {item} has been in use for a while.",
                             f"The {item} at {first}'s place looks great, it's been there a while.",
                             f"{first} has had the {item} for some time now."])
    return not_yet, already


_THE_OK = {"landlady", "flatmate", "piano teacher", "climbing partner"}


def _role_phrase(role: str, pr: random.Random) -> str:
    core = role.removeprefix("my ")
    forms = [f"my {core}"]
    if core in _THE_OK:
        forms += [f"the {core}", f"our {core}"]
    return pr.choice(forms)


def coverage_sentence(predicate: str, by_role: bool, role: str, name: str, v: dict,
                      pr: random.Random) -> str:
    """One attribute, by role OR by name, never both."""
    pick = pr.choice
    if by_role:
        r = _role_phrase(role, pr)
        if predicate == "based_in":
            c = v["city"]
            return pick([f"{_cap(r)} lives in {c} now.",
                         f"{c} is where {r} lives these days.",
                         f"{_cap(r)}'s flat is in {c}."])
        if predicate == "employer":
            e = v["employer"]
            return pick([f"{_cap(r)} works at {e}.",
                         f"{e} is who {r} works for.",
                         f"{_cap(r)}'s employer: {e}."])
        return pick([f"{_cap(r)} works from home most days.",
                     f"Most days {r} works from home.",
                     f"Home is {r}'s office, most of the week."])
    if predicate == "based_in":
        c = v["city"]
        return pick([f"{name} lives in {c}, close to the water.",
                     f"{c} is where {name} is based.",
                     f"Postcard from {name}, who lives in {c}."])
    if predicate == "employer":
        e = v["employer"]
        return pick([f"Ran into {name}, who works at {e}.",
                     f"{name} has a job at {e}.",
                     f"Things at {e}, where {name} works, sound hectic."])
    return pick([f"{name} works from home most days.",
                 f"Working from home suits {name}, who does it most days.",
                 f"{name}'s office is the kitchen table at home."])


def together_sentence(role: str, name: str, pr: random.Random) -> str:
    """The decoy: role and name in one deposit, as two people."""
    r = _role_phrase(role, pr)
    return pr.choice([f"Lunch with {r} and {name} today.",
                      f"{name} joined {r} and me for lunch today.",
                      f"Had lunch today with {name} and {r}, the three of us."])


# --- photos and documents (no stream: layout chosen from the content) -----

def photo_text(day: str, v: dict) -> str:
    lat, lon, tm = f"{v['lat']:.5f}", f"{v['lon']:.5f}", v["time"]
    k = _stable(day, tm) % 3
    return [f"Image file metadata: captured {day} {tm}; GPS {lat}, {lon}.",
            f"Camera roll item from {day}, {tm}. Location (GPS): {lat}, {lon}.",
            f"Saved {day} at {tm}, GPS coordinates {lat} / {lon}."][k]


def _doc_date(iso: str, k: int) -> str:
    d = date.fromisoformat(iso)
    return [f"{d.day} {d.strftime('%B %Y')}", d.strftime("%d/%m/%Y"),
            f"{d.strftime('%B')} {d.day}, {d.year}"][k % 3]


def lease_document(owner_name: str, home, rent, agent: str) -> tuple[str, dict, dict]:
    v = home.value
    k = _stable(owner_name, home.valid_from)
    dt = _doc_date(home.valid_from, k >> 3)
    if k % 2 == 0:
        lines = ["TENANCY AGREEMENT", "", f"Between {agent} (the lessor)",
                 f"and {owner_name} (the tenant)", "",
                 f"Property let: {v['street']}, {v['city']}", f"Tenancy begins: {dt}"]
        keys = {"lives_at": "Property let:", "pays_rent": "Rent payable monthly:"}
        if rent:
            lines.append(f"Rent payable monthly: {rent.value['amount']} {rent.value['currency']}")
        lines += ["", "Deposit held in a protected scheme.", "Both parties have signed below."]
    else:
        lines = ["LETTING CONTRACT", "", f"Occupant: {owner_name}", f"Agent: {agent}",
                 f"Dwelling address: {v['street']}, {v['city']}", f"Move-in date: {dt}"]
        keys = {"lives_at": "Dwelling address:", "pays_rent": "Monthly payment due:"}
        if rent:
            lines.append(f"Monthly payment due: {rent.value['amount']} {rent.value['currency']}")
        lines += ["", "Keys returned at the end of the contract.", "Signed in duplicate."]
    return "\n".join(lines), {"doc_type": "lease"}, keys


def offer_document(owner_name: str, job) -> tuple[str, dict, dict]:
    v = job.value
    k = _stable(owner_name, job.valid_from, v["employer"])
    dt = _doc_date(job.valid_from, k >> 3)
    if k % 2 == 0:
        text = "\n".join([v["employer"], "", "LETTER OF APPOINTMENT", "", f"To: {owner_name}", "",
                          f"Re: your appointment as {v['title']} at {v['employer']}",
                          f"First working day: {dt}",
                          "Kindly return a countersigned copy.", "", "People Team"])
        keys = {"works_at": "Re: your appointment"}
    else:
        text = "\n".join(["JOB OFFER", "", f"Candidate: {owner_name}",
                          f"Role offered: {v['title']}, {v['employer']}",
                          f"Starting on: {dt}", "",
                          "We look forward to welcoming you.", "Recruitment"])
        keys = {"works_at": "Role offered:"}
    return text, {"doc_type": "offer_letter"}, keys


def clinic_document(owner_name: str, h, clinic: str) -> tuple[str, dict, dict]:
    v = h.value
    k = _stable(owner_name, h.valid_from, clinic)
    dt = _doc_date(h.valid_from, k >> 3)
    if k % 2 == 0:
        text = "\n".join([clinic, "", "CONSULTATION NOTE", "", f"Name: {owner_name}",
                          f"Seen on: {dt}", f"Diagnosis - {v['condition']}",
                          f"Management - {v['care']}", "Review if no improvement."])
        keys = {"health": "Diagnosis -"}
    else:
        text = "\n".join(["CLINIC LETTER", clinic, "", f"Re: {owner_name}, attended {dt}",
                          f"Clinical findings: {v['condition']}; treatment: {v['care']}",
                          "Return should symptoms get worse."])
        keys = {"health": "Clinical findings:"}
    return text, {"doc_type": "visit_summary"}, keys


def race_document(owner_name: str, race) -> tuple[str, dict, dict]:
    v = race.value
    k = _stable(owner_name, race.valid_from, v["race"])
    dt = _doc_date(race.valid_from, k >> 3)
    if k % 2 == 0:
        text = "\n".join(["RESULT SLIP", v["race"], "", f"Participant: {owner_name}",
                          f"Event date: {dt}", f"Chip time: {v['time']}"])
        keys = {"race": "Chip time:"}
    else:
        text = "\n".join([f"Certificate of completion, {v['race']}", "",
                          f"Awarded to {owner_name}, who completed the course on {dt}.",
                          f"Net time recorded: {v['time']}"])
        keys = {"race": "Net time recorded:"}
    return text, {"doc_type": "certificate"}, keys
