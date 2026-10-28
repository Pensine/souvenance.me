"""Perceptors — the passive sensory organs (§4).

Principle: no tool is designed for the twin; the twin does the perceiving.
Each perceptor pulls information from an existing system and reprocesses it
into candidate events; interpretation (signal vs. noise) belongs to the brain
(consolidation). A perceptor that breaks = a pause, never a loss.

A perceptor = a function `pull() -> list[dict]` where each dict has the keys
`source`, `kind`, `occurred_at` (timezone-aware datetime), `payload` (dict).
It is active if its configuration exists (opt-in via environment variable).

User-specific perceptors (e.g. a business service via MCP) are added here:
one module, one pull() function, one entry in REGISTRY.
"""

from . import calendar_ics, imap_mail

REGISTRY = {
    "calendar": calendar_ics,
    "mail": imap_mail,
}


def pull_all() -> list[dict]:
    """Pull from every active perceptor. A failure does not stop the others."""
    events, errors = [], []
    for name, module in REGISTRY.items():
        if not module.enabled():
            continue
        try:
            events.extend(module.pull())
        except Exception as exc:  # a pause, not a loss
            errors.append((name, str(exc)))
    return events, errors
