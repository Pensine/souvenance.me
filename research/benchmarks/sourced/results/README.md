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
