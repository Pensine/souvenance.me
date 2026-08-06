"""Moteur temporel — le temps vécu, pas seulement le temps objectif (§7.6).

Principe non négociable : le cadre temporel est CALCULÉ EN CODE, jamais
laissé à l'arithmétique du LLM. Chaque réponse MCP embarque ce cadre.
"""

from datetime import date, datetime, timedelta, timezone


SAISONS = {12: "hiver", 1: "hiver", 2: "hiver", 3: "printemps", 4: "printemps",
           5: "printemps", 6: "été", 7: "été", 8: "été", 9: "automne",
           10: "automne", 11: "automne"}


def humanize_delta(then: datetime, now: datetime | None = None) -> str:
    """Delta humanisé : « il y a 14 mois, deux étés en arrière »."""
    now = now or datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    # Jours calendaires (pas de troncature timedelta) : « demain » reste demain
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

    # Distance en saisons vécues : combien d'étés séparent alors de maintenant
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
    """Le cadre temporel embarqué dans chaque réponse MCP :
    date, saison, position vs jalons, intentions actives pertinentes."""
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

    # Mémoire prospective : intentions dont le déclencheur est atteint.
    # Elles refont surface EN CONTEXTE — jamais en notification (règle du silence).
    due = list(conn.execute(
        """
        SELECT id, content, trigger_kind, trigger_value FROM intentions
        WHERE resolved_at IS NULL
          AND trigger_kind = 'date' AND trigger_value::date <= %s
        """,
        (today,),
    ).fetchall())
    # Déclencheur 'delta_landmark' : « J-30:nom_du_jalon »
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
