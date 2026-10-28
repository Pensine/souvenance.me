"""The right words, in the wrong mood: "peut-être que j'apprendrai la voile"
("maybe I'll learn sailing") quoted word for word under "a appris la voile"
("learned sailing").

The cited evidence checks that the excerpt exists; it does not see that the
excerpt is in the conditional, the future, a hypothesis, a wish, negated, a
question, or reported by a third party, when the memory states it as an
accomplished fact. This module sees it, in code, in French and English.

Rule: a marker in the excerpt only counts if it BEARS on what the memory
asserts — a content word of the memory appears in the few words that follow
it, within the same clause (up to the end of the sentence for "si" / "if").
"Manager is never boring" does not contradict "est manager"; "I did not sign
up for the marathon" contradicts "s'est inscrit au marathon". A memory that
itself keeps the mood ("envisage", "might", "selon Hollis") is not at fault.

This check is lexical: it misses modalities without a marker (irony, context),
and a marker near a shared word can raise a false alarm. Review by a model
remains behind it.
"""

from __future__ import annotations

import re

from .evidence import normalize

FENETRE = 6  # window size, in tokens, after a marker

# category -> markers (normalized forms: lowercase, accent-free; a
# multi-word entry is searched as a sequence of words). The French and English
# word lists are functional and stay as they are.
MARQUEURS = {
    "hypothese": [
        "maybe", "perhaps", "possibly", "probably", "might", "may be", "could", "would",
        "i'd", "we'd", "he'd", "she'd", "they'd", "you'd", "if", "unless", "whether",
        "peut etre", "peutetre", "sans doute", "probablement", "eventuellement",
        "possible que", "si", "s'il", "s'ils", "au cas ou", "a condition que",
    ],
    "futur": [
        "will", "i'll", "we'll", "he'll", "she'll", "they'll", "you'll", "going to",
        "gonna", "plan to", "plans to", "planning", "plan on", "intend", "intends",
        "next year", "next week", "next month", "someday", "one day", "soon",
        "vais", "va", "vas", "allons", "allez", "vont", "compte", "comptons", "prevois",
        "prevoit", "projette", "envisage", "envisageons", "un jour", "bientot",
        "l'an prochain", "l'annee prochaine", "la semaine prochaine", "le mois prochain",
    ],
    "souhait": [
        "wish", "hope", "hopes", "hoping", "would like", "would love", "i'd like",
        "i'd love", "dream", "dreams", "want to", "wants to", "thinking about",
        "thinking of", "considering", "keep thinking", "tempted",
        "aimerais", "aimerait", "voudrais", "voudrait", "souhaite", "souhaiterais",
        "espere", "esperons", "reve de", "revais de", "j'ai envie", "envie de",
        "pense a", "songe a", "tente de", "tente par",
    ],
    "negation": [
        "not", "no", "never", "no longer", "no more", "nobody", "nothing", "neither",
        "nor", "didn't", "don't", "doesn't", "won't", "wasn't", "isn't", "aren't",
        "haven't", "hasn't", "hadn't", "can't", "cannot", "couldn't", "wouldn't",
        "ne", "n'", "pas", "jamais", "plus jamais", "aucun", "aucune", "rien", "ni",
    ],
    "oui_dire": [
        "apparently", "reportedly", "supposedly", "allegedly", "said", "says", "told me",
        "heard", "rumour", "rumor", "according to", "they say",
        "apparemment", "parait il", "il parait", "on dit", "dit que", "m'a dit",
        "m'a raconte", "selon", "rumeur", "aurait", "auraient", "serait", "seraient",
    ],
}

# French conditional and future detected by verb ending
_COND = re.compile(r"^\w{3,}(?:rais|rait|rions|riez|raient)$")
_FUT = re.compile(r"^\w{2,}(?:erai|eras|erons|erez|eront|irai|iras|irons|irez|iront)$"
                  r"|^\w{4,}(?:rai|rons|rez|ront)$")  # apprendrai, attendrons, prendront
_FUT_IRR = {"serai", "seras", "sera", "serons", "serez", "seront", "aurai", "auras",
            "aura", "aurons", "aurez", "auront", "ferai", "feras", "fera", "ferons",
            "ferez", "feront", "irai", "iras", "ira", "irons", "irez", "iront", "pourrai",
            "pourra", "pourront", "voudrai", "voudra", "devrai", "devra", "saurai",
            "saura", "verrai", "verra", "viendrai", "viendra", "tiendrai", "tiendra",
            "faudra"}
_PAS_VERBE = {"extrait", "extraits", "portrait", "portraits", "retrait", "retraits",
              "attrait", "abstrait", "distrait", "soustrait", "trait", "traits", "frais",
              "anglais", "francais", "mais", "jamais", "desormais", "vrai", "minerai",
              "environs", "marrons", "citrons", "patrons", "escadrons", "ronrons",
              "front", "affront", "fourrez"}

_STOP = {"the", "and", "for", "with", "this", "that", "was", "were", "are", "has", "have",
         "had", "his", "her", "their", "its", "our", "your", "from", "about", "into",
         "les", "des", "une", "dans", "pour", "avec", "sur", "par", "que", "qui", "est",
         "sont", "ete", "etait", "avait", "elle", "ils", "elles", "nous", "vous", "son",
         "ses", "leur", "leurs", "cette", "ces", "aux", "mon", "mes", "ton", "tes", "lui",
         "today", "yesterday", "aujourd'hui", "hier", "very", "tres", "just", "juste",
         "really", "honestly", "vraiment", "there", "here", "ici", "la", "le"}
_IRREALIS = {"hypothese", "futur", "souhait"}
_SPLIT_PROP = re.compile(r"[,;:—–()\"«»]|\s-\s")
_SPLIT_PHRASE = re.compile(r"(?<=[.!?])\s+|\n+")


def _toks(text: str) -> list[str]:
    return [t for t in normalize(text).replace("-", " ").split() if t]


def _porteurs(text: str) -> set[str]:
    return {t for t in _toks(text) if len(t) >= 3 and t not in _STOP and not t.isdigit()}


def _proche(a: str, b: str) -> bool:
    """Same stem, no dictionary: a common prefix of at least 4 letters
    ("learn"/"learned", "move"/"moved"), or the whole word for short ones."""
    n = min(len(a), len(b), 4)
    return n >= 3 and a[:n] == b[:n] and (n == 4 or a == b or a.startswith(b) or b.startswith(a))


def _marqueurs(tokens: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, category) of each marker found in the tokens."""
    found = []
    for cat, items in MARQUEURS.items():
        for item in items:
            parts = item.split()
            n = len(parts)
            for i in range(len(tokens) - n + 1):
                if tokens[i:i + n] == parts:
                    found.append((i, i + n, cat))
    for i, t in enumerate(tokens):
        bare = t.split("'")[-1]
        if bare in _PAS_VERBE:
            continue
        if bare in _FUT_IRR or _FUT.match(bare):
            found.append((i, i, "futur"))      # the verb itself carries the mood
        elif _COND.match(bare):
            found.append((i, i, "hypothese"))
        if t.startswith("n'"):
            found.append((i, i + 1, "negation"))
    return found


# Memory side only: a negation can be expressed without a classic marker.
# "Plus de café après seize heures" does keep "je ne bois plus de café";
# "a arrêté de fumer" keeps "je ne fume plus". (In an excerpt, "plus"
# first means "more": it is not searched for there.)
_NEGATION_MEMOIRE = ("plus", "arrete", "arreter", "cesse", "fini", "renonce", "sans",
                     "refuse", "evite", "stopped", "quit", "quitted", "gave up",
                     "without", "refused", "avoids", "avoided", "no longer")


def categories(text: str, *, memoire: bool = False) -> set[str]:
    """Moods present in a text, regardless of scope."""
    toks = _toks(text)
    cats = {c for _, _, c in _marqueurs(toks)}
    if memoire and any(" ".join(toks[i:i + len(m.split())]) == m
                       for m in _NEGATION_MEMOIRE for i in range(len(toks))):
        cats.add("negation")
    if "?" in (text or ""):
        cats.add("question")
    return cats


def mismatches(content: str, excerpts: list[str]) -> list[str]:
    """Moods of the excerpts that bear on what the memory asserts without the
    memory keeping them. Returns the faulty categories (empty = nothing to flag)."""
    mem = _porteurs(content)
    if not mem:
        return []
    kept = categories(content, memoire=True)
    bad = set()
    for ex in excerpts:
        for phrase in _SPLIT_PHRASE.split(ex or ""):
            ptoks = _toks(phrase)
            if "?" in phrase and any(_proche(t, m) for t in ptoks for m in mem):
                bad.add("question")
            # clause boundaries, as token indices within the sentence
            props, start = [], 0
            for part in _SPLIT_PROP.split(phrase):
                n = len(_toks(part))
                props.append((start, start + n))
                start += n
            for i, j, cat in _marqueurs(ptoks):
                if cat in ("hypothese",) and ptoks[i] in ("if", "si", "unless", "whether"):
                    end = len(ptoks)            # "si X, Y": the scope is the whole sentence
                else:
                    end = next((b for a, b in props if a <= i < b), len(ptoks))
                    end = min(end, j + FENETRE)
                window = [t for t in ptoks[i:end] if len(t) >= 3 and t not in _STOP]
                if any(_proche(t, m) for t in window for m in mem):
                    bad.add(cat)
    out = []
    for cat in sorted(bad):
        if cat in kept or (cat in _IRREALIS and kept & _IRREALIS):
            continue                            # the memory keeps the mood: nothing to flag
        out.append(cat)
    return out
