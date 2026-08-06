"""Le moteur temporel est calculé en code, jamais par le LLM — donc testable."""

from datetime import datetime, timezone

from pensine.temporal import humanize_delta


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def test_aujourdhui():
    assert humanize_delta(NOW, NOW) == "aujourd'hui"


def test_hier_demain():
    assert humanize_delta(datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc), NOW) == "hier"
    assert humanize_delta(datetime(2026, 8, 5, 13, 0, tzinfo=timezone.utc), NOW) == "demain"


def test_jours_et_semaines():
    assert humanize_delta(datetime(2026, 7, 30, tzinfo=timezone.utc), NOW) == "il y a 5 jours"
    assert "semaines" in humanize_delta(datetime(2026, 7, 1, tzinfo=timezone.utc), NOW)


def test_mois_et_etes():
    # ~14 mois en arrière : deux étés vécus depuis (2025 et 2026)
    d = humanize_delta(datetime(2025, 6, 1, tzinfo=timezone.utc), NOW)
    assert "il y a 14 mois" in d
    assert "deux étés en arrière" in d


def test_annees():
    assert "ans" in humanize_delta(datetime(2023, 8, 4, tzinfo=timezone.utc), NOW)


def test_futur_en_jours():
    assert humanize_delta(datetime(2026, 8, 10, tzinfo=timezone.utc), NOW) == "dans 6 jours"
