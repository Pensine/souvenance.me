"""Charge affective d'un souvenir — modèle circumplexe (Russell, 1980).

Deux axes indépendants plutôt qu'un curseur bon/mauvais :

    valence   -1 (pénible) … 0 (neutre) … +1 (heureux)
    arousal    0 (éteint, calme) … 1 (vif, intense)

Le second axe n'est pas un raffinement décoratif : sans lui, le chagrin et la
colère — tous deux négatifs, l'un sourd, l'autre vif — deviennent le même
souvenir. C'est aussi lui qui module la consolidation nocturne : un souvenir
intense résiste à l'oubli.

`None` signifie « non déterminé » et ne vaut jamais 0 : ne rien savoir de ce
qui était ressenti n'est pas savoir que c'était neutre. Le rappel omet alors
la clé plutôt que d'afficher un affect neutre inventé.
"""

_NEUTRAL_BAND = 0.25   # en deçà, la valence ne penche ni d'un côté ni de l'autre
_CALM_BAND = 0.35      # en deçà, l'épisode est éteint plutôt que vif

_LABELS = {
    ("negative", "vif"): "pénible, intense",
    ("negative", "eteint"): "pénible, sourd",
    ("positive", "vif"): "heureux, vif",
    ("positive", "eteint"): "heureux, paisible",
    ("neutre", "vif"): "neutre, sous tension",
    ("neutre", "eteint"): "neutre, calme",
}


def parse(item: dict) -> tuple[float | None, float | None]:
    """Lit `valence` et `arousal` d'une mémoire produite par le modèle.

    Une valeur non numérique ou hors bornes est refusée plutôt que ramenée dans
    l'intervalle : un affect inventé contamine le corpus, et l'événement brut
    reste dans le log pour une relecture ultérieure. Les deux axes sont validés
    séparément — une aberration sur l'un n'emporte pas l'autre.
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
    """Libellé lisible, ou None si la charge n'a pas été déterminée.

    Un seul des deux axes suffit à produire un libellé partiel : savoir que
    l'épisode était intense sans savoir s'il était bon ou mauvais reste une
    information, et l'effacer serait perdre ce qu'on sait.
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
    """Bloc `ressenti` du rappel, ou None quand rien n'a été déterminé.

    Les valeurs brutes accompagnent le libellé : le libellé sert à la lecture,
    les nombres servent au tri et à la comparaison.
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
