"""The place of a memory — computed on the server, never sent elsewhere.

Three sources, from the most precise to the fuzziest:
  · the GPS coordinates of a photo (EXIF) or sent by the shortcut;
  · the name iOS gives a voice memo when place-based naming is on
    ("Route d'Albertville"): an address without coordinates;
  · what the person says.

Turning coordinates into a place name usually goes through an online service,
which would thereby learn where you were. Here, we read a local copy of
GeoNames (towns and villages of more than 1,000 inhabitants, CC-BY license),
installed by scripts/install_geonames.sh. Without it, everything still works:
the coordinates remain, only the name is missing.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from . import config

GEO_DIR = Path(getattr(config, "GEO_DIR", "/var/lib/pensine/geo"))

# User-facing labels shown in French on recall cards (asserted by tests); kept in French.
SOURCE_LABELS = {
    "gps_photo": "GPS de la photo",
    "raccourci": "position envoyée au dépôt",
    "nom_dictaphone": "nom donné par Dictaphone",
    "declare": "dit par toi",
}

# Words that mark an address in a voice-memo name. A memo renamed by hand
# ("Idée pour le site") must not become a place. (Street-type words are
# French and English, so they stay as they are.)
_STREET = re.compile(
    r"\b(rue|route|avenue|av\.|chemin|boulevard|bd|place|all[ée]e|impasse|quai|"
    r"cours|esplanade|square|voie|sentier|lieu-dit|col|lac|street|st\.|road|rd\.|"
    r"avenue|lane|drive|way|square)\b", re.IGNORECASE)
_DEFAULT_NAMES = re.compile(
    r"^(nouvel enregistrement|new recording|enregistrement|recording|audio|"
    r"memo|mémo|voice|img|vid|pxl|dsc)[\s_\-]*\d*$", re.IGNORECASE)


def one_line(text: str) -> str:
    """'9 Rue X\r\n38090 Ville\r\nFrance' → '9 Rue X, 38090 Ville, France'."""
    return ", ".join(p.strip() for p in re.split(r"[\r\n]+", text or "") if p.strip())


def valid(lat, lon) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)


def from_filename(filename: str | None) -> str | None:
    """A voice-memo name that looks like an address, otherwise None."""
    if not filename:
        return None
    stem = Path(filename).stem.strip()
    if not stem or _DEFAULT_NAMES.match(stem) or not _STREET.search(stem):
        return None
    return re.sub(r"\s+", " ", stem.replace("_", " "))[:120]


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance (haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


@lru_cache(maxsize=1)
def _index(geo_dir: str) -> tuple[dict, dict] | None:
    """1° × 1° grid over the GeoNames localities, loaded once."""
    cities = Path(geo_dir) / "cities1000.txt"
    if not cities.exists():
        return None
    admin1 = {}
    a1 = Path(geo_dir) / "admin1CodesASCII.txt"
    if a1.exists():
        for line in a1.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                admin1[parts[0]] = parts[1]
    grid: dict[tuple[int, int], list] = {}
    with cities.open(encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 11:
                continue
            try:
                lat, lon = float(p[4]), float(p[5])
            except ValueError:
                continue
            grid.setdefault((math.floor(lat), math.floor(lon)), []).append(
                (lat, lon, p[1], p[8], p[10]))
    return grid, admin1


def reverse(lat: float, lon: float, geo_dir: str | None = None) -> dict | None:
    """The nearest locality: name, region, country, distance. Offline."""
    idx = _index(str(geo_dir or GEO_DIR))
    if idx is None or not valid(lat, lon):
        return None
    grid, admin1 = idx
    cy, cx = math.floor(lat), math.floor(lon)
    best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for c in grid.get((cy + dy, cx + dx), ()):
                d = distance_km((lat, lon), (c[0], c[1]))
                if best is None or d < best[0]:
                    best = (d, c)
    if best is None:
        return None
    d, (_, _, name, country, a1) = best
    return {"name": name, "region": admin1.get(f"{country}.{a1}"), "country": country,
            "distance_km": round(d, 1)}


def label(lat=None, lon=None, place: str | None = None, geo_dir: str | None = None) -> str | None:
    """The name to display: the locality if we have coordinates, else the text."""
    if lat is not None and lon is not None:
        r = reverse(lat, lon, geo_dir)
        if r:
            near = "" if r["distance_km"] < 3 else "près de "  # French on purpose (display label)
            region = f", {r['region']}" if r.get("region") else ""
            return f"{near}{r['name']}{region} ({r['country']})"
    return place
