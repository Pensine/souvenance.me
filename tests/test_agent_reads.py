"""Read log: what an agent has read is visible, and readable in plain terms."""

from datetime import datetime, timezone
from types import SimpleNamespace

from pensine.mcp_server import _client
from pensine.webapp import describe_read

AT = datetime(2026, 10, 23, tzinfo=timezone.utc)


def test_recall_liste_les_memoires_lues():
    r = {"at": AT, "action": "recall",
         "detail": {"query": "Atelier Nova", "hits": 2, "memory_ids": [46, 99],
                    "client": "claude-ai"},
         "memories": [{"id": 46, "content": "Décision de créer une SAS"},
                      {"id": 99, "content": None}]}
    text = describe_read(r)
    assert text.startswith("claude-ai searched “Atelier Nova” — 2 memories read")
    assert "#46 Décision de créer une SAS" in text
    assert "#99 (no longer exists)" in text  # the trace outlives the memory


def test_ancienne_lecture_sans_identifiants():
    r = {"at": AT, "action": "recall", "detail": {"query": "x", "hits": 3},
         "memories": []}
    text = describe_read(r)
    assert text.startswith("an agent searched")
    assert "before read tracking" in text


def test_miroir_et_curation():
    m = describe_read({"at": AT, "action": "mirror",
                       "detail": {"question": "", "memory_ids": [], "client": None},
                       "memories": []})
    assert m == "an agent opened the mirror"
    c = describe_read({"at": AT, "action": "curate",
                       "detail": {"domain": "lecture"}, "memories": []})
    assert c == "an agent asked for curation — lecture"


def test_client_au_mieux():
    assert _client(None) is None
    ctx = SimpleNamespace(request_context=SimpleNamespace(session=SimpleNamespace(
        client_params=SimpleNamespace(client_info=SimpleNamespace(name="claude-ai")))))
    assert _client(ctx) == "claude-ai"
    muet = SimpleNamespace(request_context=SimpleNamespace(session=SimpleNamespace(
        client_params=None)))
    assert _client(muet) is None
