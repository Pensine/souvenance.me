# 002 — Lived time

**Working title:** *Temporal framing computed in code, not inferred by the
model: an ablation on multi-session conversational memory.*

**Author:** Nicolas Noguera · Souvenance

**Type:** empirical. Measurement, not argument — the companion paper 001 needs
to stop being an opinion.
**Status:** protocol. Pre-registered below, **written before any run**, so that
a negative result is publishable rather than quietly dropped.
**Target:** Zenodo preprint with DOI; code and results in this folder.

---

## The claim under test

Paper 001 §3.4 asserts that temporal arithmetic computed in code is
model-independent by construction, and is therefore one of the few properties
that transfers unchanged across model generations. That assertion is currently
unmeasured. This paper measures it.

**H1.** Injecting temporal framing computed in code — elapsed durations,
relative ordering, validity intervals expressed in natural language — improves
accuracy on temporal questions over a multi-session corpus, compared with
supplying raw timestamps and leaving the arithmetic to the model.

**H2 (the one that matters).** The size of that advantage **shrinks as model
capability rises.** If it does, then §3.4 is true but heading toward
irrelevance: the models will stop needing the crutch. If it holds steady across
a capability range, the architectural claim survives.

H2 is the reason this experiment is worth running. H1 alone is close to
obvious.

## Why this is falsifiable, and what would kill it

Stated before the data exists:

- **If condition B does not beat condition A** on temporal accuracy, §3.4 of
  paper 001 loses its strongest leg and the paper is revised to say so.
- **If B beats A only through added context length**, the effect is an artefact
  of token count, not of temporal computation. The token-matched control (C3)
  exists to catch exactly this, and if it catches it, the result is negative.
- **If the advantage disappears on the strongest model tested**, H2 fails.
  Paper 001 §3.4 gets rewritten: computing time in code is defensive
  engineering with a shelf life, not a durable primitive. **We will publish
  that.**

## Data

**LoCoMo** (Maharana et al., ACL 2024), public. Chosen for three reasons: it is
multi-session (up to 35 sessions, ~300 turns), it carries an explicit
**temporal reasoning** question category, and paper 001 §2.2 already cites that
category as the weakest across published systems — so a gain there is a gain on
the acknowledged hard case.

**Never on the author's own corpus.** A result nobody can reproduce is not a
result (see [`../../README.md`](../../README.md)). The private instance is
where the architecture runs, not where it is evaluated.

Secondary corpus if time allows: a temporal split from a second public
benchmark, to check the effect is not a LoCoMo artefact.

## Conditions

All conditions receive the same retrieved evidence. **Only the temporal
presentation differs.**

| # | Condition | Temporal information supplied |
|---|---|---|
| A | **Raw timestamps** | ISO-8601 timestamp per turn. Model does all arithmetic. |
| B | **Code-computed framing** | Timestamp *plus* framing computed deterministically: elapsed duration to query time, ordering relative to other retrieved items, validity interval where the fact has one. |
| C1 | **Floor** | No temporal information at all. Establishes how much of the score is answerable without time. |
| C2 | **Timestamps + explicit instruction** | As A, plus an instruction to compute durations carefully step by step. Separates "the model can't" from "the model doesn't bother". |
| C3 | **Token-matched placebo** | As A, plus filler text matching B's token count but carrying no temporal content. **The control that decides whether the effect is real.** |

C2 and C3 are the conditions that make this worth publishing. Without C3 a
positive result means nothing; without C2 we cannot distinguish a capability
limit from a prompting artefact.

## Models

At least three, spanning a deliberate capability range — a small open-weights
model, a mid-tier, and a frontier model. H2 is only testable across a spread;
one model would make the whole exercise uninterpretable.

Every model runs every condition. Fixed decoding parameters, temperature 0
where available, three seeds where sampling cannot be disabled.

## Metrics

Primary: accuracy on the temporal question category, per condition per model.

Reported broken down by question subtype, because an aggregate hides the
mechanism:
- absolute date recall
- ordering of two events
- elapsed duration between events
- relative-to-event framing ("before the move", "after she left")

Secondary: accuracy on non-temporal categories, as a regression check —
temporal framing must not degrade ordinary recall. If it does, that is a
finding and it goes in the abstract.

Reported with confidence intervals. Effect sizes, not just win/loss. A 1-point
difference on a few hundred questions is noise, and will be labelled as such.

## Threats to validity — to be stated in the paper, not hidden

1. **LoCoMo is synthetic.** Generated multi-session dialogue is not a real
   life. The temporal structure may be more regular than a genuine corpus.
2. **Benchmark contamination.** LoCoMo predates the frontier models tested.
   Check for memorisation before trusting frontier-model scores.
3. **The framing generator is a design artefact.** Results are contingent on
   how well the code phrases durations. A weak generator produces a weak
   result and proves nothing about the architecture. The generator is published
   with the paper.
4. **Retrieval is held fixed by design**, so this measures presentation, not
   the retrieval cascade discussed in paper 001 §3.5. Different question,
   different paper.

## Deliverables

- this document — the protocol, frozen before the first run
- `run.py` — harness: conditions, model adapters, scoring
- `results/` — raw outputs and per-condition scores, committed as produced
- `paper.md` — written after the numbers exist, whichever way they fall

## Relationship to paper 001

001 argues; 002 measures one of its load-bearing claims. If 002 comes back
negative, 001 §3.4 is rewritten and the falsification list in 001 §6 gets its
first resolved entry. That is the intended behaviour of the pair, not a
failure of it.
