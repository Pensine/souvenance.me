"""Percepteur agenda personnel — URL ICS privée (Google/Apple/Proton l'exportent).

Générique : fonctionne pour n'importe quel utilisateur avec une URL ICS.
Fenêtre : les événements des dernières 48 h (le cycle nocturne rattrape).
Parsing minimal sans dépendance — DTSTART, SUMMARY, LOCATION, DESCRIPTION.
"""

import urllib.request
from datetime import datetime, timedelta, timezone

from .. import config

WINDOW = timedelta(hours=48)


def enabled() -> bool:
    return bool(config.CALENDAR_ICS_URLS)


def pull() -> list[dict]:
    events = []
    since = datetime.now(timezone.utc) - WINDOW
    for url in config.CALENDAR_ICS_URLS:
        with urllib.request.urlopen(url, timeout=60) as resp:
            ics = resp.read().decode("utf-8", errors="replace")
        for vevent in parse_ics(ics):
            if vevent["start"] >= since and vevent["start"] <= datetime.now(timezone.utc):
                events.append({
                    "source": "calendar",
                    "kind": "meeting",
                    "occurred_at": vevent["start"],
                    "payload": {k: v for k, v in vevent.items() if k != "start"}
                    | {"start": vevent["start"].isoformat()},
                })
    return events


def parse_ics(ics: str) -> list[dict]:
    """Parse minimal des VEVENT. Gère les lignes pliées (RFC 5545),
    DTSTART avec TZID/UTC/DATE."""
    # Dépliage : une ligne qui commence par espace/tab continue la précédente
    lines: list[str] = []
    for raw in ics.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)

    out, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current and "start" in current:
                out.append(current)
            current = None
        elif current is not None and ":" in line:
            key, _, value = line.partition(":")
            name, _, params = key.partition(";")
            if name == "DTSTART":
                dt = _parse_dt(value, params)
                if dt:
                    current["start"] = dt
            elif name in ("SUMMARY", "LOCATION", "DESCRIPTION"):
                current[name.lower()] = value.replace("\\,", ",").replace("\\n", "\n")
    return out


def _parse_dt(value: str, params: str) -> datetime | None:
    value = value.strip()
    try:
        if "VALUE=DATE" in params or (len(value) == 8 and value.isdigit()):
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        # TZID non résolu sans base de fuseaux : on prend l'heure naïve en UTC
        # (suffisant pour situer un rendez-vous dans la journée)
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
