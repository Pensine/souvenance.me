"""Embeddings: clean degradation and task prefixes.

The nomic prefix is not cosmetic -- without 'search_query: ' /
'search_document: ', search quality drops sharply. We therefore test it
explicitly, without loading the model (500 MB).
"""

import pytest

from pensine import embeddings


@pytest.fixture(autouse=True)
def _vide_le_cache():
    embeddings.embed.cache_clear()
    embeddings._degraded_warned = False
    yield
    embeddings.embed.cache_clear()
    embeddings._model = None
    embeddings._degraded_warned = False


def test_desactive_renvoie_none(monkeypatch):
    monkeypatch.setattr("pensine.config.EMBEDDINGS_ENABLED", False)
    assert embeddings.embed("peu importe") is None


def test_modele_absent_degrade_sans_casser(monkeypatch, caplog):
    monkeypatch.setattr("pensine.config.EMBEDDINGS_ENABLED", True)
    monkeypatch.setattr(embeddings, "_load",
                        lambda: (_ for _ in ()).throw(ImportError("pas de modèle")))
    assert embeddings.embed("peu importe") is None  # recall falls back to full-text
    # ...but never silently: a full-text search passing itself off
    # as semantic would be a lie by the system.
    assert "degrades" in caplog.text
    caplog.clear()
    embeddings.embed("une autre requête")
    assert caplog.text == ""  # warned once, not on every call


class _FauxModele:
    """Captures what is actually encoded."""

    def __init__(self):
        self.vu = []

    def encode(self, text, **kwargs):
        self.vu.append(text)
        return [0.1, 0.2, 0.3]


def _branche(monkeypatch, backend="nomic"):
    faux = _FauxModele()
    monkeypatch.setattr("pensine.config.EMBEDDINGS_ENABLED", True)
    monkeypatch.setattr("pensine.config.EMBEDDING_BACKEND", backend)
    monkeypatch.setattr(embeddings, "_load", lambda: faux)
    return faux


def test_prefixe_query(monkeypatch):
    faux = _branche(monkeypatch)
    assert embeddings.embed("qu'est-ce que je pensais de X ?") == (0.1, 0.2, 0.3)
    assert faux.vu == ["search_query: qu'est-ce que je pensais de X ?"]


def test_prefixe_document(monkeypatch):
    faux = _branche(monkeypatch)
    embeddings.embed("une mémoire consolidée", kind="document")
    assert faux.vu == ["search_document: une mémoire consolidée"]


def test_kind_inconnu_retombe_sur_query(monkeypatch):
    faux = _branche(monkeypatch)
    embeddings.embed("texte", kind="n'importe quoi")
    assert faux.vu[0].startswith("search_query: ")


def test_bge_m3_sans_prefixe(monkeypatch):
    faux = _branche(monkeypatch, backend="bge-m3")
    faux.encode = lambda texts, **kw: {"dense_vecs": [[0.4, 0.5]]}
    assert embeddings.embed("texte brut", kind="document") == (0.4, 0.5)
