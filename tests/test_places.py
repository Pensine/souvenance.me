"""A memory has a place: coordinates, Dictaphone address, local name, era."""

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from pensine import places, temporal


def test_coordonnees_valides():
    assert places.valid(43.61, 3.87)
    assert places.valid("45.9", "6.1")
    assert not places.valid(0, 0)           # the "null island" of a silent GPS
    assert not places.valid(91, 3)
    assert not places.valid("abc", 3)
    assert not places.valid(None, None)


@pytest.mark.parametrize("name, expected", [
    ("1528–1906 Route d'Albertville.m4a", "1528–1906 Route d'Albertville"),
    ("Rue de la Paix 12.m4a", "Rue de la Paix 12"),
    ("Nouvel enregistrement 12.m4a", None),
    ("New Recording.m4a", None),
    ("Idée pour le site.m4a", None),          # renamed by hand: not a place
    ("IMG_8461.jpeg", None),
    (None, None),
])
def test_adresse_dictaphone(name, expected):
    assert places.from_filename(name) == expected


def test_distance():
    montpellier, annecy = (43.6108, 3.8767), (45.8992, 6.1294)
    assert 290 < places.distance_km(montpellier, annecy) < 320


@pytest.fixture
def geo(tmp_path):
    rows = [
        # id, name, ascii, alt, lat, lon, fclass, fcode, cc, cc2, admin1
        ["1", "Montpellier", "Montpellier", "", "43.61092", "3.87723", "P", "PPLA", "FR", "", "76"],
        ["2", "Sète", "Sete", "", "43.40280", "3.69278", "P", "PPL", "FR", "", "76"],
        ["3", "Annecy", "Annecy", "", "45.90878", "6.12565", "P", "PPLA2", "FR", "", "84"],
    ]
    (tmp_path / "cities1000.txt").write_text(
        "\n".join("\t".join(r + [""] * 8) for r in rows) + "\n", encoding="utf-8")
    (tmp_path / "admin1CodesASCII.txt").write_text(
        "FR.76\tOccitanie\tOccitanie\t11071623\nFR.84\tAuvergne-Rhône-Alpes\tARA\t11071619\n",
        encoding="utf-8")
    places._index.cache_clear()
    yield str(tmp_path)
    places._index.cache_clear()


def test_nom_de_lieu_hors_ligne(geo):
    r = places.reverse(43.611042, 3.873367, geo)   # the photo of the Porte du Peyrou
    assert r["name"] == "Montpellier" and r["region"] == "Occitanie" and r["distance_km"] < 1
    assert places.label(43.611042, 3.873367, geo_dir=geo) == "Montpellier, Occitanie (FR)"
    assert places.label(45.80, 6.20, geo_dir=geo).startswith("près de Annecy")


def test_sans_geonames_les_coordonnees_restent(tmp_path):
    places._index.cache_clear()
    assert places.reverse(43.6, 3.8, str(tmp_path)) is None
    assert places.label(43.6, 3.8, "Porte du Peyrou", geo_dir=str(tmp_path)) == "Porte du Peyrou"
    places._index.cache_clear()


def test_epoque_de_vie():
    chapters = [
        {"name": "Montpellier", "at_date": date(2020, 9, 1), "kind": "chapter_start"},
        {"name": "Montpellier", "at_date": date(2024, 6, 30), "kind": "chapter_end"},
        {"name": "Annecy", "at_date": date(2024, 7, 1), "kind": "chapter_start"},
    ]
    at = lambda y, m: datetime(y, m, 1, tzinfo=timezone.utc)  # noqa: E731
    assert temporal.epoch(chapters, at(2019, 1)) is None
    assert temporal.epoch(chapters, at(2022, 5)) == "Montpellier"
    assert temporal.epoch(chapters, at(2026, 8)) == "Annecy"


def test_lieu_envoye_avec_un_depot():
    from pensine.api import _lieu
    assert _lieu("43,611042", "3.873367", "") == {"lat": 43.611042, "lon": 3.873367,
                                                  "source": "raccourci"}
    assert _lieu("", "", "chez mes parents") == {"place": "chez mes parents", "source": "declare"}
    assert _lieu("0", "0", "") is None
    assert _lieu("", "", "") is None


def test_situer_ou_et_quand(geo, monkeypatch):
    from pensine import mcp_server
    monkeypatch.setattr(places, "GEO_DIR", __import__("pathlib").Path(geo))
    r = {"valid_from": datetime(2026, 8, 12, tzinfo=timezone.utc), "valid_to": None,
         "superseded_by": None, "archived_at": None,
         "lat": 43.611042, "lon": 3.873367, "place": None, "place_source": "gps_photo"}
    out = mcp_server._situate(r, {}, [{"name": "Annecy", "at_date": date(2024, 7, 1),
                                       "kind": "chapter_start"}])
    assert out["ou"]["lieu"] == "Montpellier, Occitanie (FR)"
    assert out["ou"]["source"] == "GPS de la photo"
    assert out["epoque"] == "Annecy"


def test_log_fichier_vide_sans_texte_refuse(monkeypatch, tmp_path):
    from pensine import api, config
    monkeypatch.setattr(config, "PENSINE_TOKEN", "t0ken")
    monkeypatch.setattr(config, "MEDIA_ROOT", tmp_path)

    def _pas_de_base():
        raise AssertionError("the database must not be touched")
    monkeypatch.setattr(api.db, "connection", _pas_de_base)
    r = TestClient(api.app).post("/log", headers={"Authorization": "Bearer t0ken"},
                                 files={"file": ("log.m4a", b"", "audio/x-m4a")})
    assert r.status_code == 422
    assert not any(tmp_path.rglob("*"))


def test_adresse_iphone_sur_une_ligne():
    from pensine.api import _lieu
    raw = "9 Rue de la Paix\r\n75002 Paris\r\nFrance"
    assert places.one_line(raw) == "9 Rue de la Paix, 75002 Paris, France"
    assert _lieu("48.86", "2.33", raw)["place"] == "9 Rue de la Paix, 75002 Paris, France"
