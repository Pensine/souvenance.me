"""The deposit rejects what is not a deposit, before writing anything."""

from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer t0ken"}


def _client(monkeypatch, tmp_path):
    from pensine import api, config
    monkeypatch.setattr(config, "PENSINE_TOKEN", "t0ken")
    monkeypatch.setattr(config, "MEDIA_ROOT", tmp_path)

    def _pas_de_base():
        raise AssertionError("the database must not be touched")
    monkeypatch.setattr(api.db, "connection", _pas_de_base)
    return TestClient(api.app)


def test_fichier_vide_refuse_sans_trace(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.post("/deposit", headers=AUTH,
                    files={"file": ("memo.m4a", b"", "audio/x-m4a")})
    assert r.status_code == 422
    assert r.json()["detail"] == "empty file"
    assert not any(tmp_path.rglob("*")), "no file must be written"


def test_champ_file_absent_refuse(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.post("/deposit", headers=AUTH, data={"note": "sans fichier"})
    assert r.status_code == 422


def test_champ_file_texte_vide_refuse(monkeypatch, tmp_path):
    # what a shortcut sends when its variable is empty: a text field ""
    client = _client(monkeypatch, tmp_path)
    r = client.post("/deposit", headers=AUTH, data={"file": ""})
    assert r.status_code == 422


import pytest  # noqa: E402


@pytest.mark.parametrize("ct,name,kind", [
    ("text/plain", "note.txt", "text"),
    ("text/markdown; charset=utf-8", "idees.md", "text"),
    ("application/octet-stream", "note.txt", "text"),
    ("", "carnet.md", "text"),
    ("application/json", "export.json", "text"),
    ("audio/x-m4a", "memo.m4a", "audio"),
    ("application/octet-stream", "memo.m4a", "audio"),
    ("application/octet-stream", "", "audio"),      # voice memo from the iOS shortcut
    ("image/heic", "IMG_1.heic", "photo"),
    ("video/quicktime", "clip.mov", "video"),
    ("application/pdf", "doc.pdf", "pdf"),
    ("", "doc.pdf", "pdf"),
    ("application/zip", "archive.zip", "file"),
    ("application/octet-stream", "inconnu.xyz", "file"),
])
def test_type_du_depot(ct, name, kind):
    from pensine.api import _kind
    assert _kind(ct, name) == kind
