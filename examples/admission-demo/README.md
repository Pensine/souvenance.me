# Admission demo: the model reads, the code proves

A two-minute, offline demo of the write-time gate at the centre of the engine.
A language model reads a person's deposits and proposes memories; plain code
decides which of them are written, by checking that each one quotes words
that really are in the deposit it claims to come from. The same kind of check
guards identity links ("my sister" = "Lena").

```bash
git clone https://github.com/Pensine/souvenance.me souvenance && cd souvenance
python3 examples/admission-demo/demo.py      # Python 3.11 or later, standard library only
```

No database, no network, no model, no install step: the gate is code, so the
demo gives the same output on every machine. Everything in it is synthetic
(a fictional person, three invented deposits, five candidate memories written
by hand the way a model returns them). No real personal data is involved.

## What you should see

| candidate memory | what it cites | outcome |
|---|---|---|
| Maya is unhappy in her new job. | nothing | **refused**: no excerpt cited |
| Maya's sister Lena lives near the harbour. | a sentence no deposit contains | **refused**: excerpt not found |
| Maya's knee hurts after 15 km. | a real sentence that says "ten kilometres" | **kept, flagged**: "15" is not in the deposit; confidence capped at 0.5 |
| Maya started a new job at a ferry company. | a real sentence | **admitted** |
| Lena invited Maya to dinner at their mother's on Sunday. | a real sentence, different apostrophe | **admitted** (typography is normalised, words are not) |

Then three identity claims: an excerpt that does not exist (refused), a real
excerpt that does not name "my sister" (refused), and "My sister Lena drove me
to the harbour" (admitted).

A refused memory loses nothing: the deposit stays in the append-only log and a
later, better reader can try again. An omission can be made up for; an
invention cannot. That asymmetry is the whole design.

## What the demo calls

- `pensine.evidence.verify`: tiers 1 and 2 of the admission cascade (excerpt
  found, every number and proper noun present). In the engine, a flagged
  memory then goes to a short reread by the model (tier 3); the demo has no
  model, so the flagged one is kept with its confidence capped, which is what
  the engine does when no reread is possible. With `severity="strict"` it would
  be refused.
- `pensine.identity.admit`: the proof gate on identity links.

Tests that cover the same functions: `tests/test_evidence.py`,
`tests/test_identity.py`, and `tests/test_admission_demo.py` for this demo.

## Limits, stated plainly

- **A quote proves that the words exist, not that the reading is right.**
  "Lena invited Maya to dinner at their mother's" is admitted although no
  deposit says whose mother; the code checks numbers and proper nouns, not
  every word. The reread and the neural readers exist for that, and they are
  models, with their own error rates.
- **Checking a memory against its source is not new.** SodaMem and Eywa do it
  (see the lab's related-work page). Applying the same gate to identity links
  is the part we did not find elsewhere, and it has not yet been measured in
  isolation (no ablation).
- The demo shows the mechanism on five hand-written cases. It is not a
  measurement. Measured figures, with their limits, are in
  `research/benchmarks/sourced/results/README.md` and on
  https://souvenance.me/benchmark.
