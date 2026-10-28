"""Which language a deposit is written in — so that its memories are too.

A memory written in another language than its deposit breaks three things:
the person reads their own life translated, the cited excerpt (always copied
in the deposit's language) no longer matches the sentence it supports, and a
question asked in the deposit's language finds the memory less well.

Detection is deliberately small: function words, no dependency, no model.
It only has to tell apart the languages a person actually deposits in, on
texts of a sentence or more. It answers None when it does not know — a short
"OK, see you" proves nothing — and the caller then falls back to the
deposits' language as a whole.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

# Function words specific enough to one language. Words shared by two of
# them ("a", "on", "en", "de", "la", "un", "una", "non", "ha"…) are left out.
_STOPWORDS = {
    "en": "the and is was were of to with that this have has had i my me you it for but "
          "not at from they we be been will would just about what so our your are there "
          "their after before today really which when who did does his her she he him don't i'm it's i'd i've i'll".split(),
    "fr": "le les des du est et une je il elle nous vous pas que qui pour dans "
          "sur avec mais tres ai avons ete au aux ce cette mon mes son sa ses "
          "aujourd hui hier demain plus ca etait fait suis sont avait".split(),
    "es": "el los las y por para pero muy esta fue hoy yo nosotros tambien "
          "como estoy tengo hemos".split(),
    "de": "der die das und ist nicht ich mit sich auf fur ein eine war wir heute auch "
          "aber bei nach habe sind".split(),
    "it": "lo gli della che sono ho mio anche molto oggi questo questa perche "
          "siamo sei".split(),
}
_INDEX = {w: lang for lang, words in _STOPWORDS.items() for w in words}
_INDEX["'elision"] = "fr"

# How the prompts name each language: in French (the prompts' language) and
# in the language itself (the final instruction is written in it, which small
# models follow far better than a rule in another language).
NAMES = {
    "en": ("anglais", "English"),
    "fr": ("français", "French"),
    "es": ("espagnol", "Spanish"),
    "de": ("allemand", "German"),
    "it": ("italien", "Italian"),
}
WRITE_IN = {
    "en": "Write every memory, intention and reason in English, like the deposits. "
          "Do not translate.",
    "fr": "Écris chaque mémoire, intention et raison en français, comme les dépôts. "
          "Ne traduis pas.",
    "es": "Escribe cada recuerdo, intención y razón en español, como los depósitos. "
          "No traduzcas.",
    "de": "Schreibe jede Erinnerung, Absicht und Begründung auf Deutsch, wie die "
          "Einträge. Nicht übersetzen.",
    "it": "Scrivi ogni ricordo, intenzione e motivo in italiano, come i depositi. "
          "Non tradurre.",
}

# Words only: "D0001" or "16h26" are identifiers, not a French "d" or "h".
_TOKEN = re.compile(r"(?<![a-z0-9])[a-z]+(?:'[a-z]+)?(?![a-z0-9])")
# French elision, which only counts with its apostrophe ("j'ai", "qu'il").
_ELISION = {"c", "d", "j", "l", "m", "n", "s", "t", "qu", "jusqu", "lorsqu", "puisqu"}


def _tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("’", "'")
    out = []
    for tok in _TOKEN.findall(t):
        if tok in _INDEX:  # "don't", "i'm", "it's"
            out.append(tok)
            continue
        head, _, tail = tok.partition("'")
        if tail and head in _ELISION:  # "j'ai" → an elision, then "ai"
            out += ["'elision", tail]
        else:
            out += [head, tail] if tail else [head]
    return out


# Letters (or one-letter words) that only one of these languages uses: they
# matter on short sentences with few function words ("Kofi a déménagé à Turin").
_MARKS = {"fr": re.compile(r"(?<!\w)à(?!\w)|[çœêâôîûë]"), "it": re.compile(r"(?<!\w)è(?!\w)|[ìò]"),
          "es": re.compile(r"[ñ¿¡áíóú]"), "de": re.compile(r"[äöüß]")}


def detect(text: str, *, min_hits: int = 3) -> str | None:
    """The language code of `text`, or None when the evidence is too thin
    (fewer than `min_hits` function words or marks, or no clear winner)."""
    counts = Counter(_INDEX[t] for t in _tokens(text) if t in _INDEX)
    low = (text or "").lower()
    for lang, mark in _MARKS.items():
        counts[lang] += len(mark.findall(low))
    counts = +counts  # drop zeros
    if not counts:
        return None
    (best, n), *rest = counts.most_common(2) + [(None, 0)]
    second = rest[0][1]
    if n < min_hits or n < 2 * second:
        return None
    return best


def majority(codes) -> str | None:
    """The most frequent known code among `codes` (None ignored)."""
    counts = Counter(c for c in codes if c)
    return counts.most_common(1)[0][0] if counts else None
