"""Cycle clock of the `nightly` container: crontab table, correct hours,
no skipped cycle."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
import scheduler  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_table_docker_lisible():
    jobs = scheduler.load(ROOT / "deploy" / "docker" / "crontab")
    names = [j.name for j in jobs]
    assert names == ["nightly", "rem_weekly", "persona_compiler", "backup"]


def test_nuit_a_3h30():
    job = scheduler.Job("30 3 * * * python consolidation/nightly.py")
    assert job.next_after(datetime(2026, 10, 24, 12, 0)) == datetime(2026, 10, 25, 3, 30)
    assert job.next_after(datetime(2026, 10, 25, 3, 29)) == datetime(2026, 10, 25, 3, 30)
    assert job.next_after(datetime(2026, 10, 25, 3, 30)) == datetime(2026, 10, 26, 3, 30)


def test_rem_le_dimanche():
    job = scheduler.Job("0 4 * * 0 python consolidation/rem_weekly.py")
    nxt = job.next_after(datetime(2026, 10, 21, 0, 0))  # a Wednesday
    assert nxt == datetime(2026, 10, 25, 4, 0) and nxt.isoweekday() == 7
    assert scheduler.Job("0 4 * * 7 x.py").next_after(datetime(2026, 10, 21)) == nxt


def test_premier_du_mois():
    job = scheduler.Job("0 5 1 * * python consolidation/persona_compiler.py")
    assert job.next_after(datetime(2026, 10, 24)) == datetime(2026, 11, 1, 5, 0)


def test_listes_pas_et_plages():
    assert scheduler.parse_field("*/15", 0, 59) == {0, 15, 30, 45}
    assert scheduler.parse_field("1-3,10", 0, 23) == {1, 2, 3, 10}
    with pytest.raises(ValueError):
        scheduler.parse_field("61", 0, 59)


def test_ligne_incomplete():
    with pytest.raises(ValueError):
        scheduler.Job("30 3 * *")


def test_run_ecrit_le_journal(tmp_path, monkeypatch):
    from pensine import config
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    job = scheduler.Job("* * * * * echo bonjour  # essai.sh")
    assert scheduler.run(job) == 0
    assert "bonjour" in (tmp_path / "essai.log").read_text()
