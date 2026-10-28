# Results on the 2-week sample: harness validation only

**These are not benchmark results.** The sample is tiny (30 facts, 33
deposits, 37 questions). The judge is the lexical one, which is a harness
check and not the published judge (SPEC §6). No real model wrote any
memory. These runs show that the pipe works end to end and that the scorer
gives the expected numbers on systems whose truth we know.

Reproduce from `research/benchmarks/sourced`:

```bash
python -m sourced run   --data sample --system <oracle|injected|verbatim> --out results/<s>.run.json --inject-rate 0.2
python -m sourced score --data sample --run results/<s>.run.json --out results/<s>.report.json
docker compose -p sourced-eval up -d
python -m sourced run   --data sample --system pensine --pensine-mode scripted --out results/pensine-scripted.run.json
python -m sourced score --data sample --run results/pensine-scripted.run.json --out results/pensine-scripted.report.json
```

| Run | Invention | Excerpt support | Fact recall | Recall @ inv ≤ 1 % | QA (abst. incl.) |
|---|---|---|---|---|---|
| control: oracle | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| control: injected (target 20 %) | 0.21 (8/38) | 0.79 | 1.00 | 1.00 | 1.00 |
| baseline: verbatim | 0.00 | 1.00 | 0.40 | 0.40 | 0.16 |
| Pensine, scripted extractor | 0.12 (6/49) | 0.82 | 1.00 | 0.53 | n/a (context hit 0.96, upper bound) |

## What the scripted Pensine run shows

In `scripted` mode, a deterministic script stands in for the consolidation
model. It writes every gold fact with its exact quote, and it adds two kinds
of known inventions. The run measures Pensine's code-level evidence gate
(`pensine/evidence.py`, `PENSINE_VERIFY=code`), not its extraction.

- **Made-up quotes are caught.** All 7 photo descriptions came with a
  quote that is not in any deposit. The gate rejected all 7.
- **Real quotes with the wrong modality get through.** 6 hedged sentences
  were quoted word for word but stated as done: a plan, a hypothesis, a
  negation, hearsay, a rumour. The gate kept all 6. Checking that the words
  exist cannot tell "maybe I'll learn to sail" from "learned to sail". This
  is the job of the model re-read (`PENSINE_VERIFY=modele`, not exercised
  here) or of a dedicated modality check.
- **Legitimate inference is capped.** Memories that name the city of a
  photo, derived from its GPS position, are flagged ("detail absent from
  the deposit") and their confidence is capped at 0.5. They then sit at the
  same confidence as other flagged memories, which is why recall at
  invention ≤ 1 % drops to 0.53.
- **Context hit rate (0.96)** is the share of text-answer questions whose
  gold answer appears somewhere in `recall()`'s context. It is an upper
  bound on retrieval, not an accuracy: no reader model ran.

These observations come from 49 memories on one seed. They point at what to
measure next. They are not findings.

## First real run: Pensine with Qwen 3.5 4B (local), 2026-10-28

`pensine-qwen3.5-4b.run.json`: Pensine at commit c0b62a8, backend `openai`
→ `mlx_lm.server` serving `mlx-community/Qwen3.5-4B-MLX-4bit` (thinking
off, temperature 0), `PENSINE_VERIFY=modele`. Measured on a Mac with 16 GB:
69 min, model peak footprint 8.7 GB. Still one seed and a toy sample. The
QA numbers below are scored in code and do not depend on the judge.

- **Nights**: 8 of 14 consolidated. From 11 February on, every night failed
  because the model returned invalid JSON, and the backlog grew from 6 to 18
  deposits. The move and the job change (15 February) never reached memory.
  A growing backlog plus a small model fails in cascade. This is the most
  useful finding of the run.
- **Store**: 24 memories, **written in French** from English deposits
  (Pensine's prompt is French). The lexical judge cannot read across
  languages, so write-time metrics wait for the model judge
  (`*.report.phi4.json`, Phi-4 14B, still running when this was written).
- **QA** (37 questions, abstention included): accuracy 0.43. 0 invented
  answers on the 7 abstention questions. Answered precision 0.69 at
  coverage 0.35. Several answers came back in French ("Édimbourg"): city
  exonyms are now accepted by the matcher.
- **Modality**: Qwen kept the hedges it saw ("envisage de s'installer à
  Turin si l'offre…", "n'a pas [pu] s'inscrire au marathon"). The
  conditional flaw found in scripted mode (a real quote stated as done)
  stays a test case of the benchmark. Its fix belongs to the support check.

## Second real run: robust consolidation, same model, 2026-10-28

Same sample, same model (`mlx-community/Qwen3.5-4B-MLX-4bit` on
`mlx_lm.server --temp 0 --chat-template-args '{"enable_thinking":false}'`),
backend `openai`, `PENSINE_VERIFY=modele`, embeddings `nomic`, default
settings (`PENSINE_CONSOLIDATION_ATTEMPTS=2`, no batch cap). Code changes
since the first run: tolerant JSON reading and a stricter re-ask, splitting
of a failing night down to single deposits, field-level repair of the
answer and a savepoint per batch (`consolidation/nightly.py`,
`pensine/llm.py`), and memories written in the deposit's language
(`pensine/language.py`). `mlx_lm.server` ignores `response_format`, so
structured output played no part here.

Two after-runs, because the second one fixed what the first one showed
(reread corrections translated into French):

| | before (09abaa7) | after (1bb37f1) | after (b2e12b1) |
|---|---|---|---|
| Nights consolidated without failure / 14 | 8 | 14 (2 split once) | 14 |
| Deposits pending after the last night | 18 | 0 | 0 |
| Memories written | 24 | 50 | 51 |
| Memories in English (decidable) | 1/24 | 44/49 | 48/50 |
| QA accuracy (abstention incl., 37 q.) | 0.43 | 0.70 | 0.68 |
| Coverage (answered rate) | 0.35 | 0.65 | 0.76 |
| Answered precision | 0.69 | 0.83 | 0.71 |
| Invented answers (7 abstention q.) | 0 / 7 | 1 / 7 | 2 / 7 |
| Fact recall (lexical judge) | 0.20 | 0.43 | 0.47 |
| Wall time | 69 min | 59 min | 43 min |

`pensine-qwen3.5-4b-robust-1bb37f1.*` and `pensine-qwen3.5-4b-robust.*`.
"Decidable" = the function-word detector of `pensine/language.py` could
tell the language (min. one hit); the 2 French memories left at b2e12b1
are the two photos of night 1, fixed afterwards (57b8f5a, checked on that
night alone, not on a full rerun).

Reading:

- **No night is lost any more.** The backlog never builds up, so the move
  and the job change reach memory, and the questions on them get answered.
  Most of the QA gain comes from there.
- **Invented answers went from 0 to 1-2 of 7.** With more memories, the
  reader answers more often, sometimes wrongly on an abstention question
  (one answer quoted a photo memory, another named a letting agency).
  It is the reader's discipline, not the store: the question is now
  whether those answers come from memories the gate should have stopped.
  The model judge (Phi-4, not run here) is what measures that.
- **The two after-runs differ** (precision 0.83 vs 0.71) although the
  server runs at temperature 0: changes in between touch the prompt, and
  `mlx_lm` is not bit-deterministic across runs. One seed, 37 questions:
  differences of a few questions are noise.

French non-regression (not SOURCED: 8 synthetic French and 8 English
deposits, batches of 4, same model, `VERIFY=code`), share of memories in
the deposits' language: French 14/14 before, 8/8 after; English 0/8
before, 8/8 after.
