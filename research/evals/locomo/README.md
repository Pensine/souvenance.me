# LoCoMo eval — the Pensine measured on a public benchmark

Measures the engine on **LoCoMo-10** (Maharana et al., ACL 2024 — 10 very
long, dated, multi-session fictional conversations, 1,986 questions):
the standard benchmark for long-term conversational memory systems,
the one Mem0 publishes its scores on. This is the promise made in §11 of the
founding document: "measured against native memories on a public
benchmark".

## Safety — nothing touches production

- A **throwaway** database: a dedicated compose project (`locomo-eval`), port 5442,
  its own volume. One PostgreSQL database per conversation (`locomo_c1`…`c10`)
  to avoid any contamination between samples.
- The scripts set `PENSINE_DATABASE_URL` **themselves** (never read from a
  `.env`): writing into a real Pensine by accident is impossible.
- A neutral constitution (`constitution-eval.yaml`): no exclusions.
- Full reset: `docker compose -p locomo-eval down -v`.

## Running it

```bash
cd research/evals/locomo
./download.sh                          # dataset (2.8 MB — not committed, no
                                       # licence declared by snap-research)
docker compose -p locomo-eval up -d    # the throwaway database

cd ../../..
./.venv/bin/python research/evals/locomo/ingest.py --conv 1
./.venv/bin/python research/evals/locomo/run.py --conv 1
./.venv/bin/python research/evals/locomo/score.py
```

**Starting from a blank page** — mandatory between two measurements, and after
any trial with the `fake` backend (its fabricated memories would stay in the
database and batches already marked would be skipped):

```bash
./.venv/bin/python research/evals/locomo/ingest.py --conv 1 --reset
```

Smoke test (2 consolidation cycles, 5 questions):

```bash
./.venv/bin/python research/evals/locomo/run.py --conv 1 --max-batches 2 --limit 5
```

LLM backend: the one from the Pensine config (`PENSINE_LLM_BACKEND` —
`claude-cli` by default, `api`, or `ollama` for the open-weights
condition). Embeddings: nomic by default (~550 MB downloaded on the
first call).

## Design (and why)

- **1 event = 1 dated session**, `transcript` payload (the `messages` key
  would trigger the `_slim` compressor, with its 4,000-character budget).
- **Consolidation in chronological batches of 6** with a **frozen clock** set to
  the evening of the batch: `{{TODAY}}` and the `valid_from` fallback fall within
  the corpus's own time (2023), not on the run date. We call
  `nightly.consolidate()` directly and skip `forgetting_decay`,
  `links.decay` and `gist.promote`: their SQL `now()` would see a corpus
  "3 years old" and wear everything down from the first cycle.
- **QA**: clock frozen to the day after the last session; each
  question goes through `recall()` (the real MCP path, called from Python),
  then the backend answers with that context alone. `--depth source` by
  default: absolute temporal questions ("when…?", 321 questions)
  need the ISO dates of the source events — `summary` mode only
  returns humanised deltas.
- **Automatic resume**: consolidation is marked batch by batch
  (`consolidation_marks`), answers go to append-only JSONL — re-running picks up
  where it stopped.
- **Scoring**: SQuAD-style token-overlap F1 per category (1 multi-hop,
  2 temporal, 3 open-domain, 4 single-hop); category 5 (adversarial,
  446 questions): abstention score — the right answer is "No
  information".

## Known limits (accepted, to be documented with the results)

- `recall` **mutates the database** (Hebbian reinforcement of links,
  `last_accessed_at`): question order has an effect. Runs are not
  independent without a reset (`down -v` + re-ingestion).
- `db.search_memories`: hard limit of 8 memories; `links.expand`:
  6 neighbours. These are the production settings — we measure the engine as it
  is.
- The F1 judge under-scores correct answers phrased differently
  (paraphrases); an LLM judge (Mem0's method, J score) is the next
  step for a direct comparison.
- Published baseline numbers (LoCoMo paper, Mem0) must be
  copied **from the papers**, with version and judge method — never
  from a model's memory.

## Order of magnitude of the cost (full run, 10 conversations)

- Consolidation: ~10 × 30 sessions / 6 ≈ **50 LLM calls** (large prompts).
- QA: **1,986** short calls (+ 1,986 with an LLM judge).
- On a subscription CLI backend (claude-cli): no extra cost but slow (sequential,
  rate limits). With a mid-size API model: a few tens of euros — to be
  refined on the smoke test before launching the full run.
