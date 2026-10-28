"""Temporal engine — lived time, not only objective time (§7.6).

Non-negotiable principle: the temporal frame is COMPUTED IN CODE, never left
to the LLM's arithmetic. Every MCP response embeds this frame.

Everything this module returns to the reader (humanized deltas such as
"il y a 14 mois", season names, landmark labels, TENSE_GUIDE) and every regex
and word list that parses French (and English) questions is deliberately kept
in French: the memory corpus is French and the tests exercise French parsing.
"""

from datetime import date, datetime, timedelta, timezone


SAISONS = {12: "hiver", 1: "hiver", 2: "hiver", 3: "printemps", 4: "printemps",
           5: "printemps", 6: "été", 7: "été", 8: "été", 9: "automne",
           10: "automne", 11: "automne"}


def humanize_delta(then: datetime, now: datetime | None = None) -> str:
    """Humanized delta: "il y a 14 mois, deux étés en arrière" (output stays French)."""
    now = now or datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    # Calendar days (no timedelta truncation): "tomorrow" stays tomorrow
    days = (now.date() - then.date()).days
    future = days < 0
    days = abs(days)

    if days == 0:
        core = "aujourd'hui"
    elif days == 1:
        core = "demain" if future else "hier"
    elif days < 14:
        core = f"dans {days} jours" if future else f"il y a {days} jours"
    elif days < 75:
        w = round(days / 7)
        core = f"dans {w} semaines" if future else f"il y a {w} semaines"
    elif days < 700:
        m = round(days / 30.4)
        core = f"dans {m} mois" if future else f"il y a {m} mois"
    else:
        y = round(days / 365.25, 1)
        y_txt = f"{y:g} ans"
        core = f"dans {y_txt}" if future else f"il y a {y_txt}"

    # Distance in lived seasons: how many summers separate then from now
    if not future and days >= 300:
        summers = _summers_between(then.date(), now.date())
        if summers >= 1:
            core += f", {_fr_count(summers)} été{'s' if summers > 1 else ''} en arrière"
    return core


def _summers_between(then: date, now: date) -> int:
    count = 0
    for year in range(then.year, now.year + 1):
        mid_summer = date(year, 7, 15)
        if then <= mid_summer <= now:
            count += 1
    return count


def _fr_count(n: int) -> str:
    return {1: "un", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq"}.get(n, str(n))


def frame(conn, mentioned_dates: list[datetime] | None = None) -> dict:
    """The temporal frame embedded in every MCP response:
    date, season, position relative to landmarks, relevant active intentions."""
    now = datetime.now(timezone.utc)
    today = now.date()

    landmarks = conn.execute(
        """
        SELECT name, at_date, kind, cycle FROM landmarks
        WHERE at_date BETWEEN %s - INTERVAL '18 months' AND %s + INTERVAL '12 months'
        ORDER BY at_date
        """,
        (today, today),
    ).fetchall()
    landmark_frames = []
    for lm in landmarks:
        d = (lm["at_date"] - today).days
        rel = f"J{d:+d}" if d != 0 else "aujourd'hui"
        landmark_frames.append({"name": lm["name"], "date": lm["at_date"].isoformat(),
                                "kind": lm["kind"], "delta": rel})

    # Prospective memory: intentions whose trigger has been reached.
    # They resurface IN CONTEXT — never as a notification (silence rule).
    due = list(conn.execute(
        """
        SELECT id, content, trigger_kind, trigger_value FROM intentions
        WHERE resolved_at IS NULL
          AND trigger_kind = 'date' AND trigger_value::date <= %s
        """,
        (today,),
    ).fetchall())
    # 'delta_landmark' trigger: "J-30:landmark_name"
    for intent in conn.execute(
        "SELECT id, content, trigger_kind, trigger_value FROM intentions "
        "WHERE resolved_at IS NULL AND trigger_kind = 'delta_landmark'"
    ).fetchall():
        try:
            delta_part, _, lm_name = intent["trigger_value"].partition(":")
            offset = int(delta_part.strip().upper().removeprefix("J"))  # 'J-30' → -30
        except ValueError:
            continue
        lm = conn.execute("SELECT at_date FROM landmarks WHERE name ILIKE %s "
                          "ORDER BY at_date DESC LIMIT 1", (lm_name.strip(),)).fetchone()
        if lm is None:
            continue
        trigger_date = lm["at_date"] + timedelta(days=offset)
        if today >= trigger_date:
            due.append(intent)

    return {
        "now": now.isoformat(),
        "saison": SAISONS[now.month],
        "deltas": [
            {"date": d.isoformat(), "humanized": humanize_delta(d, now)}
            for d in (mentioned_dates or [])
        ],
        "jalons": landmark_frames,
        "intentions_actives": [
            {"id": i["id"], "content": i["content"]} for i in due
        ],
    }


# ---------------------------------------------------------------------------
# Anchoring in reality: past, present, future.
#
# A language model has no clock: everything it reads seems present to it. A
# memory from June that became false in October seems as current as a memory
# from yesterday. What follows places each memory in time, in code, and reads
# the temporal orientation of the question asked.
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402

_MOIS = ("janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|"
         "septembre|octobre|novembre|décembre|decembre|january|february|march|"
         "april|may|june|july|august|september|october|november|december")
_RECENT = _re.compile(
    r"\b(r[ée]cemment|derni[eè]rement|en ce moment|actuellement|aujourd'hui|"
    r"cette semaine|ce mois|ces derniers? (jours|temps|semaines|mois)|quoi de neuf|"
    r"o[uù] j'en suis|o[uù] en est|maintenant|recently|lately|currently|right now|"
    r"these days|this (week|month)|what'?s new|latest)\b", _re.IGNORECASE)
_PAST = _re.compile(
    r"\b(avant|autrefois|à l'époque|a l'epoque|il y a (\d+|quelques|plusieurs)|l'an dernier|l'année dernière|"
    r"jadis|anciennement|qu'est-ce que je pensais|je pensais|j'avais|"
    r"used to|back then|before|last year|previously|at the time|"
    rf"en (?:{_MOIS})|in (?:{_MOIS})|(?:19|20)\d\d)\b", _re.IGNORECASE)
_FUTURE = _re.compile(
    r"\b(pr[ée]vue?s?|pr[ée]vois|projet[ée]e?s?|objectifs?|à venir|a venir|"
    r"bient[oô]t|demain|prochaine?s?|dans (\d+|quelques) (jours|semaines|mois|ans)|"
    r"je vais|compte faire|upcoming|planned|going to)\b", _re.IGNORECASE)


def intent(query: str) -> str | None:
    """Temporal orientation of a question: 'recent', 'past', 'future' or None.

    The past wins over the recent when both appear: "qu'est-ce que je pensais
    en juin, avant ma décision récente ?" looks backward.
    """
    if _PAST.search(query or ""):
        return "past"
    if _RECENT.search(query or ""):
        return "recent"
    if _FUTURE.search(query or ""):
        return "future"
    return None


def _aware(d: datetime | None) -> datetime | None:
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def tense(valid_from: datetime, valid_to: datetime | None,
          superseded_by: int | None = None, now: datetime | None = None) -> str:
    """The grammatical tense of a memory: 'present', 'past' or 'future'.

    Past: closed (valid_to reached) or superseded. Future: its validity has
    not yet begun (a dated project, an upcoming race). Present otherwise.
    """
    now = now or datetime.now(timezone.utc)
    valid_from, valid_to = _aware(valid_from), _aware(valid_to)
    if superseded_by is not None or (valid_to is not None and valid_to <= now):
        return "past"
    if valid_from > now:
        return "future"
    return "present"


def distance(valid_from: datetime, archived_at: datetime | None = None,
             now: datetime | None = None) -> str:
    """Lived remoteness: 'proche' (< 3 months), 'lointain' (< 2 years), 'ancien'.

    An archived memory is at least remote: it was set aside.
    """
    now = now or datetime.now(timezone.utc)
    days = (now - _aware(valid_from)).days
    level = "proche" if days < 91 else "lointain" if days < 730 else "ancien"
    if archived_at is not None and level == "proche":
        level = "lointain"
    return level


TENSE_GUIDE = (
    "Chaque mémoire porte son temps, calculé en code. « present » : vrai "
    "aujourd'hui. « past » : a été vrai, ne l'est plus — ne le présente jamais "
    "comme actuel, dis depuis quand et ce qui l'a remplacé. « future » : projet "
    "ou échéance à venir. Raconte la continuité dans cet ordre : ce qui était, "
    "ce qui a changé et pourquoi, ce qui est, ce qui vient. Quand ils sont "
    "connus, « ou » donne le lieu (avec sa source, donc sa fiabilité) et "
    "« epoque » le chapitre de vie : situe le souvenir dans l'espace et dans "
    "la vie, pas seulement sur un calendrier.")


def rank(rows: list, orientation: str | None, limit: int = 8,
         now: datetime | None = None, window: tuple | None = None) -> list:
    """Rerank candidates according to their tense and the question's orientation.

    Relevance remains the first criterion; time modulates it:
      · a bygone memory recedes, unless the question looks backward;
      · "recently" brings fresh things up;
      · a question about the future brings up what is coming;
      · a named period (`window`, from temporal.cues) brings up whatever falls
        within it.
    After hybrid search, relevance is the fusion rank (`fusion_rank`): 0.01
    per place, so a bonus of 0.12 is worth twelve places. Otherwise the vector
    distance; with neither, arrival order.
    """
    import math
    now = now or datetime.now(timezone.utc)
    scored = []
    for i, r in enumerate(rows):
        d = r.get("distance")
        if r.get("fusion_rank") is not None:
            score = 0.5 + r["fusion_rank"] * 0.01
        else:
            score = float(d) if d is not None else 0.5 + i * 0.01
        if window:
            start, end = window
            vf = _aware(r["valid_from"])
            if (start is None or vf >= start) and (end is None or vf < end):
                score -= 0.10
        t = tense(r["valid_from"], r.get("valid_to"), r.get("superseded_by"), now)
        if t == "past":
            score += -0.03 if orientation == "past" else 0.12
        elif t == "future" and orientation == "future":
            score -= 0.08
        if r.get("archived_at") is not None and orientation != "past":
            score += 0.08
        if orientation == "recent":
            age = max(0, (now - _aware(r["valid_from"])).days)
            score -= 0.15 * math.exp(-age / 45)
        scored.append((score, i, r))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [r for _, _, r in scored[:limit]]


def epoch(chapters: list, when: datetime) -> str | None:
    """The life chapter in progress at a date: the last one started, not yet
    closed. A chapter closes through a `chapter_end` landmark of the same
    name, or by the start of the next one.
    """
    day = _aware(when).date()
    current = None
    for c in chapters:
        if c["at_date"] > day:
            break
        if c["kind"] == "chapter_start":
            current = c["name"]
        elif c["kind"] == "chapter_end" and c["name"] == current:
            current = None
    return current


# ---------------------------------------------------------------------------
# Temporal cues in the question → a period, computed in code.
#
# "Qu'est-ce que j'ai fait l'été dernier ?" ("What did I do last summer?")
# resembles, as a vector, no memory from July: the word "été" is not in it.
# So the period is computed here, from today's date and the life landmarks,
# then the search targets it (db.search_memories(window=…)) and temporal.rank
# favors whatever falls within it. Never left to the model: it has no clock.
# ---------------------------------------------------------------------------

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
# season → (start month, number of months); winter straddles two years
_SEASONS = {"printemps": (3, 3), "spring": (3, 3), "ete": (6, 3), "summer": (6, 3),
            "automne": (9, 3), "autumn": (9, 3), "fall": (9, 3),
            "hiver": (12, 3), "winter": (12, 3)}
_SEASON_RE = "|".join(_SEASONS)
_UNITS = {"jour": 1, "jours": 1, "day": 1, "days": 1,
          "semaine": 7, "semaines": 7, "week": 7, "weeks": 7,
          "mois": 30, "month": 30, "months": 30,
          "an": 365, "ans": 365, "annee": 365, "annees": 365, "year": 365, "years": 365}
_NUMBERS = {"un": 1, "une": 1, "a": 1, "an": 1, "one": 1, "deux": 2, "two": 2,
            "trois": 3, "three": 3, "quatre": 4, "four": 4, "cinq": 5, "five": 5,
            "six": 6, "sept": 7, "seven": 7, "huit": 8, "eight": 8, "dix": 10, "ten": 10}


def _norm(text: str) -> str:
    import unicodedata
    d = unicodedata.normalize("NFKD", (text or "").lower().replace("’", "'"))
    return "".join(c for c in d if not unicodedata.combining(c))


def _month_window(year: int, month: int, n: int = 1) -> tuple[date, date]:
    end_m = month - 1 + n
    return date(year, month, 1), date(year + end_m // 12, end_m % 12 + 1, 1)


def _last_occurrence(month: int, today: date, include_current: bool = True) -> int:
    """The year of the last `month` begun ("en mai" = the most recent May)."""
    if month < today.month or (include_current and month == today.month):
        return today.year
    return today.year - 1


def cues(query: str, now: datetime | None = None,
         landmarks: list | None = None) -> dict | None:
    """The period a question targets: {'debut', 'fin', 'repere'} or None.

    Bounds are dates, `fin` exclusive; either may be missing ("avant le
    déménagement"). Covers: explicit dates ("8 mai 2023", "2023-05-08",
    "mai 2023", "en 2023"), a bare month (the most recent elapsed one),
    seasons ("l'été dernier", "cet hiver"), "hier", "la semaine / le mois /
    l'an dernier", "il y a 3 semaines", "two weeks ago", and life landmarks
    ("avant / après / pendant <landmark>"). The first cue recognized wins, in
    this order: landmark, precise date, relative, season, month, year.
    """
    q = _norm(query)
    if not q:
        return None
    today = (now or datetime.now(timezone.utc)).date()

    def out(start, end, label):
        # `passee`: the period is entirely bygone — the question looks backward
        # even without saying so ("l'été dernier")
        return {"debut": start, "fin": end, "repere": label,
                "passee": end is not None and end <= today}

    # 1. life landmarks, named in the question
    for lm in sorted(landmarks or [], key=lambda x: -len(x["name"])):
        name = _norm(lm["name"]).strip()
        if len(name) < 3:
            continue
        # the whole name, or its first content word: "avant le déménagement"
        # designates the landmark "Déménagement à Chambéry"
        head = next((w for w in _re.findall(r"\w+", name) if len(w) >= 5), None)
        for probe in dict.fromkeys(p for p in (name, head) if p):
            m = _re.search(r"(?:\b(avant|before|apres|after|depuis|since|pendant|during|"
                           r"lors)\b[\w' ]{0,12}?)?\b" + _re.escape(probe) + r"\b", q)
            if m:
                break
        if not m:
            continue
        at = lm["at_date"]
        word = m.group(1)
        if word in ("avant", "before"):
            return out(None, at, f"avant {lm['name']}")
        if word in ("apres", "after", "depuis", "since"):
            return out(at, None, f"après {lm['name']}")
        return out(at - timedelta(days=30), at + timedelta(days=31), f"autour de {lm['name']}")

    # 2. precise date
    m = _re.search(r"\b((?:19|20)\d\d)-(\d\d)-(\d\d)\b", q)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return out(d - timedelta(days=1), d + timedelta(days=2), d.isoformat())
        except ValueError:
            pass
    m = (_re.search(rf"\b(\d{{1,2}})(?:er|st|nd|rd|th)? ({_MONTH_RE}),? ((?:19|20)\d\d)\b", q)
         or _re.search(rf"\b({_MONTH_RE}) (\d{{1,2}})(?:st|nd|rd|th)?,? ((?:19|20)\d\d)\b", q))
    if m:
        a, b, y = m.groups()
        day, month = (int(a), _MONTHS[b]) if a.isdigit() else (int(b), _MONTHS[a])
        try:
            d = date(int(y), month, day)
            return out(d - timedelta(days=1), d + timedelta(days=2), d.isoformat())
        except ValueError:
            pass

    # 3. relative to today
    if _re.search(r"\b(avant-hier|day before yesterday)\b", q):
        d = today - timedelta(days=2)
        return out(d, d + timedelta(days=1), "avant-hier")
    if _re.search(r"\b(hier|yesterday)\b", q):
        d = today - timedelta(days=1)
        return out(d, d + timedelta(days=1), "hier")
    m = _re.search(r"\bil y a (\d+|\w+) (jours?|semaines?|mois|ans?|annees?)\b", q) \
        or _re.search(r"\b(\d+|\w+) (days?|weeks?|months?|years?) ago\b", q)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS.get(m.group(1))
        unit = _UNITS.get(m.group(2))
        if n and unit:
            center = today - timedelta(days=n * unit)
            slack = timedelta(days=max(1, unit * n // 4, unit // 2))
            return out(center - slack, center + slack + timedelta(days=1), m.group(0))
    if _re.search(r"\b(la semaine derniere|last week)\b", q):
        monday = today - timedelta(days=today.weekday() + 7)
        return out(monday, monday + timedelta(days=7), "la semaine dernière")
    if _re.search(r"\b(cette semaine|this week)\b", q):
        monday = today - timedelta(days=today.weekday())
        return out(monday, today + timedelta(days=1), "cette semaine")
    if _re.search(r"\b(le mois dernier|last month)\b", q):
        first = today.replace(day=1)
        start = (first - timedelta(days=1)).replace(day=1)
        return out(start, first, "le mois dernier")
    if _re.search(r"\b(ce mois-ci|ce mois|this month)\b", q):
        return out(today.replace(day=1), today + timedelta(days=1), "ce mois-ci")
    if _re.search(r"\b(l'an dernier|l'annee derniere|l'an passe|l'annee passee|last year)\b", q):
        return out(date(today.year - 1, 1, 1), date(today.year, 1, 1), str(today.year - 1))
    if _re.search(r"\b(cette annee|this year)\b", q):
        return out(date(today.year, 1, 1), today + timedelta(days=1), str(today.year))

    # 4. seasons: "l'été dernier" = the last COMPLETED summer; "cet été",
    # "en été" = the last one begun; "l'été 2023" = that one
    m = _re.search(rf"\b(l'|le |la |cet |cette |ce |this |last |en |in |the |^)({_SEASON_RE})"
                   rf"(?: (dernier|derniere|passe|passee|(?:of )?((?:19|20)\d\d)))?\b", q)
    if m and m.group(1) in ("the ", "") and not m.group(4):
        m = None  # "the summer" alone places nothing
    if m:
        season = m.group(2)
        start_month, n = _SEASONS[season]
        last = m.group(1) == "last " or m.group(3) in ("dernier", "derniere", "passe", "passee")
        if m.group(4):
            year = int(m.group(4))
        else:
            year = next(y for y in range(today.year, today.year - 3, -1)
                        if (_month_window(y, start_month, n)[1] <= today if last
                            else _month_window(y, start_month, n)[0] <= today))
        s_, e_ = _month_window(year, start_month, n)
        return out(s_, e_, f"{season} {year}")

    # 5. month (with or without a year)
    m = _re.search(rf"\b({_MONTH_RE})(?: (?:de |of )?((?:19|20)\d\d))?\b", q)
    if m and not (m.group(1) == "may" and not m.group(2)
                  and not _re.search(r"\b(in|during|since) may\b", q)):
        # "may" alone is mostly an English verb: "in May" is required
        month = _MONTHS[m.group(1)]
        if m.group(2):
            year = int(m.group(2))
        else:
            if not _re.search(rf"\b(en|in|au mois de|during|since|depuis|de|d') ?{m.group(1)}\b", q):
                return None
            year = _last_occurrence(month, today)
        s, e = _month_window(year, month)
        return out(s, e, f"{m.group(1)} {year}")

    # 6. year alone
    m = _re.search(r"\b(?:en|in|during|pendant|since|depuis)? ?((?:19|20)\d\d)\b", q)
    if m:
        year = int(m.group(1))
        return out(date(year, 1, 1), date(year + 1, 1, 1), str(year))
    return None


def window_bounds(c: dict | None) -> tuple | None:
    """The bounds of a cue as UTC datetimes, for the database and for rank."""
    if not c:
        return None

    def at(d):
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None
    return at(c["debut"]), at(c["fin"])
