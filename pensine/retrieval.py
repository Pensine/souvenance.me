"""Recall: merging the searches and final ordering.

A memory that invents nothing is useless if it finds nothing. Two searches
complement each other:
  · the vector finds what RESEMBLES the question ("mon moral cet été"
    finds "je me sentais vidé en juillet");
  · full-text finds what NAMES it (a first name, a place, a number, a rare
    word that the embedding dilutes into the general meaning).
Their rankings are merged by rank (Reciprocal Rank Fusion), then a local
reranker, if configured, rereads the best candidates with the question in
front of it.

This module is pure (no database access): db.search_memories calls it.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata

from . import config

log = logging.getLogger("pensine.retrieval")

# ---------------------------------------------------------------------------
# Query words
# ---------------------------------------------------------------------------

# French and English stopwords (mixed corpus; the word list itself stays as is).
# Deliberately short: the IDF computed on the fly already neutralizes the
# corpus's frequent words; this list only removes question and connector
# words, which name nothing and would make any sentence come up.
STOPWORDS = frozenset("""
a ai aie au aux avec avoir c ca ce cela ces cet cette ceux chez comme d dans de
des du elle elles en est et etais etait ete etre eu fait faire il ils j je l la
le les leur leurs lui m ma mais me meme mes moi mon n ne nos notre nous on ont
ou par pas pour qu quand que quel quelle quelles quels qui quoi sa sans se ses
si son sont sur t ta te tes toi ton tu un une vos votre vous y comment
combien pourquoi est-ce suis es sommes etes avais avait avons avez avaient
the of and to in is was were be been being it its on at for with as by from
that this these those an or but not no do does did done have has had having
he she they them their his her him we us our you your i me my mine what when
where who whom which why how will would can could should shall may might must
am are there here about into over after before than then so if any some
""".split())

_WORD = re.compile(r"\w+", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercase, accent-free: the same normalization as the content_tsv
    column (to_tsvector('simple', unaccent(content)))."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def terms(query: str, max_terms: int = 12) -> list[str]:
    """The content words of a question, in order, without duplicates.

    Only [a-z0-9_] after normalization: no character can break the tsquery
    syntax. Single-digit numbers and isolated letters are ignored
    ("l", "2" name nothing).
    """
    seen: list[str] = []
    for w in _WORD.findall(normalize(query)):
        if len(w) < 2 or w in STOPWORDS or w in seen:
            continue
        if not w.isascii():
            continue  # non-Latin scripts: left to the vector
        seen.append(w)
    return seen[:max_terms]


# Full-text settings, overridable for the measurement bench
# (research/evals/rappel). Defaults: the ones retained by measurement.
LEX_PREFIX = True      # "camped" finds "camping": stem by prefix
LEX_MIN_FRAC = 0.6     # minimum score, as a fraction of the sum of IDFs
VECTOR_WEIGHT = 1.0    # weight of the vector list in the fusion


def lexeme(word: str) -> str:
    """The tsquery term for a word: itself, or its stem as a prefix.

    Neither a French nor an English stemmer (the corpus mixes both, see
    migration 013): we strip two letters from words of 6 letters or more and
    search by prefix. "camped" → camp:* (camping, camps),
    "souvenirs" → souveni:*, "pottery" → potte:*. Crude, but with no assumed
    language, and short words (names, acronyms) stay exact.
    """
    if LEX_PREFIX and len(word) >= 6 and word.isalpha():
        return word[:-2] + ":*"
    return word


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

RRF_K = 60


def fuse(ranked_lists: list[list[dict]], k: int = RRF_K,
         weights: list[float] | None = None) -> list[dict]:
    """Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009).

    score(d) = Σ_lists  weight / (k + rank(d))   (rank starting at 1)

    Why rank and not scores: a cosine distance and a full-text score do not
    live on the same scale, and their scale varies from one question to the
    next; normalizing them amounts to inventing an exchange rate. Rank, on the
    other hand, is comparable. k=60 is the paper's value, robust without
    tuning: a document at the top of a single list does not beat a document
    well placed in both.

    Each row keeps the fields of its first appearance, completed by later ones
    (the vector distance survives the fusion). The result carries
    `fusion_rank` (0 = best) and `rrf`.
    """
    weights = weights or [1.0] * len(ranked_lists)
    scores: dict[int, float] = {}
    rows: dict[int, dict] = {}
    first_seen: dict[int, int] = {}
    order = 0
    for lst, w in zip(ranked_lists, weights):
        for rank, r in enumerate(lst, start=1):
            rid = r["id"]
            scores[rid] = scores.get(rid, 0.0) + w / (k + rank)
            if rid not in rows:
                rows[rid] = dict(r)
                first_seen[rid] = order
                order += 1
            else:
                for key, value in r.items():
                    if rows[rid].get(key) is None and value is not None:
                        rows[rid][key] = value
    ordered = sorted(rows, key=lambda rid: (-scores[rid], first_seen[rid]))
    out = []
    for pos, rid in enumerate(ordered):
        row = rows[rid]
        row["rrf"] = scores[rid]
        row["fusion_rank"] = pos
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Local reranker (cross-encoder)
# ---------------------------------------------------------------------------

_reranker = None
_reranker_failed = False
last_rerank_ms: float | None = None  # for the measurement bench


def _load_reranker():
    """Load the configured cross-encoder, once per process.

    A failure never breaks recall: we warn once and keep the fusion order.
    The reranker is a refinement, not a dependency.
    """
    global _reranker, _reranker_failed
    if _reranker is not None or _reranker_failed:
        return _reranker
    try:
        from sentence_transformers import CrossEncoder  # heavy import, deferred
        _reranker = CrossEncoder(config.RERANKER_MODEL, max_length=512,
                                 device=config.RERANKER_DEVICE)
    except Exception as e:  # model missing, offline, RAM…
        _reranker_failed = True
        log.warning("Reranker unavailable (%s: %s) — recall keeps the fusion "
                    "order.", type(e).__name__, e)
    return _reranker


def rerank(query: str, rows: list[dict], top: int | None = None) -> list[dict]:
    """Re-sort the first `top` candidates by relevance as read by the model.

    The rest of the list follows, in fusion order. Without a configured or
    loadable reranker, the list comes back unchanged. `fusion_rank` is
    rewritten to reflect the final order (temporal.rank uses it).
    """
    global last_rerank_ms
    last_rerank_ms = None
    if not config.RERANKER_MODEL or len(rows) < 2:
        return rows
    model = _load_reranker()
    if model is None:
        return rows
    top = top or config.RERANK_TOP
    head, tail = rows[:top], rows[top:]
    t0 = time.perf_counter()
    try:
        scores = model.predict([(query, r["content"]) for r in head],
                               batch_size=16, show_progress_bar=False)
    except Exception as e:
        log.warning("Reranker failed (%s: %s) — fusion order kept.",
                    type(e).__name__, e)
        return rows
    last_rerank_ms = (time.perf_counter() - t0) * 1000
    ranked = [r for _, _, r in sorted(
        ((float(s), i, r) for i, (s, r) in enumerate(zip(scores, head))),
        key=lambda x: (-x[0], x[1]))]
    for r, s in zip(ranked, sorted((float(s) for s in scores), reverse=True)):
        r["rerank_score"] = s
    out = ranked + tail
    for pos, r in enumerate(out):
        r["fusion_rank"] = pos
    return out
