"""Chargement du .env par config : le cron nu et systemd doivent voir pareil."""

import os

from pensine.config import _load_dotenv


def test_charge_et_nettoie(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# commentaire\n"
        "PENSINE_TEST_A=valeur\n"
        "PENSINE_TEST_B=5433              # commentaire en fin de ligne\n"
        "export PENSINE_TEST_C='entre quotes'\n"
        "ligne invalide sans egal\n",
        encoding="utf-8",
    )
    for k in ("PENSINE_TEST_A", "PENSINE_TEST_B", "PENSINE_TEST_C"):
        monkeypatch.delenv(k, raising=False)
    _load_dotenv(env)
    assert os.environ["PENSINE_TEST_A"] == "valeur"
    assert os.environ["PENSINE_TEST_B"] == "5433"
    assert os.environ["PENSINE_TEST_C"] == "entre quotes"
    for k in ("PENSINE_TEST_A", "PENSINE_TEST_B", "PENSINE_TEST_C"):
        del os.environ[k]


def test_environnement_prioritaire(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PENSINE_TEST_D=fichier\n", encoding="utf-8")
    monkeypatch.setenv("PENSINE_TEST_D", "process")
    _load_dotenv(env)
    assert os.environ["PENSINE_TEST_D"] == "process"  # systemd garde la main


def test_fichier_absent_ne_casse_pas(tmp_path):
    _load_dotenv(tmp_path / "inexistant.env")  # ne doit pas lever
