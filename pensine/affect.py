"""Affective charge of a memory — circumplex model (Russell, 1980).

Two independent axes rather than a good/bad slider:

    valence   -1 (painful) … 0 (neutral) … +1 (happy)
    arousal    0 (flat, calm) … 1 (vivid, intense)

The second axis is not a decorative refinement: without it, grief and anger —
both negative, one dull, the other vivid — become the same memory. It is also
what modulates nightly consolidation: an intense memory resists forgetting.

`None` means "undetermined" and is never 0: knowing nothing about what was
felt is not knowing that it was neutral. Recall then omits the key rather than
displaying an invented neutral affect.

The labels returned by `label()` / `describe()` (and the `ressenti` /
`intensite` keys) are deliberately French: they are recall output over a
French-language memory corpus.
"""

_NEUTRAL_BAND = 0.25   # below this, valence leans neither one way nor the other
_CALM_BAND = 0.35      # below this, the episode is flat rather than vivid

_LABELS = {
    ("negative", "vif"): "pénible, intense",
    ("negative", "eteint"): "pénible, sourd",
    ("positive", "vif"): "heureux, vif",
    ("positive", "eteint"): "heureux, paisible",
    ("neutre", "vif"): "neutre, sous tension",
    ("neutre", "eteint"): "neutre, calme",
}


def parse(item: dict) -> tuple[float | None, float | None]:
    """Read `valence` and `arousal` from a memory produced by the model.

    A non-numeric or out-of-range value is rejected rather than clamped into
    the interval: an invented affect contaminates the corpus, and the raw
    event stays in the log for later review. The two axes are validated
    separately — an aberration on one does not take the other down.
    """
    def read(key: str, lo: float, hi: float) -> float | None:
        raw = item.get(key)
        if raw is None or isinstance(raw, bool):
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        return val if lo <= val <= hi else None

    return read("valence", -1.0, 1.0), read("arousal", 0.0, 1.0)


def label(valence: float | None, arousal: float | None) -> str | None:
    """Human-readable label, or None if the charge was not determined.

    A single axis is enough to produce a partial label: knowing that the
    episode was intense without knowing whether it was good or bad is still
    information, and erasing it would lose what we know.
    """
    if valence is None and arousal is None:
        return None

    if valence is None:
        return "intense" if arousal >= _CALM_BAND else "calme"
    if arousal is None:
        if valence <= -_NEUTRAL_BAND:
            return "pénible"
        if valence >= _NEUTRAL_BAND:
            return "heureux"
        return "neutre"

    if valence <= -_NEUTRAL_BAND:
        tone = "negative"
    elif valence >= _NEUTRAL_BAND:
        tone = "positive"
    else:
        tone = "neutre"
    energy = "vif" if arousal >= _CALM_BAND else "eteint"
    return _LABELS[(tone, energy)]


def describe(valence: float | None, arousal: float | None) -> dict | None:
    """The `ressenti` block of recall, or None when nothing was determined.

    The raw values accompany the label: the label is for reading, the numbers
    are for sorting and comparison.
    """
    text = label(valence, arousal)
    if text is None:
        return None
    out: dict = {"ressenti": text}
    if valence is not None:
        out["valence"] = round(float(valence), 2)
    if arousal is not None:
        out["intensite"] = round(float(arousal), 2)
    return out
