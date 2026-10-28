"""Local embeddings — two backends, chosen by PENSINE_EMBEDDING_BACKEND:

- 'nomic'  : nomic-embed-text-v1.5 (768-d, ~500 MB of RAM) — default, fits on
             a small VPS. Requires task prefixes ('search_query: ' /
             'search_document: '): without them, quality drops sharply.
- 'bge-m3' : BAAI/bge-m3 (1024-d, ~2 GB) — better in French, for the day the
             RAM allows it. No prefix.

Degrades gracefully if the model is missing: recall falls back to full-text
search rather than breaking — capture never depends on the intelligent layer
(zero-maintenance principle of the founding document).
"""

import logging
from functools import lru_cache

from . import config

log = logging.getLogger("pensine.embeddings")

_model = None
_degraded_warned = False


def _warn_degraded(reason: str) -> None:
    """Degradation must never be silent: a full-text search passing itself off
    as semantic is a lie by the system. Warn once per process, not on every call."""
    global _degraded_warned
    if not _degraded_warned:
        _degraded_warned = True
        log.warning("Embeddings unavailable (%s) — recall degrades to "
                    "full-text search. Check PENSINE_EMBEDDING_BACKEND "
                    "and the model installation.", reason)

# nomic distinguishes the query from the document; stored memories are
# documents, searches are queries.
_NOMIC_PREFIXES = {"query": "search_query: ", "document": "search_document: "}


def _load():
    global _model
    if _model is None:
        if config.EMBEDDING_BACKEND == "bge-m3":
            from FlagEmbedding import BGEM3FlagModel  # heavy import, deferred
            _model = BGEM3FlagModel(config.EMBEDDING_MODEL, use_fp16=False)
        else:
            from sentence_transformers import SentenceTransformer  # same
            _model = SentenceTransformer(config.EMBEDDING_MODEL,
                                         trust_remote_code=True)
    return _model


@lru_cache(maxsize=512)
def embed(text: str, kind: str = "query") -> tuple[float, ...] | None:
    """Dense vector, or None if embeddings are unavailable.

    `kind`: 'query' (we are searching) or 'document' (we are storing a memory)."""
    if not config.EMBEDDINGS_ENABLED:
        return None
    try:
        model = _load()
    except Exception as e:
        _warn_degraded(f"model loading: {type(e).__name__}: {e}")
        return None
    try:
        if config.EMBEDDING_BACKEND == "bge-m3":
            out = model.encode([text], return_dense=True)
            vector = out["dense_vecs"][0]
        else:
            prefix = _NOMIC_PREFIXES.get(kind, _NOMIC_PREFIXES["query"])
            vector = model.encode(prefix + text, normalize_embeddings=True)
        return tuple(float(x) for x in vector)
    except Exception as e:
        _warn_degraded(f"encoding: {type(e).__name__}: {e}")
        return None
