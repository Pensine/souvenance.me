"""One fact per memory, its subject read in code; interpretation rejected."""

from pensine import atoms, evidence

NAMES = {"dina", "kasper", "elias", "oskar", "kofi", "kofi achebe"}
OWNER = "Kofi Achebe"


def split(content, subject=OWNER, preuve=None, source=None):
    m = {"type": "semantic", "content": content, "subject": subject,
         "preuve": preuve or [content], "source_event_ids": [1]}
    return [(p["content"], p.get("subject")) for p in
            atoms.atomize(m, [source or content], NAMES, OWNER)]


# --- measured on the third Qwen run (37f508d): two facts, one subject ---------

import pytest

pytestmark = pytest.mark.skipif(not atoms.readers.available(),
                                reason="GLiNER2 reader not installed (pensine/readers.py)")


@pytest.mark.xfail(reason="known reader limit: the head of 'asked about' is the speaker, "
                          "and 'received from X' reads X; a double possessive reads the first owner", strict=False)
def test_reported_speech_and_received_from_are_still_misread():
    assert split("Oskar asked about my best friend, who works at Marrowgate Press.")[0][1] == \
        "my best friend"
    assert split("Received a voice message from Oskar.")[0][1] == "I"
    assert split("Kofi's uncle's flat is in Montreal.")[0][1] == "my uncle"


def test_two_facts_about_two_people_become_two_memories():
    assert split("Watered the plants on the balcony. My aunt lives in Valencia now.") == [
        ("Watered the plants on the balcony.", "I"), ("My aunt lives in Valencia now.", "my aunt")]
    assert split("Need to buy coffee filters. Elias works from home most days.") == [
        ("Need to buy coffee filters.", "I"), ("Elias works from home most days.", "Elias")]


def test_the_fact_belongs_to_the_clause_that_carries_it():
    assert split("Ran into Dina, who works at Mistral Joinery.") == [
        ("Ran into Dina, who works at Mistral Joinery.", "Dina")]
    assert split("Told Kasper that my brother works at Larkspur Ceramics.")[0][1] == "my brother"
    assert split("Croisé Dina, qui travaille chez Nova.")[0][1] == "Dina"
    assert split("J'ai dit à Kasper que mon frère travaille à Lyon.")[0][1] == "mon frère"


def test_the_sentence_subject_otherwise():
    assert split("My uncle works at Pellucid Labs.")[0][1] == "my uncle"
    assert split("Ma grande sœur vit à Valence.")[0][1] == "ma grande sœur"
    assert split("Landlady works at Oxbow Bindery.")[0][1] == "Landlady"
    assert split("Kasper lives in Edinburgh these days.")[0][1] == "Kasper"
    assert split("Dina has not got the kayak yet.")[0][1] == "Dina"


def test_diary_voice_and_first_person_are_the_owner():
    assert split("Already got the kayak set up at home.")[0][1] == "I"
    assert split("The kayak I ordered has not arrived yet.")[0][1] == "I"
    assert split("Arrosé les plantes.")[0][1] == "I"
    assert split("Kofi went running.")[0][1] == "I"           # the owner's own name


def test_unreadable_keeps_the_model_word_but_never_its_owner_default(monkeypatch):
    assert split("The neighbours were playing music again.")[0][1] == "neighbours"
    # the reader says nothing: the model's word stays, its owner default does not
    monkeypatch.setattr(atoms.readers, "subject", lambda s, model=None: None)
    assert split("Kasper sent a postcard.")[0][1] is None
    assert split("Kasper sent a postcard.", subject="Dina")[0][1] == "Dina"


def test_same_person_and_pronouns_stay_together():
    assert split("Kasper moved to Lyon. He loves it there.") == [
        ("Kasper moved to Lyon. He loves it there.", "Kasper")]
    assert split("My aunt lives in Valencia. My aunt works at Nova.")[0][1] == "my aunt"
    assert len(split("My aunt lives in Valencia. My aunt works at Nova.")) == 1


def test_each_part_keeps_the_excerpt_that_proves_it():
    source = "Watered the plants on the balcony.\nMy aunt lives in Valencia now."
    m = {"type": "semantic", "content": "Watered the plants. My aunt lives in Valencia now.",
         "preuve": ["Watered the plants on the balcony", "My aunt lives in Valencia now"],
         "source_event_ids": [1], "remplace": [7], "raison": "moved"}
    a, b = atoms.atomize(m, [source], NAMES, OWNER)
    assert a["preuve"] == ["Watered the plants on the balcony"]
    assert b["preuve"] == ["My aunt lives in Valencia now"]
    # what was replaced goes with the fact about someone else
    assert "remplace" not in a and b["remplace"] == [7] and b["raison"] == "moved"


# --- interpretation ------------------------------------------------------------

def test_memories_about_the_record_are_interpretation():
    for text in ("Uncertainty regarding the identity of 'Silas' versus the previously "
                 "mentioned 'uncle'.",
                 "The subject reports a change in family location details, which supersedes "
                 "previous mentions.",
                 "L'utilisateur indique un déménagement.",
                 "Incertitude sur l'identité de Silas."):
        assert atoms.interpretive(text), text
    for text in ("I am uncertain about the move.", "Kasper moved to Lyon, superseding Paris.",
                 "My aunt lives in Valencia now.", "Je ne suis pas sûr de vouloir déménager."):
        assert not atoms.interpretive(text), text


def test_the_cascade_rejects_interpretation_even_with_real_excerpts():
    source = {"id": 1, "payload": {"text": "Silas lives in Porto near the harbour."}}
    m = {"type": "reflection", "source_event_ids": [1], "preuve": ["Silas lives in Porto"],
         "content": "Uncertainty regarding the identity of 'Silas' versus the uncle."}
    res = evidence.check(m, {1: source})
    assert res["status"] == "reject" and res["motifs"] == [evidence.INTERPRETATION]
    kept, report = evidence.verify([m], [source])
    assert kept == [] and report["issues"] == {"interpretation": 1}


def test_a_capitalized_verb_or_a_thing_is_not_a_person():
    # measured on the replay of 37f508d: "Received a …" read as a name
    assert split("Signed a lease for the flat.")[0][1] == "I"


def test_the_first_person_of_a_received_message_is_not_the_owner():
    m = {"type": "semantic", "content": "I am doing well here in Montreal.",
         "subject": OWNER, "preuve": ["I am doing well here in Montreal"]}
    assert atoms.atomize(m, [m["content"]], NAMES, OWNER)[0]["subject"] == "I"
    (part,) = atoms.atomize(m, [m["content"]], NAMES, OWNER, incoming=True)
    assert "subject" not in part
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    assert nightly.received({"kind": "voice_in", "payload": {}})
    assert nightly.received({"kind": "note", "payload": {"direction": "in"}})
    assert not nightly.received({"kind": "note", "payload": {"text": "x"}})


# --- measured on dev2 (Sonnet 5.5, 253de05): the owner's possessive ----------

def test_a_possessive_name_hands_the_fact_to_what_it_owns():
    assert split("Kofi's aunt lives in Edinburgh now.")[0][1] == "my aunt"
    assert split("Kofi's piano teacher lives in Leipzig now.")[0][1] == "my piano teacher"
    assert split("Kofi's brother Elias has his birthday in December.")[0][1] == "Elias"
    assert split("Dina's sister works at Nova.")[0][1] == "Dina's sister"
    assert split("Oskar's rowing machine has been in use for a while.")[0][1] == "Oskar"


def test_where_someone_works_is_about_them():
    assert split("Things at Mistral Joinery, where Dina works, sound hectic.")[0][1] == "Dina"
    assert split("Went to the cafe where I work.")[0][1] == "I"
