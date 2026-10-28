# Frugal bench — first pass (23 October 2026)

**Question.** Does a small local model, one that fits on a laptop and
soon on a phone, consolidate a life memory as faithfully
as the production model?

**Protocol.** Five real consolidation nights (23 deposits: dictated logs,
transcribed voice memos, described photos, imports), replayed with the exact
production instructions, with no prior-knowledge context. Reference:
the 51 memories written by the production model (Claude Sonnet) on those
nights. Models tested locally on a 16 GB MacBook M4 (MLX, 4-bit,
temperature 0.2). Judge: Claude Sonnet, which classifies each memory produced
(faithful, approximate, invented), checks its date, and counts the reference
memories recovered. The reference memories also go before the judge,
as a control.

> **Correction, evening of 23 October.** The first version of this table
> attributed 18% inventions to the production model. That was an artefact:
> the transcript of a 6-minute voice memo had been deleted to be
> redone (switch to language detection) just before the export. The judge
> saw that memo without its text, and the 9 memories derived from it looked
> invented. Once that deposit is left out of the calculation (table below), the
> production model invents nothing. The bench will be replayed once the transcript is
> redone.

## Corrected results (memo without a transcript left out)

| Model | Memories judged | Faithful | Approx. | Invented | Reference recovered |
|---|---|---|---|---|---|
| Reference (production) | 42 | 88% | 12% | **0%** | — |
| Qwen 3.5 4B | 26 | 73% | 19% | 8% | 56% (22/39) |
| Qwen 3.5 9B | 19 | 63% | 32% | 5% | 33% (14/42) |
| Ministral 3, 3B | 15 | 33% | 47% | 20% | 47% (14/30) |
| Gemma 4 E2B | 7 | 86% | 14% | 0% | 67% (6/9)* |

What this changes: the production model is reliable on this bench; it is
the small models that still invent (5 to 20%). For a life memory,
that is too much: frugal consolidation must not go into production without
a safeguard.

## First pass (original table, skewed by the memo without a transcript)

| Model | Usable nights | Memories | Faithful | Approx. | Invented | Correct dates | Reference recovered | Total time |
|---|---|---|---|---|---|---|---|---|
| Reference (production) | 5/5 | 51 | 73% | 10% | 18% | 100% | — | — |
| Qwen 3.5 9B | 5/5 | 19 | 63% | 32% | 5% | 95% | 27% (14/51) | 468 s |
| Qwen 3.5 4B | 4/5 | 26 | 73% | 19% | 8% | 96% | 46% (22/48) | 462 s |
| Ministral 3, 3B | 3/5 | 15 | 33% | 47% | 20% | 93% | 38% (15/39) | 380 s |
| Gemma 4 E2B | 3/5 | 7 | 86% | 14% | 0% | 100% | 67% (6/9)* | 191 s |

\* Gemma produced a usable answer only on the three smallest nights.

## What it says

1. **~~Small models do not invent more than the frontier model~~** —
   conclusion withdrawn: it rested on the artefact described above. The
   production model invents nothing; the small models do.
2. **Two weaknesses, of unequal severity.** They forget (33 to 56% of the
   reference recovered) and they invent (5 to 20%). Forgetting can be recovered:
   the raw deposit stays in the log, replayable by a better model
   later. An invention cannot: that is what must be prevented.
3. **Big nights break them.** The failures come from nights of 6,000 to
   8,500 characters: truncated or malformed answers.
4. **Qwen 3.5 4B is the best compromise** among the small models (56% of the
   reference recovered, 8% invention, 4 nights out of 5) — still far from
   production (0% invention).

## Limits

Five nights and 51 reference memories: a signal, not proof. A single
judge, from the same family as the reference. The nights were replayed without
prior knowledge, which disadvantages everyone in the same way.

## Next experiment

Require each memory to quote, word for word, the excerpt of the deposit it rests on,
and check in code that the excerpt exists: a memory whose evidence is not
found is rejected, whatever the model. Then split the big nights (one deposit at a time, or in slices of
2,000 characters) and constrain the output to JSON. Hypothesis: a 4B
passes 5 nights out of 5 and recovers clearly more on recall. If it holds, the
consolidation can run at home, without a frontier model.

Raw data and outputs: `donnees-privees/`, never versioned — they
contain a life.
