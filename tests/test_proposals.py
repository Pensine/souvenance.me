"""Proposed memory: nothing enters the substrate without a second act.

What is locked down here is the property that distinguishes this system from an
off-the-shelf assistant: the assistant may spot, it does not decide. The server
does not see the conversation and so cannot verify consent -- but it
can refuse to believe in a consent that has not had time to exist.
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
    """Minimal connection: records the requests, replays fixed rows."""

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


# --- Proposing is not memorizing -------------------------------------------

def test_proposer_n_ecrit_aucun_evenement():
    """The central guarantee: a proposal does not reach the substrate."""
    conn = _FakeConn([{"id": 1, "proposed_at": "2026-08-08"}])
    proposals.propose(conn, "achat d'un appartement", "fact", "engagement long")
    assert not conn.wrote_to_events()


def test_un_type_inconnu_bascule_vers_la_categorie_prudente():
    """When in doubt, inference -- it is the one that demands the most restraint."""
    conn = _FakeConn([{"id": 1, "proposed_at": "2026-08-08"}])
    proposals.propose(conn, "x", kind="n'importe quoi")
    assert "inference" in conn.all_params()
    assert "n'importe quoi" not in conn.all_params()


# --- Consent must have had time to exist -----------------------------------

def test_confirmation_immediate_refusee():
    """Nobody reads a proposal and answers in two seconds."""
    conn = _FakeConn([{"id": 1, "content": "x", "kind": "fact",
                       "rationale": None, "status": "pending", "age_s": 0.4}])
    with pytest.raises(proposals.NotConsented):
        proposals.confirm(conn, 1)


def test_confirmation_immediate_n_ecrit_rien():
    """Refusal must be total: no event written "just in case"."""
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
    """Confirming twice must not duplicate the event."""
    conn = _FakeConn([{"id": 1, "content": "x", "kind": "fact",
                       "rationale": None, "status": "confirmed", "age_s": 900}])
    assert proposals.confirm(conn, 1) == {"already": "confirmed"}
    assert not conn.wrote_to_events()


def test_une_proposition_refusee_ne_peut_plus_etre_confirmee():
    conn = _FakeConn([{"id": 1, "content": "x", "kind": "inference",
                       "rationale": None, "status": "declined", "age_s": 900}])
    assert proposals.confirm(conn, 1) == {"already": "declined"}
    assert not conn.wrote_to_events()


# --- Refusal is information, not a void ------------------------------------

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


# --- Traceability: the question no off-the-shelf assistant can answer ------

def test_les_evenements_portent_leur_provenance():
    """Without origin, the deposited and the proposed become indistinguishable."""
    import inspect
    from pensine import db
    sig = inspect.signature(db.append_event)
    assert sig.parameters["origin"].default == "declared"


def test_la_provenance_n_entre_pas_dans_le_hash():
    """It qualifies the fact, it does not change it -- otherwise the same fact
    deposited twice through two channels would create two events."""
    import inspect
    from pensine import db
    src = inspect.getsource(db.append_event)
    hash_line = next(l for l in src.splitlines() if "event_hash(" in l)
    assert "origin" not in hash_line
