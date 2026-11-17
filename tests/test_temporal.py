"""The temporal engine is computed in code, never by the LLM -- hence testable."""

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
    # ~14 months back: two summers lived since (2025 and 2026)
    d = humanize_delta(datetime(2025, 6, 1, tzinfo=timezone.utc), NOW)
    assert "il y a 14 mois" in d
    assert "deux étés en arrière" in d


def test_annees():
    assert "ans" in humanize_delta(datetime(2023, 8, 4, tzinfo=timezone.utc), NOW)


def test_futur_en_jours():
    assert humanize_delta(datetime(2026, 8, 10, tzinfo=timezone.utc), NOW) == "dans 6 jours"


def test_a_state_belongs_to_every_period_it_was_true_in():
    """Measured on dev3 (Sonnet 5.5, 3981614): "In which city did Anton live
    on 9 February?" missed "lives in Rotterdam" (5 → 16 February), whose
    validity started before the period."""
    from datetime import datetime, timezone
    from pensine import temporal
    d = lambda day: datetime(2025, 2, day, tzinfo=timezone.utc)
    window = (d(8), d(11))
    lived = {"type": "semantic", "valid_from": d(5), "valid_to": d(16)}
    assert temporal.in_window(lived, window)
    assert not temporal.in_window({**lived, "valid_to": d(7)}, window)      # over before
    assert not temporal.in_window({"type": "semantic", "valid_from": d(16), "valid_to": None},
                                  window)                                   # began after
    assert temporal.in_window({"type": "semantic", "valid_from": d(1), "valid_to": None}, window)
    # an event is in the period only if it happened in it
    assert not temporal.in_window({"type": "episodic", "valid_from": d(5), "valid_to": None},
                                  window)
    assert temporal.in_window({"type": "episodic", "valid_from": d(9), "valid_to": None}, window)
