"""Token gate of the MCP server: Bearer, secret path, ?token=."""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from pensine.mcp_auth import TokenGate

TOKEN = "s3cret-jeton"


async def _echo(request):
    return JSONResponse({"path": request.url.path, "query": request.url.query})


def _client(token: str = TOKEN) -> TestClient:
    inner = Starlette(routes=[Route("/mcp", _echo, methods=["GET", "POST"]),
                              Route("/mcp/sub", _echo)])
    return TestClient(TokenGate(inner, token))


def test_sans_jeton_refuse():
    r = _client().get("/mcp")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")


def test_bearer():
    r = _client().get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.json()["path"] == "/mcp"


def test_bearer_faux():
    r = _client().get("/mcp", headers={"Authorization": "Bearer autre"})
    assert r.status_code == 401


def test_chemin_secret_reecrit_vers_mcp():
    r = _client().post(f"/mcp/{TOKEN}")
    assert r.status_code == 200 and r.json()["path"] == "/mcp"


def test_chemin_secret_avec_suite():
    r = _client().get(f"/mcp/{TOKEN}/sub")
    assert r.status_code == 200 and r.json()["path"] == "/mcp/sub"


def test_chemin_secret_faux():
    assert _client().post("/mcp/presque-le-jeton").status_code == 401
    assert _client().post(f"/mcp/{TOKEN}x").status_code == 401


def test_query_token_retire_avant_l_application():
    r = _client().get(f"/mcp?token={TOKEN}&autre=1")
    assert r.status_code == 200
    assert "token" not in r.json()["query"] and "autre=1" in r.json()["query"]


def test_query_token_faux():
    assert _client().get("/mcp?token=non").status_code == 401


def test_jeton_vide_interdit():
    with pytest.raises(ValueError):
        TokenGate(lambda *a: None, "")


def test_sans_jeton_configure_application_nue():
    from pensine import mcp_server
    from pensine.mcp_auth import TokenGate as Gate

    assert not isinstance(mcp_server.http_app("0.0.0.0", token=""), Gate)
    assert isinstance(mcp_server.http_app("0.0.0.0", token=TOKEN), Gate)


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "test", "version": "0"}}}
HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}


def test_vrai_serveur_mcp_par_chemin_secret():
    """End to end on the real MCP application: the secret path opens
    the session, the bare address stays closed."""
    from pensine import mcp_server

    with TestClient(mcp_server.http_app("0.0.0.0", token=TOKEN)) as client:
        assert client.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        r = client.post(f"/mcp/{TOKEN}", json=INIT, headers=HEADERS)
        assert r.status_code == 200, r.text
        assert "Pensine" in r.text
