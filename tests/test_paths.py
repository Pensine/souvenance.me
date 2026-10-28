"""Data folders: a single root, PENSINE_DATA_DIR, and the legacy
server keeps its locations (/var/lib, /var/backups, /var/log)."""

import os
import subprocess
import sys
from pathlib import Path

from pensine.config import default_data_dir

ROOT = Path(__file__).resolve().parent.parent


def test_linux_avec_dossier_historique(tmp_path):
    legacy = tmp_path / "var-lib-pensine"
    legacy.mkdir()
    assert default_data_dir("linux", tmp_path, legacy, is_root=False) == legacy


def test_linux_root_sans_dossier(tmp_path):
    legacy = tmp_path / "absent"
    assert default_data_dir("linux", tmp_path, legacy, is_root=True) == legacy


def test_linux_utilisateur(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    got = default_data_dir("linux", tmp_path, tmp_path / "absent", is_root=False)
    assert got == tmp_path / ".local" / "share" / "souvenance"


def test_linux_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    got = default_data_dir("linux", tmp_path, tmp_path / "absent", is_root=False)
    assert got == tmp_path / "xdg" / "souvenance"


def test_macos(tmp_path):
    legacy = tmp_path / "present"
    legacy.mkdir()  # ignored outside Linux
    got = default_data_dir("darwin", tmp_path, legacy, is_root=True)
    assert got == tmp_path / "Library" / "Application Support" / "Souvenance"


def _resolve(env: dict) -> dict:
    base = {k: v for k, v in os.environ.items() if not k.startswith("PENSINE_")}
    # empty rather than absent: config loads ROOT/.env without overwriting what
    # exists, and on the VPS this .env sets these folders explicitly
    base.update({k: "" for k in ("PENSINE_DATA_DIR", "PENSINE_MEDIA_ROOT", "PENSINE_GEO_DIR",
                                 "PENSINE_BACKUP_DIR", "PENSINE_LOG_DIR", "PENSINE_KEYS_DIR",
                                 "PENSINE_KEYS_BACKUP_DIR")})
    base.update(env, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-m", "pensine.config"], cwd="/",
                         env=base, capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


def test_tout_derive_de_data_dir(tmp_path):
    got = _resolve({"PENSINE_DATA_DIR": str(tmp_path)})
    assert got["PENSINE_MEDIA_ROOT"] == str(tmp_path / "media")
    assert got["PENSINE_GEO_DIR"] == str(tmp_path / "geo")
    assert got["PENSINE_BACKUP_DIR"] == str(tmp_path / "backups")
    assert got["PENSINE_LOG_DIR"] == str(tmp_path / "logs")
    # the keys and their backup: never under BACKUP_DIR (distinct retentions)
    assert got["PENSINE_KEYS_DIR"] == str(tmp_path / "keys")
    assert got["PENSINE_KEYS_BACKUP_DIR"] == str(tmp_path / "keys-backups")


def test_variables_explicites_gagnent(tmp_path):
    got = _resolve({"PENSINE_DATA_DIR": str(tmp_path),
                    "PENSINE_MEDIA_ROOT": "/ailleurs/media",
                    "PENSINE_BACKUP_DIR": "/ailleurs/sauvegardes"})
    assert got["PENSINE_MEDIA_ROOT"] == "/ailleurs/media"
    assert got["PENSINE_BACKUP_DIR"] == "/ailleurs/sauvegardes"
    assert got["PENSINE_GEO_DIR"] == str(tmp_path / "geo")


def test_serveur_historique_inchange():
    got = _resolve({"PENSINE_DATA_DIR": "/var/lib/pensine"})
    assert got["PENSINE_MEDIA_ROOT"] == "/var/lib/pensine/media"
    assert got["PENSINE_GEO_DIR"] == "/var/lib/pensine/geo"
    assert got["PENSINE_BACKUP_DIR"] == "/var/backups/pensine"
    assert got["PENSINE_LOG_DIR"] == "/var/log/pensine"


def test_script_shell_lit_la_meme_regle(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PENSINE_")}
    env["PENSINE_DATA_DIR"] = str(tmp_path / "avec espace")
    out = subprocess.run(
        ["bash", "-c", '. scripts/paths.sh && printf "%s" "$PENSINE_GEO_DIR"'],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
    assert out == str(tmp_path / "avec espace" / "geo")
