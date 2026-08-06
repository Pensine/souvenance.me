from fastapi.testclient import TestClient


def _client(monkeypatch, password=""):
    import pensine.webapp as webapp
    monkeypatch.setattr(webapp, "WEBAPP_PASSWORD", password)
    from pensine.api import app
    return TestClient(app)


def test_503_sans_mot_de_passe_configure(monkeypatch):
    assert _client(monkeypatch).get("/app").status_code == 503


def test_page_login_puis_session(monkeypatch):
    client = _client(monkeypatch, password="s3cret")
    r = client.get("/app")
    assert r.status_code == 200 and 'placeholder="password"' in r.text
    # mauvais mot de passe
    assert client.post("/app/login", data={"password": "faux"}).status_code == 401
    # bon mot de passe → cookie → timeline servie
    r = client.post("/app/login", data={"password": "s3cret"}, follow_redirects=True)
    assert r.status_code == 200 and "timeline" in r.text


def test_data_exige_session(monkeypatch):
    client = _client(monkeypatch, password="s3cret")
    assert client.get("/app/data").status_code == 401
