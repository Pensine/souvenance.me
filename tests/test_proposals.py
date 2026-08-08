"""Mémoire proposée : rien n'entre dans le substrat sans un second acte.

Ce qui est verrouillé ici est la propriété qui distingue ce système d'un
assistant du marché : l'assistant peut repérer, il ne décide pas. Le serveur ne
voit pas la conversation et ne peut donc pas vérifier un consentement — mais il
peut refuser de croire à un consentement qui n'a pas eu le temps d'exister.
"""

import pytest

from pensine import proposals


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _FakeConn:
    """Connexion minimale : enregistre les requêtes, rejoue des lignes fixées."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries: list[str] = []
        self.params: list[tuple] = []

    def execute(self, sql, params=None):
        self.queries.append(" ".join(sql.split()))
        self.params.append(params or ())
        return _FakeCursor(self.rows.pop(0) if self.rows else None)

    def wrote_to_events(self) -> bool:
        return any("INSERT INTO events" in q for q in self.queries)

    def all_params(self) -> list:
        return [v for p in self.params for v in p]


# --- Proposer n'est pas mémoriser ------------------------------------------

def test_proposer_n_ecrit_aucun_evenement():
    """La garantie centrale : une proposition n'atteint pas le substrat."""
    conn = _FakeConn([{"id": 1, "proposed_at": "2026-08-08"}])
    proposals.propose(conn, "achat d'un appartement", "fact", "engagement long")
    assert not conn.wrote_to_events()


def test_un_type_inconnu_bascule_vers_la_categorie_prudente():
    """Dans le doute, l'inférence — c'est elle qui demande le plus de retenue."""
    conn = _FakeConn([{"id": 1, "proposed_at": "2026-08-08"}])
    proposals.propose(conn, "x", kind="n'importe quoi")
    assert "inference" in conn.all_params()
    assert "n'importe quoi" not in conn.all_params()


# --- Le consentement doit avoir eu le temps d'exister ----------------------

def test_confirmation_immediate_refusee():
    """Personne ne lit une proposition et ne répond en deux secondes."""
    conn = _FakeConn([{"id": 1, "content": "x", "kind": "fact",
                       "rationale": None, "status": "pending", "age_s": 0.4}])
    with pytest.raises(proposals.NotConsented):
        proposals.confirm(conn, 1)


def test_confirmation_immediate_n_ecrit_rien():
    """Le refus doit être total : pas d'événement écrit « au cas où »."""
    conn = _FakeConn([{"id": 1, "content": "x", "kind": "fact",
                       "rationale": None, "status": "pending", "age_s": 0.1}])
    with pytest.raises(proposals.NotConsented):
        proposals.confirm(conn, 1)
    assert not conn.wrote_to_events()


def test_le_delai_minimal_laisse_le_temps_de_repondre():
    assert proposals.MIN_SECONDS_BEFORE_CONFIRM >= 3


def test_proposition_inconnue_leve_une_erreur():
    conn = _FakeConn([None])
    with pytest.raises(KeyError):
        proposals.confirm(conn, 999)


def test_une_proposition_deja_decidee_n_est_pas_rejouee():
    """Confirmer deux fois ne doit pas dupliquer l'événement."""
    conn = _FakeConn([{"id": 1, "content": "x", "kind": "fact",
                       "rationale": None, "status": "confirmed", "age_s": 900}])
    assert proposals.confirm(conn, 1) == {"already": "confirmed"}
    assert not conn.wrote_to_events()


def test_une_proposition_refusee_ne_peut_plus_etre_confirmee():
    conn = _FakeConn([{"id": 1, "content": "x", "kind": "inference",
                       "rationale": None, "status": "declined", "age_s": 900}])
    assert proposals.confirm(conn, 1) == {"already": "declined"}
    assert not conn.wrote_to_events()


# --- Le refus est une information, pas un néant ---------------------------

def test_le_refus_est_conserve():
    conn = _FakeConn([{"id": 3}])
    assert proposals.decline(conn, 3, "trop personnel") == {"declined": 3}
    joined = " ".join(conn.queries)
    assert "declined" in joined and "decline_reason" in joined


def test_refuser_n_ecrit_aucun_evenement():
    conn = _FakeConn([{"id": 3}])
    proposals.decline(conn, 3)
    assert not conn.wrote_to_events()


def test_refuser_une_proposition_deja_decidee_ne_fait_rien():
    conn = _FakeConn([None])
    assert proposals.decline(conn, 3) == {"already": "decided"}


# --- Traçabilité : la question qu'aucun assistant du marché ne sait rendre --

def test_les_evenements_portent_leur_provenance():
    """Sans origin, le déposé et le proposé deviennent indiscernables."""
    import inspect
    from pensine import db
    sig = inspect.signature(db.append_event)
    assert sig.parameters["origin"].default == "declared"


def test_la_provenance_n_entre_pas_dans_le_hash():
    """Elle qualifie le fait, elle ne le change pas — sinon le même fait
    déposé deux fois par deux voies créerait deux events."""
    import inspect
    from pensine import db
    src = inspect.getsource(db.append_event)
    hash_line = next(l for l in src.splitlines() if "event_hash(" in l)
    assert "origin" not in hash_line
