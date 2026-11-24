#!/usr/bin/env python3
"""The model reads, the code proves: a two-minute demo of the admission gate.

A language model proposes memories from a person's deposits; before anything
is written, plain code checks that each memory quotes words that really are in
the deposit it claims to come from. A second gate does the same for identity
links ("my sister" = "Lena").

Everything here is synthetic: a fictional person (Maya), three invented
deposits, and five candidate memories written by hand the way a model returns
them. No database, no network, no model: the gate is code, so the demo runs
with the standard library only and gives the same output every time.

Usage, from the repository root:

    python3 examples/admission-demo/demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Deterministic and offline: no paraphrase model (it would be downloaded),
# no machine-specific settings read from a local .env.
os.environ["PENSINE_NLI"] = "none"
os.environ["PENSINE_OWNER_NAME"] = "Maya"
os.environ["PENSINE_EVIDENCE_MODALITY"] = "off"
os.environ["PENSINE_TIMEZONE"] = "UTC"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pensine import evidence, identity  # noqa: E402

# -- What the person deposited (the append-only log keeps these forever) -----
DEPOSITS = [
    {"id": 1, "occurred_at": "2026-03-02T08:10:00+00:00",
     "payload": {"kind": "note", "text": "Started the new job at the ferry company today. "
                 "My sister Lena drove me to the harbour because the bus was cancelled."}},
    {"id": 2, "occurred_at": "2026-03-04T19:40:00+00:00",
     "payload": {"kind": "voice", "transcript": "Long day. I think I might sign up for the "
                 "spring half-marathon, but my knee still hurts after ten kilometres."}},
    {"id": 3, "occurred_at": "2026-03-06T12:05:00+00:00",
     "payload": {"kind": "message", "from": "Lena", "to": "Maya",
                 "text": "Dinner at Mum's on Sunday? Bring the photos from Porto."}},
]

# -- What a model proposed after reading them (written by hand for the demo) -
CANDIDATES = [
    {"label": "no excerpt cited",
     "memory": {"content": "Maya is unhappy in her new job.", "source_event_ids": [1],
                "preuve": []}},
    {"label": "excerpt that is not in the deposit",
     "memory": {"content": "Maya's sister Lena lives near the harbour.", "source_event_ids": [1],
                "preuve": ["Lena lives five minutes from the harbour"]}},
    {"label": "excerpt found, a number the deposit does not hold",
     "memory": {"content": "Maya's knee hurts after 15 km.", "source_event_ids": [2],
                "preuve": ["my knee still hurts after ten kilometres"]}},
    {"label": "excerpt found word for word",
     "memory": {"content": "Maya started a new job at a ferry company.", "source_event_ids": [1],
                "preuve": ["Started the new job at the ferry company today"]}},
    {"label": "excerpt found despite typography",
     "memory": {"content": "Lena invited Maya to dinner at their mother's on Sunday.",
                "source_event_ids": [3],
                "preuve": ["Dinner at Mum’s on Sunday"]}},
]

STATUS = {
    "verifiee": "ADMITTED  (excerpt found, every detail in the deposit)",
    "a_verifier": "KEPT, FLAGGED  (no second reader here: confidence capped at 0.5)",
}
REASON = {
    "aucun_extrait": "no excerpt cited",
    "extrait_introuvable": "excerpt not found in the deposit",
}


def admission() -> None:
    print("1. Memory admission: each candidate must quote its deposit\n")
    for c in CANDIDATES:
        trace: list[str] = []
        kept, _ = evidence.verify([c["memory"]], DEPOSITS, owner="Maya", trace=trace)
        print(f"   - {c['memory']['content']}")
        print(f"     cites: {c['memory']['preuve'] or '(nothing)'}")
        if kept:
            ev = kept[0]["evidence"]
            print(f"     -> {STATUS.get(ev['statut'], ev['statut'])}")
            for motif in ev["motifs"]:
                print(f"        flag: {motif.replace('absent du dépôt :', 'not in the deposit:')}")
        else:
            print(f"     -> REFUSED  ({REASON.get(trace[-1], trace[-1])}); "
                  "the deposit stays in the log, nothing is lost")
        print()


def identity_links() -> None:
    print("2. Identity links: \"my sister\" = \"Lena\" only with an excerpt that says so\n")
    source = "\n".join(evidence.source_text(d) for d in DEPOSITS)
    claims = [
        ("my sister", "Lena", "Lena lives five minutes from the harbour"),   # not in any deposit
        ("my sister", "Lena", "Dinner at Mum's on Sunday"),                  # real, but proves nothing
        ("my sister", "Lena", "My sister Lena drove me to the harbour"),     # real, and links the two
    ]
    for alias, name, excerpt in claims:
        ok, why = identity.admit(alias, name, excerpt, source)
        verdict = "ADMITTED" if ok else "REFUSED"
        print(f"   - \"{alias}\" = \"{name}\", excerpt: \"{excerpt}\"")
        print(f"     -> {verdict}  ({why})\n")


if __name__ == "__main__":
    print("Synthetic deposits:")
    for d in DEPOSITS:
        p = d["payload"]
        print(f"   [{d['id']}] {p['kind']:<7} {p.get('text') or p.get('transcript')}")
    print()
    admission()
    identity_links()
    print("What this shows: the model proposes, plain code decides what is written.")
    print("What it does not show: that the gate catches every wrong memory. A quote")
    print("proves the words exist, not that the reading is right; see the README.")
