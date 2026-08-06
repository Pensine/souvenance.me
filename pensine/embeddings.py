"""Embeddings locaux — deux backends, choisis par PENSINE_EMBEDDING_BACKEND :

- 'nomic'  : nomic-embed-text-v1.5 (768-d, ~500 Mo de RAM) — défaut, tient sur
             un petit VPS. Exige des préfixes de tâche ('search_query: ' /
             'search_document: ') : sans eux, la qualité chute nettement.
- 'bge-m3' : BAAI/bge-m3 (1024-d, ~2 Go) — meilleur en français, pour le jour
             où la RAM le permet. Aucun préfixe.

Dégrade proprement si le modèle est absent : recall bascule en plein-texte
plutôt que de casser — la capture ne dépend jamais de la couche intelligente
(principe zéro-MCO du document fondateur).
"""

import logging
from functools import lru_cache

from . import config

log = logging.getLogger("pensine.embeddings")

_model = None
_degraded_warned = False


def _warn_degraded(reason: str) -> None:
    """La dégradation ne doit jamais être silencieuse : une recherche en
    plein-texte qui se fait passer pour sémantique est un mensonge du système.
    On avertit une fois par process, pas à chaque appel."""
    global _degraded_warned
    if not _degraded_warned:
        _degraded_warned = True
        log.warning("Embeddings indisponibles (%s) — recall dégrade en "
                    "recherche plein-texte. Vérifiez PENSINE_EMBEDDING_BACKEND "
                    "et l'installation du modèle.", reason)

# nomic distingue la requête du document ; les mémoires stockées sont des
# documents, les recherches des requêtes.
_NOMIC_PREFIXES = {"query": "search_query: ", "document": "search_document: "}


def _load():
    global _model
    if _model is None:
        if config.EMBEDDING_BACKEND == "bge-m3":
            from FlagEmbedding import BGEM3FlagModel  # import lourd, différé
            _model = BGEM3FlagModel(config.EMBEDDING_MODEL, use_fp16=False)
        else:
            from sentence_transformers import SentenceTransformer  # idem
            _model = SentenceTransformer(config.EMBEDDING_MODEL,
                                         trust_remote_code=True)
    return _model


@lru_cache(maxsize=512)
def embed(text: str, kind: str = "query") -> tuple[float, ...] | None:
    """Vecteur dense, ou None si les embeddings sont indisponibles.

    `kind` : 'query' (on cherche) ou 'document' (on stocke une mémoire)."""
    if not config.EMBEDDINGS_ENABLED:
        return None
    try:
        model = _load()
    except Exception as e:
        _warn_degraded(f"chargement du modèle : {type(e).__name__}: {e}")
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
        _warn_degraded(f"encodage : {type(e).__name__}: {e}")
        return None
