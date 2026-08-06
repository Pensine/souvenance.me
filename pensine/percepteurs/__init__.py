"""Percepteurs — les organes sensoriels passifs (§4).

Principe : aucun outil n'est conçu pour le jumeau, c'est le jumeau qui perçoit.
Chaque percepteur tire de l'information d'un système existant et la retraite
en events candidats ; l'interprétation (signal/bruit) appartient au cerveau
(consolidation). Un percepteur qui casse = une pause, jamais une perte.

Un percepteur = une fonction `pull() -> list[dict]` où chaque dict a les clés
`source`, `kind`, `occurred_at` (datetime aware), `payload` (dict).
Il est actif si sa configuration existe (opt-in par variable d'environnement).

Les percepteurs propres à un utilisateur (ex. un coach sportif via MCP)
s'ajoutent ici : un module, une fonction pull(), une entrée dans REGISTRY.
"""

from . import calendar_ics, imap_mail

REGISTRY = {
    "calendar": calendar_ics,
    "mail": imap_mail,
}


def pull_all() -> list[dict]:
    """Tire tous les percepteurs actifs. Un échec n'arrête pas les autres."""
    events, errors = [], []
    for name, module in REGISTRY.items():
        if not module.enabled():
            continue
        try:
            events.extend(module.pull())
        except Exception as exc:  # pause, pas perte
            errors.append((name, str(exc)))
    return events, errors
