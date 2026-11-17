"""Neural readers under the proof layer: what a model reads better than a rule.

Measured on SOURCED: hand-written subject rules (pensine/atoms.py, 253de05)
went from 37 % to 3 % attribution errors on the dev phrasing they were
written on, and stayed at 26 % on the sealed held-out phrasing. Grammar
rules do not generalize; a reading model does. So the sentence is READ by an
existing model, and the code only crosses its two readings:

  - GLiNER2 (fastino/gliner2-multi-v1, Apache-2.0, FR/EN, CPU): the people
    and roles a sentence names, and the head of the relation it states;
  - the subject is the head of the most confident relation that is a person
    or a role the sentence names ("Ivo's aunt lives in …" → Ivo's aunt;
    "Mistral Joinery, where Bianca works" → Bianca);
  - a sentence naming no one is the diary voice, the owner's;
  - a sentence naming someone whose relation head is no one stays unread
    (None): honest, never the owner by default.

The proof contract stays in code (pensine/evidence.py): a subject read here
is still a reading; the memory keeps the excerpt that carries it.

Optional: without the `gliner2` package or its weights, `subject` returns
None and the caller keeps the model's word (except its owner default).
PENSINE_READER=none disables it (tests, machines without the model).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

MODEL = os.environ.get("PENSINE_READER_MODEL", "fastino/gliner2-multi-v1")
OWNER = "I"

PEOPLE = ["person", "relative, friend or other role of a person"]
# Generic relations: their head is whom the sentence states something about.
# Not the benchmark's predicates: what a life-log sentence says about someone.
# No "said" / "told" / "met": their head is the speaker or the one met, not
# whom the fact is about ("Oskar asked about my best friend, who works at …").
RELATIONS = ["lives in", "works at", "moved to", "joined", "started", "bought", "has",
             "wants", "likes"]
THRESHOLD = 0.5
_FIRST = {"i", "me", "my", "myself", "je", "j", "moi", "me", "mon", "ma", "mes"}


@lru_cache(maxsize=1)
def _model():
    if os.environ.get("PENSINE_READER", "gliner2") == "none":
        return None
    try:
        from gliner2 import GLiNER2
        return GLiNER2.from_pretrained(MODEL)
    except Exception:  # missing package or weights: no reading, not a crash
        return None


def available() -> bool:
    return _model() is not None


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", (text or "").lower().replace("’", "'")))


def _overlaps(head: str, mention: str) -> bool:
    h, m = _words(head), _words(mention)
    return bool(h and m and (h & m))


def subject(sentence: str, model=None) -> str | None:
    """Whom one sentence states its fact about, as written ("Ivo's aunt",
    "Bianca", "ma grande sœur"), OWNER for the diary voice and the first
    person, or None when the reading does not say."""
    model = model or _model()
    s = (sentence or "").strip()
    if model is None or not s:
        return None
    ents = model.extract_entities(s, PEOPLE, threshold=THRESHOLD)["entities"]
    named = [e for label in PEOPLE for e in ents.get(label, [])]
    named = [e for e in named if not (_words(e) <= _FIRST)]
    if not named:
        return OWNER  # no one named: the diary voice ("Watered the plants")
    rels = model.extract_relations(s, RELATIONS, include_confidence=True,
                                   threshold=THRESHOLD)["relation_extraction"]
    heads = sorted(((r["head"]["confidence"], r["head"]["text"])
                    for found in rels.values() for r in found), reverse=True)
    for _, head in heads:
        if _words(head) and _words(head) <= _FIRST:
            return OWNER  # "I am doing well here", "Je vis à Lyon"
        if any(_overlaps(head, e) for e in named):
            return _as_written(head, s)
    return None


_POSSESSIVE = r"(?:my|our|his|her|their|mon|ma|mes|notre|nos|son|sa|ses|leur|[A-Z][\w-]*['’]s)"


def _as_written(head: str, sentence: str) -> str:
    """The head with the possessive the sentence gives it: "brother" in
    "… that my brother works …" is "my brother", never a bare role. A name
    needs none ("Kofi's brother Elias" is Elias)."""
    if head[:1].isupper():
        return head
    m = re.search(rf"\b({_POSSESSIVE})\s+(?:\w+\s+)?{re.escape(head)}\b", sentence,
                  re.IGNORECASE)
    if m and not head.lower().startswith(m[1].lower()):
        return sentence[m.start():m.end()]
    return head


# ------------------------------------------------------------ entailment

NLI_MODEL = os.environ.get("PENSINE_NLI_MODEL",
                           "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")
# Measured against Sonnet 5.5 as reference judge, rescuing only what the
# word-level check refused: agreement 77 → 89 of 93 memories on the dev run
# (1a17d6f), 74 → 82 of 90 on the sealed set (253de05), no added false
# support on either. 0.7 and 0.8 tie on dev; 0.8 is the stricter.
ENTAILS = 0.8


@lru_cache(maxsize=1)
def _nli():
    if os.environ.get("PENSINE_NLI", "mdeberta") == "none":
        return None
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(NLI_MODEL)
        mod = AutoModelForSequenceClassification.from_pretrained(NLI_MODEL).eval()
        return tok, mod, mod.config.label2id.get("entailment", 0)
    except Exception:  # missing package or weights: no rescue, not a crash
        return None


def entailment(premise: str, hypothesis: str) -> float | None:
    """P(the excerpts entail the memory), mDeBERTa-v3 XNLI (MIT, FR/EN, CPU),
    or None without the model. A paraphrase the word-level check refuses
    ("Spent hours at dinner with a best friend named Kasper") is read here."""
    nli = _nli()
    if nli is None or not (premise or "").strip() or not (hypothesis or "").strip():
        return None
    import torch
    tok, mod, ent = nli
    x = tok(premise[:1500], hypothesis, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        return float(torch.softmax(mod(**x).logits, -1)[0][ent])
