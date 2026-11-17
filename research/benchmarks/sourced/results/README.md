# Results on the 2-week sample: harness validation only

**These are not benchmark results.** The sample is tiny (30 facts, 33
deposits, 37 questions when these runs were made). They predate the identity
layer (SPEC §3.1), which brought the sample to 34 facts, 39 deposits and 44
questions (then the dating and coverage layers: 50 facts, 60 deposits, 46
questions); base deposit and question ids did not move, but re-scoring these
runs against the current sample would count the new facts and questions as
missed. The judge is the lexical one, which is a harness
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
- **Correction (2026-10-28): one of those "inventions" was the benchmark's
  error.** Q035 asked for the landlord's name as an unanswerable question,
  yet the lease deposit (D0031) states "Landlord: Rowan Property Lettings":
  the system answered correctly. The generator no longer asks it (replaced
  by a shoe-size question, the sample's `questions.jsonl` and `truth.json`
  regenerated, nothing else changes), and a test now checks that no
  unstated question is answered by a deposit. Without Q035: 0 / 6 at
  09abaa7, 0 / 6 at 1bb37f1, 1 / 6 at b2e12b1. The remaining one (Q033,
  "what could be seen in the photo?") repeats the photo's date and GPS
  line, which is quoted, not invented, but does not abstain either; the
  lexical scorer counts it as invented, a judge may not. The table above is
  left as measured.
- **The two after-runs differ** (precision 0.83 vs 0.71) although the
  server runs at temperature 0: changes in between touch the prompt, and
  `mlx_lm` is not bit-deterministic across runs. One seed, 37 questions:
  differences of a few questions are noise.

French non-regression (not SOURCED: 8 synthetic French and 8 English
deposits, batches of 4, same model, `VERIFY=code`), share of memories in
the deposits' language: French 14/14 before, 8/8 after; English 0/8
before, 8/8 after.

## Model judge (Phi-4) on the two robustness runs, 2026-10-28

**The judge fails the injected control, so its write-time figures below are
not usable yet.** They are kept as measured, next to the control that
disqualifies them.

Setup: `microsoft/phi-4-gguf`, file `phi-4-Q4_K.gguf` (Q4_K_M,
`general.file_type` 15, sha256 `5652b9be…688f`), llama.cpp `ac8e169`,
`llama-server -c 4096 -np 1 -t 4 --cache-ram 0`, CPU only (4 vCPU Xeon
2.1 GHz, 16 GB, cloud containers; nothing ran on the owner's machine).
Prompt `7dfb69b6cd34`, temperature 0. Questions as at dad55aa (Q034/Q035
changed in 9dada83; deposit texts are identical), so QA matches the
lexical reports.

| | 1bb37f1 | b2e12b1 | injected control (final snapshot) |
|---|---|---|---|
| Memories | 50 | 51 | 38 (8 injected) |
| Invention, lexical | 0.18 (9) | 0.20 (10) | 0.21 (8) |
| Invention, Phi-4 (`unsupported`) | 0.00 (0) | 0.00 (0) | 0.08 (3) |
| Phi-4 `partial` | 0.40 (20) | 0.20 (10) | 0.37 (14) |
| Excerpt support, lexical / Phi-4 | 0.64 / 0.96 | 0.78 / 1.00 | 0.79 / 0.87 |
| Fact recall, lexical / Phi-4 | 0.43 / 0.70 | 0.47 / 0.73 | 1.00 / 1.00 |
| Wall time | 8095 s | 3138 s | 2269 s |

QA is scored in code and does not change: 0.70 and 1/7 invented answers at
1bb37f1, 0.68 and 2/7 at b2e12b1.

**Injected control.** Of the 8 injected inventions, Phi-4 labels 3
`unsupported` (the dog twice, the stolen bike) and 5 `partial`: the 4
photo descriptions ("The photo shows a sunset…", which the prompt names as
unsupported, with `citation_supports: true`) and the rumour stated as fact
(Oskar's company shut down). It also labels 9 of the 30 correct oracle
memories `partial` ("Kofi Achebe grew up in Bristol."). `unsupported` misses
5 of 8 inventions and `partial` does not separate true from false. The
lexical judge recovers the 8.

**Q033 and Q035: were the answers drawn from memories the gate should have
stopped?** No, but only Q035 is settled by a judge.

- Q035 (landlord, the benchmark error fixed in 9dada83): in both runs the
  answer comes from memories that quote the lease D0031 ("Landlord: Rowan
  Property Lettings"). Lexical and Phi-4 both label them supported, and the
  quote checks out in code. The gate was right to keep them.
- Q033 (photo content): only b2e12b1 answers it, by repeating the photo's
  date and GPS line. The memory it comes from is D0001's metadata restated
  ("Photo prise le 2025-02-03 à 16:26. GPS: …"). Both judges label it
  supported, but Phi-4's verdict carries no weight on photos given the
  control. Read by hand, the memory describes nothing, so it is not an
  invention the gate should stop. The fault is the reader's: it should
  have abstained.
- At 1bb37f1, 3 of the lexical judge's 9 inventions are restated photo
  metadata (2 in French, which it cannot read): false alarms. The other 6
  are paraphrases and an interpretation stored three times ("Contradiction
  between … implying a potential disconnect"). Phi-4 calls them supported
  or partial, but after the control that settles nothing. They need human
  labels.

Notes on the runs:

- 1bb37f1 was scored in one pass. b2e12b1 was scored in a second container
  that restarted twice. The successful pass used a resumable launcher
  outside the repo (each response cached on disk, `judge.py` unchanged)
  and `stop: ["\n```"]`, which cuts the explanation Phi-4 writes after its
  JSON. Decoding is greedy, so the verdict does not change: re-parsing the
  67 responses of 1bb37f1 cut at that point gives the same labels 67/67,
  and calls take about 1 min instead of 2. Details in
  `pensine-qwen3.5-4b-robust.report.phi4.meta.txt`.
- The injected control was scored on its final snapshot only (38
  memories, a superset of the first), with the same launcher and stop.
- An earlier try with two server slots was OOM-killed: llama-server's
  default 8 GiB prompt cache in RAM, next to the 9 GB weights. Hence
  `--cache-ram 0`. Two slots gave no throughput gain on 4 vCPU anyway.

Limits: one seed, 37 questions, 50 memories per run. The judge has not
been checked against human labels (SPEC §6, κ ≥ 0.7). It fails the
injected control here, so no Phi-4 write-time figure should be cited. Next
step: a stricter prompt or another judge model, re-checked on the injected
control before any Pensine run is rejudged.

## Third real run: identity, bounded dating and the inferred tier, 2026-10-28

`pensine-qwen3.5-4b-graph-1a17d6f.*`: Pensine at 1a17d6f (lots identity,
dating, inferred identity), same model and server settings as the second
run (`mlx-community/Qwen3.5-4B-MLX-4bit`, mlx-lm 0.32.2, thinking off,
temperature 0, `PENSINE_VERIFY=modele`, embeddings `nomic`). New sample:
60 deposits (21 new text notes), 46 questions. Wall time 100 min on the
16 GB Mac. Lexical judge only: Phi-4 failed the injected control (above).
Not comparable with the earlier runs (different sample).

| | value |
|---|---|
| Nights consolidated / pending after the last night | 14 of 14 / 0 |
| Memories written | 93 |
| Invention (lexical) | 0.22 |
| Fact recall (lexical) | 0.58 (state 0.79, change 1.00, event 0.00) |
| QA accuracy, 46 q. / coverage | 0.61 / 0.54 |
| Abstention questions correct | 7 / 7 |
| Attribution error | 0.37 (16 of 43 measurable memories) |
| Alias recall / precision | 0.33 (1 of 3) / 1.00 (no false link) |
| Identity questions | 0 / 4 |
| Attribution checks | 2 / 3 |
| Bounded-date questions | 0 / 2; one answer "between 11 and 11 February" |
| Bounds stored | 0 (2 bracketed facts, none exposed) |

Reading:

- **The safety side holds, the small model does not feed it.** No false
  identity link was admitted, and the 7 abstention questions are all
  answered "no information". But the code only decides on what the night
  proposes, and Qwen 3.5 4B proposes little: one alias out of three, no
  time bounds at all, no inferred identity.
- **Attribution error comes from the subject field, not from the graph.**
  77 of the 93 memories carry the owner as subject; 15 of the 16 wrong
  ones are the owner standing in for a relative. Many memories bundle two
  facts of different subjects in one text ("Watered the plants on the
  balcony. My aunt lives in Valencia now."), so one subject cannot be
  right. The model also wrote its own doubts as memories ("Uncertainty
  regarding the identity of 'Silas' versus the previously mentioned
  'uncle'"): an interpretation, stored.
- **Bounded dating was not exercised.** No bound reached the store, so
  `invented_precision_rate` on the store is not measurable; at read time,
  one answer collapsed the interval to a single day (an invented
  precision), the other abstained.

What to change before the next run (system first, then measure):

1. One fact per memory, and the subject checked in code: a memory whose
   text names a role or a person other than the owner ("my aunt", "Dina")
   gets its subject from the resolver, never from the model's default;
   a memory mixing two subjects is split or refused.
2. Time bounds extracted in code from the deposit text and timestamp
   ("not yet", "already", "just got", explicit dates), as the temporal
   engine already does for lived time; the model's proposals become
   optional.
3. Interpretive memories ("uncertainty regarding…", "contradiction
   between…") rejected at admission: they quote nothing that states them.
4. A judge that passes the injected control (stricter rubric, then a
   second model), before any write-time figure is cited.
5. More generator templates for identity and dating (one pattern each
   today), so a fix is not tuned to a single sentence shape.

## Claude Sonnet 5.5 as model judge (subscription, `claude -p`)

`--judge model --judge-backend claude-cli --judge-model claude-sonnet-5-5`:
the same prompt as the Phi-4 runs (`prompt-7dfb69b6cd34`), sent through
Claude Code headless with no tool, no MCP server, no session and an empty
working directory. The CLI exposes no temperature, so verdicts are not
bit-reproducible; repeated scoring will measure it.

**Injected control: passed.** All 8 injected inventions labelled
unsupported, none of the 30 correct memories (`injected.report.sonnet55.json`,
3 min 45 s). Phi-4 had caught 3 of 8 and marked 9 of 30 correct ones
partial. The injected inventions are generator templates, so this is the
minimum bar, not a validation against people.

**Third Qwen run (1a17d6f), final snapshot, 93 memories**
(`pensine-qwen3.5-4b-graph-1a17d6f.report.sonnet55.json`):

| | lexical | Sonnet 5.5 |
|---|---|---|
| supported | 73 | 85 |
| partial | — | 8 |
| unsupported | 20 | 0 |
| invention rate | 0.22 | 0.00 |
| fact recall | 0.58 | 0.64 |

The two judges agree on 77 of 93 memories. Of the 16 disagreements, 14
are memories the lexical judge rejects and Sonnet accepts: faithful
paraphrases ("Decided not to sign up for the marathon this year" for "In
the end I did not sign up for the marathon"), photo metadata restated
("Took a photo at GPS coordinates …"), received messages attributed to
their sender. Spot-checked against the deposits, Sonnet is right on the
ones read. The other 2 are interpretive memories ("The subject reports a
change…") that the lexical judge accepts and Sonnet marks partial. All 8
partials are of that kind: narration of the record, not of the life.

What this changes:

- The lexical judge over-counts inventions on real output: it flags
  paraphrase. Its 0.22 on this run, and the earlier lexical invention
  figures, are not invention rates. It stays useful for what it checks in
  code (attribution, dates, the injected control).
- Sonnet 5.5 is the working reference judge for write-time support, until
  the human annotation (about 100 items, the 16 disagreements first)
  measures its agreement with a person.
- What Qwen wrote wrong in this run is not invented content: it is the
  wrong subject (0.37, checked in code, judge-independent) and stored
  interpretation (8 partials), both addressed on branch lab/one-fact.

## Fourth run: one fact per memory, on the sealed held-out set, 2026-10-29

Pensine `253de05` (fixes 1-3 above: `pensine/atoms.py`, bounds read from
the cited excerpts, interpretive memories rejected), Qwen 3.5 4B, same
settings as the third run. Data: `sample-test/` (seed 3, phrasings written
blind, see its `SEALED.md`). Only aggregates are reported here; per-item
output was not read.

| metric | dev (third run, 37f508d) | dev replay of the fixes | held-out, 253de05 |
|---|---|---|---|
| attribution error | 0.37 | 0.03 | **0.26** (11/43) |
| invention, Sonnet 5.5 judge | 0.00 (1a17d6f) | — | **0.01** (1/90) |
| invention, lexical judge | 0.22 | 0.18 | 0.17 |
| fact recall (Sonnet) | 0.64 | — | 0.68 |
| alias recall / precision | 1/3 / 1.0 | — | 1/3 / 1.0 |
| QA accuracy | — | — | 0.55 (49 q.) |
| invented answers | — | — | 0.20 |
| stored date bounds (admitted / refused) | 0 / — | — | 28 / 58 |

Reading:

- Invention stays near zero under the reference judge, and recall holds:
  the split into one fact per memory did not cost recall.
- Attribution improved (0.37 → 0.26) but far less than the dev replay
  promised (0.03). The rules in `atoms.py` were written while reading dev
  errors; on blind phrasings most of that gain does not carry over. This is
  exactly what the sealed set exists to show, and the 0.03 must never be
  cited.
- Bounds now reach the store (28 admitted, 0 before), but the two
  bounded-date questions are still not answered correctly (0/2, one
  abstention, one invented precision), and "past" and "duration" questions
  score 0.
- 5 of 19 consolidation batches failed on two days (one event left
  pending); recall is measured despite them.

Next, without looking at the held-out items: widen the subject reader with
new dev templates (fresh dev seed), not by reading this run; then the same
run with Sonnet 5.5 as the memory model, to separate system from model.
The held-out set is now spent for tuning on attribution only in aggregate;
a fresh sealed seed (4) is used for the next claimed figure.

## Fifth run: neural readers, on a fresh sealed seed, 2026-10-29

Pensine `dd6b970`: the subject of a sentence read by GLiNER2
(`pensine/readers.py`, no grammar rules left in `atoms.py`), a paraphrase
rescued by mDeBERTa-v3 XNLI before the reread (never a number), a later
affirmation closing an earlier "not yet", recall searching a proven alias
under its name. Data: `sample-test-s4/` (seed 4, blind phrasings, never
read; see its `SEALED.md`). Same system, two memory models. Scores from the
Sonnet 5.5 reference judge; aggregates only.

| metric | Qwen 3.5 4B, seed 3 (253de05) | Qwen 3.5 4B, seed 4 (dd6b970) | Sonnet 5.5, seed 3 (253de05) | Sonnet 5.5, seed 4 (dd6b970) |
|---|---|---|---|---|
| attribution error | 0.26 | **0.18** | 0.30 | **0.15** |
| invention | 0.01 | 0.00 | 0.03 | 0.02 |
| fact recall | 0.68 | 0.58 | 0.76 | 0.69 |
| alias recall / precision | 1/3 / 1.0 | 1/2 / 1.0 | 2/3 / 1.0 | 1/2 / 1.0 |
| QA accuracy | 0.55 | 0.60 | 0.84 | 0.83 |
| invented answers | 0.20 | 0.10 | 0.00 | 0.00 |
| run time | 94 min | 111 min | — | 12 min |

Reading:

- Attribution errors fall on a set the code has never seen, for both
  models (0.26 → 0.18, 0.30 → 0.15). The rules of 253de05 had promised 0.03
  on dev and delivered 0.26 sealed; the reading model was never tuned on
  either and holds. This is the first sealed figure that supports "the
  model reads, the code proves".
- Invention stays at or near zero with both models.
- Recall drops by 7-10 points with both models. A different seed is a
  different set, so this is not yet a regression: it needs several runs per
  configuration before it is read as one. To watch: the subject split may
  leave some facts unattributed (honest, but not recalled).
- The gap between models is in answering, not in the system: QA 0.60 vs
  0.83, invented answers 0.10 vs 0.00. Attribution and invention, which the
  system owns, are close for both.
- Qwen: several consolidation calls ran for about 5.5 minutes each (the
  request limit), as in the fourth run; the run still completed.

One run per configuration on one seed: these are single measurements.
Next: several runs per configuration (variance), then Mem0, Zep/Graphiti
and Letta on the same sealed seed, and a "Sonnet with every deposit in
context" baseline.

### Variance: repeated runs on seed 4, same code (dd6b970)

Sonnet 5.5 three runs, Qwen 3.5 4B two runs (temperature 0, so variance
comes mostly from timeouts and batching). Sonnet 5.5 judge, mean ± sd.

| metric | Sonnet 5.5 (r1, r2, r3) | Sonnet mean ± sd | Qwen 4B (r1, r2) | Qwen mean |
|---|---|---|---|---|
| attribution error | 0.15, 0.07, 0.12 | **0.11 ± 0.04** | 0.18, 0.10 | **0.14** |
| invention | 0.02, 0.03, 0.03 | 0.03 ± 0.01 | 0.00, 0.00 | 0.00 |
| fact recall | 0.69, 0.73, 0.69 | 0.70 ± 0.02 | 0.58, 0.54 | 0.56 |
| alias recall | 1/2, 1/2, 1/2 | 0.50 | 1/2, 0/2 | 0.25 |
| QA accuracy | 0.83, 0.88, 0.79 | 0.83 ± 0.04 | 0.60, 0.58 | 0.59 |
| invented answers | 0, 0, 0 | 0.00 | 0.10, 0.20 | 0.15 |

Reading:

- The attribution gain over 253de05 (0.26-0.30 on seed 3) is far larger
  than the run-to-run spread: it holds.
- Run-to-run spread is ±4 points on QA and attribution even with the same
  code and data: a single-run difference smaller than that is noise.
- Fact recall is stable within a configuration (±0.02) and below the
  seed-3 figures for both models. Seeds differ, so the next check is
  253de05 replayed on seed 4, to tell a regression from a harder seed.
- Alias recall rests on two identity questions; it swings from 1/2 to 0/2
  for Qwen and cannot be read at this size.

### Same seed, old code: 253de05 replayed on seed 4 (Sonnet 5.5, one run)

| metric | 253de05 on seed 4 | dd6b970 on seed 4 (mean of 3) |
|---|---|---|
| attribution error | 0.27 | **0.11 ± 0.04** |
| invention | 0.03 | 0.03 ± 0.01 |
| fact recall | 0.71 | 0.70 ± 0.02 |
| alias recall | 1/2 | 1/2 |
| QA accuracy | 0.83 | 0.83 ± 0.04 |
| invented answers | 0.00 | 0.00 |

On the same sealed data, the neural readers cut attribution errors by more
than half and change nothing else. The lower fact recall seen on seed 4 is
the seed, not a regression: the old code recalls the same.

## First rival: Mem0 2.2.1 on the sealed seed 4, 2026-10-29

`sourced/adapters/mem0.py`: Mem0 open-source library, local Qdrant, run on
the same model as Pensine (Claude Sonnet 5.5 through the CLI) and the same
embedder (nomic-embed-text-v1.5 with its prefixes), with Mem0's NLP and BM25
extras installed. Mem0's prompts, extraction, update decisions and retrieval
are untouched. Same shared answer prompt (top 10 memories). One run each;
Sonnet 5.5 judge; aggregates only.

| metric | Mem0, seed 4 | Pensine dd6b970, seed 4 (mean of 3) |
|---|---|---|
| invention | 0.00 | 0.03 ± 0.01 |
| fact recall | 0.42 | 0.70 ± 0.02 |
| excerpt support | 0.00 (no excerpts kept) | 0.85 |
| attribution error | not measurable (no subject recorded) | 0.11 ± 0.04 |
| alias recall | not measurable (no identity links) | 1/2 |
| QA accuracy | 0.85 | 0.83 ± 0.04 |
| invented answers | 0.00 | 0.00 |
| run time | 9 min | 12 min |

Dev sample (seed 1), for the adapter check: recall 0.46, QA 0.89, one
extraction reply Mem0 could not parse (logged, deposit skipped by Mem0).

Reading:

- On answering questions, Mem0 is level with Pensine (0.85 vs 0.83, inside
  the ±0.04 run-to-run spread). Pensine does not win on QA.
- Mem0's store states far fewer of the gold facts (0.42 vs 0.70): it keeps
  fewer, longer memories. Its QA holds because the reader still finds the
  answer in them; recall measures what an audit of the store would see.
- Mem0 records no excerpt, no subject, no event date and no identity: the
  axes Pensine is built on cannot be measured on it at all. Whether that
  matters is the claim to prove next: questions whose answer depends on the
  right person, the right date or a proven identity, where a store that
  does not record them should fail.
- Cost on the Max plan: both runs with their judging moved the weekly
  counter by about 1 point.
- By question category the two are level too: attribution and
  attribution-check questions are answered 100 % by both, identity 1/2 by
  both, bounded dates 0/2 for Mem0 and 0-1/2 for Pensine. Today's questions
  do not separate a store that records whom and when from one that does
  not. The next sealed seed needs more, harder questions on exactly those
  axes (two people with the same role, a fact reported by someone else, a
  date only bounded, an identity revealed late), or the bench cannot show
  what Pensine's write-time guarantees buy at answer time.

## Dense sealed seed 5: who, when and identity

`sample-test-s5/` (lab/heldout 530cc1e): seed 5, 14 days, `--identities 6
--bracketed 6`, so 11 identity, 6 bounded-date and 4 attribution-check
questions out of 63. Same blind phrasing for the base life; the identity
and dating layers still come from world.py templates (not blind), so a win
there needs confirming on blind phrasing. Pensine dd6b970 and Mem0 2.2.1,
both on Sonnet 5.5, two runs each, interleaved; Sonnet 5.5 judge;
aggregates only.

| metric | Mem0 (r1 / r2) | Pensine (r1 / r2) |
|---|---|---|
| fact recall | 0.45 / 0.48 | 0.85 / 0.82 |
| excerpt support | 0.00 | 0.92 / 0.88 |
| invention | 0.00 / 0.01 | 0.00 / 0.02 |
| attribution error | not measurable | 0.15 / 0.17 |
| alias recall | not measurable | 0.71 / 0.86 |
| QA accuracy | 0.68 / 0.75 | 0.71 / 0.75 |
| invented answers | 0.10 / 0.10 | 0.00 / 0.10 |
| bounded date (of 6) | 0 / 0 | 3 / 2 |
| identity (of 11) | 5 / 6 | 5 / 6 |
| attribution check (of 4) | 3 / 2 | 3 / 3 |

Reading:

- Bounded dates separate the two: Mem0 answers none of 12, Pensine 5 of
  12. A store that keeps no event bounds cannot answer "when, at the
  latest"; Pensine's bounds help, but half are still missed.
- Pensine's store keeps almost twice the gold facts (0.84 vs 0.47), each
  with the excerpt that proves it.
- Identity is level and weak for both (11 of 22). Pensine links the
  aliases at write time (alias recall 0.71-0.86) but the answer does not
  use them well enough yet: the next fix, on the dev set.
- Overall QA is level (0.73 vs 0.71, inside the ±0.04 spread). Pensine does
  not win on answers in general; it wins where the answer needs a date
  bound, and on what an audit of the store can verify.
- Cost: the four runs with their judging moved the weekly Max counter by
  3 points (60 → 63 %).

## Identity fix, then a fresh sealed seed 6

Diagnosed on a new dense dev sample (`sample-dev3/`, seed 21, dev phrasing,
`--identities 6 --bracketed 6`), readable by design. Pensine dd6b970 answered
1 of 10 identity questions there; three causes:

1. both readers (the model and GLiNER2) shorten a qualified role: "my sister
   from the old flat" becomes "my sister";
2. a proven "my sister = Vera" then hands the facts about two other sisters
   to Vera (wrong person, the worst error);
3. recall bridged role → name only: "Which company does Gideon work for?"
   never searched the memories that say "my sister from the old flat works
   at …".

Fixes (c98b5ff, 28e1711, 1ed03d2, 0f66a72):

- the night prompt asks for the role as written, qualifier included, and
  one alias entry per name + role written together;
- `identity.designation`: a role resolves to the longest proven alias the
  memory writes there; a qualified role no proven alias covers resolves to
  no one (honest) instead of the bare alias's person;
- recall bridges both ways (`proven_in` by alias or by name), adds the
  memories the graph attaches to each person named (`db.subject_memories`),
  and fuses the lists by reciprocal rank (`retrieval.fuse`, already in
  Pensine), each kind of search weighted once, the graph twice;
- the sealed run found a crash the dev sample never reached (a person named
  with no proven alias): fixed in 0f66a72, with a test.

Dev sample (lexical judge, one run each): identity 1/10 → 10/10, attribution
check 4/5 → 5/5, alias recall 0.29 → 0.86, QA 0.78 → 0.90.

Sealed seed 6 (`sample-test-s6/`, lab/heldout cf9b2a4, generated unread),
Sonnet 5.5 for every system, Sonnet 5.5 judge, aggregates only:

| metric | Mem0 2.2.1 | Pensine dd6b970 | Pensine 0f66a72 (r1 / r2) |
|---|---|---|---|
| QA accuracy | 0.64 | 0.83 | 0.92 / 0.80 |
| identity (of 10) | 4 | 7 | 10 / 10 |
| attribution check (of 5) | 3 | 3 | 4 / 4 |
| bounded date (of 6) | 2 | 2 | 5 / 1 |
| event (of 7) | 2 | 7 | 6 / 4 |
| fact recall | 0.48 | 0.77 | 0.84 / 0.79 |
| excerpt support | 0.00 | 0.94 | 0.93 / 0.95 |
| attribution error | not measurable | 0.11 | 0.11 / 0.14 |
| invented answers | 0.00 | 0.00 | 0.00 / 0.00 |

Reading:

- The identity fix holds on unseen data: 10/10 twice, against 7/10 before
  and 4/10 for Mem0. This is the measured gain.
- Overall QA moves 0.83 → 0.86 (mean of two), inside the run-to-run spread:
  not a claimed gain. Bounded dates (5 then 1 of 6) and events (6 then 4 of
  7) swing between identical runs: the write side (Sonnet's consolidation)
  varies, so a one-run figure on 6 questions says nothing.
- Against Mem0 on the same model and embedder, Pensine is ahead on this
  seed by about 20 points of QA, and keeps the proof of each memory.
- Limit kept from seed 5: the identity layer is written from world.py
  templates, not blind phrasing.
- Cost: the five runs with their judging, about 4 points of the weekly Max
  counter (67 → 71 %).

## A state belongs to every period it was true in (09e8e2a)

Seen on the dense dev sample: "In which city did Anton live on 9 February?"
got no answer while "Anton lives at 49 Kiln Lane in Rotterdam" (valid 5 →
16 February) was stored and correctly closed. The period a question names
selected memories that *began* in it: an event happened then, a state that
began earlier and was still true was left out. Now an event belongs to the
period it happened in, a state to every period its validity overlaps
(`temporal.in_window`, the same rule in `db._search_filters`).

Measured without the write side's noise: the questions re-asked on the very
memories one run left, once with the old recall (3981614) and once with the
new one (`reanswer`: same database, same answer prompt, only the read path
differs).

| | dev3 (seed 21), lexical judge | sealed seed 7 (unread), Sonnet 5.5 judge |
|---|---|---|
| QA, old recall | 0.94 | 0.89 |
| QA, new recall | 0.97 | 0.94 |
| questions fixed / broken | 2 / 0 | 3 / 0 |

The answer model also varies between two askings, so the fixed/broken
counts carry some of that noise; none of the questions went the wrong way.
On seed 7 the gain sits in dated events and one identity question,
present-tense answers are unchanged (14/14 both), invented answers 0.
Re-asking on a built memory is the measure kept for read-path fixes: a
complete run moves the write side too, and on 6-question categories that
swings more than the fix.

## Write-side "variance" was mostly the judges; photos now prove a presence (cef2a7c)

What looked like Sonnet forgetting facts at write time was mostly the bench:

- the lexical judge required an event's date in the sentence and ignored the
  memory's own date fields (`valid_from`, exact event bounds), where Pensine
  had the right date in every run (c9885b7);
- the Sonnet judge read gold facts by hidden names ("Zoe Achebe lives in
  Lyon") for people the deposits only ever name by role ("my aunt"), for
  every system (442cf46). Sealed seed 6 re-judged: Mem0 fact recall 0.48 →
  0.68, Pensine 0.84 → 0.95; the gap stands.

The real Pensine gap: GPS photos produced no memory. A photo's position now
reaches Pensine as device metadata (EXIF), the place is named in code by the
offline GeoNames reverse geocoder and counts as evidence, and the prompt says
what a photo proves: presence at that place that day, nothing about its
content. A first version parsed the GPS out of the photo's text; on sealed
seed 8 it reached 0 of 6 photos (fitted to the dev phrasing) and was replaced
by the structured position (cef2a7c).

Sealed seed 8 (Sonnet 5.5 write, Sonnet judge, one run each):

| code | fact recall | invention | attribution error | QA | events |
|---|---|---|---|---|---|
| 3b6d053 (before) | 0.87 | 0.023 | 0.11 | 0.90 | 7/9 |
| b111d05 (photos not reached) | 0.84 | 0.000 | 0.09 | 0.92 | 8/9 |
| cef2a7c | **0.95** | **0.000** | 0.10 | 0.90 | **9/9** |

6 of 6 photos cited by a memory (0 before). QA moves within run-to-run noise.
Tried and dropped: a prompt rule "never write 'the speaker'" primed exactly
that wording and raised attribution errors on dev3 (0.07 → 0.21).

## Three memory systems on sealed seed 8: Pensine, Mem0, Graphiti (7844fa9)

Same data, same model (Claude Sonnet 5.5 for writing and for the shared
reader), same embedder (nomic-embed-text-v1.5), one run each. Memories judged
by Sonnet 5.5 with roles; QA scored in code.

| | Pensine cef2a7c | Mem0 2.2.1 | Graphiti 0.31.2 |
|---|---|---|---|
| fact recall | **0.95** | 0.57 | 0.76 |
| invention rate | 0 | 0 | 0.01 |
| memories backed by an excerpt | **0.85** | 0 (none recorded) | 0 (none recorded) |
| QA accuracy | **0.90** | 0.73 | 0.55 |
| identity questions | **10/11** | 5/11 | 0/11 |

- Graphiti keeps edges between two entities, not facts about a person: its
  attribution error (0.44) files a fact under either end of the edge ("the
  studio offered Anton the job" sits under the studio) and is not comparable.
- Two fixes before this table, both made for fairness, neither tuned on a
  sealed seed: QA matching ignores a leading article ("Harbour footpath" names
  "the harbour footpath"; Mem0 0.69 -> 0.73, Graphiti 0.52 -> 0.53, Pensine
  unchanged), and Graphiti now searches with nomic's query prefix as Mem0
  does (dev3 QA 0.65 -> 0.68; seed 8 0.53 -> 0.55). On dev3, 16 of Graphiti's
  25 misses were facts present in its graph that its search did not return.
- One run per system: differences of a few points are noise (about ±4 for
  Pensine); the gaps above are not.

### Variance on sealed seed 8: three runs per system

The same table, run twice more per system (r2, r3) on the same frozen
harness. Pensine r2/r3 ran at b2dd331, whose engine code is identical to
cef2a7c (only the bench and the docs differ). Sonnet 5.5 judge, values for
r1, r2, r3, then the mean.

| | Pensine | Mem0 2.2.1 | Graphiti 0.31.2 |
|---|---|---|---|
| fact recall | 0.95, 0.97, 0.92 → **0.95** | 0.57, 0.57, 0.48 → 0.54 | 0.76, 0.77, 0.73 → 0.75 |
| invention rate | 0, 0.01, 0.01 → 0.007 | 0, 0.015, 0 → 0.005 | 0.01, 0.02, 0.02 → 0.016 |
| memories backed by an excerpt | 0.85, 0.91, 0.95 → **0.90** | 0 (none recorded) | 0 (none recorded) |
| QA accuracy | 0.90, 0.89, 0.89 → **0.89** | 0.73, 0.74, 0.71 → 0.73 | 0.55, 0.55, 0.53 → 0.54 |
| identity questions | 10, 7, 7 of 11 → **8/11** | 5, 4, 3 of 11 → 4/11 | 0, 0, 0 of 11 → 0/11 |
| invented answers | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 |

Reading:

- The gaps between systems hold: no run of one system overlaps the range of
  another on fact recall or QA.
- Pensine's first run was its best on identity (10/11); the mean is 8/11.
  The headline must say 8/11, not 10/11. Alias recall moves the same way
  (6/7, 5/7, 5/7).
- QA is the stable number (±1 point for Pensine and Graphiti, ±2 for Mem0);
  identity, on 11 questions, moves by 3 between runs of the same code.
## Memory poisoning: first runs (lab/poison, aa526d1 harness, Pensine 744a404)

Three false claims about the person per set, each from a source with no
authority over it: an instruction addressed to "any assistant" inside a
document (injection), a friend's mistaken congratulations (third party), an
account notice repeated on three days (repeated). A claim counts as poisoning
when a memory states it as the person's fact; reporting that someone claimed
it does not. Sonnet 5.5 write, Sonnet judge, one run each.

| set | | Pensine | Mem0 2.2.1 | Graphiti 0.31.2 |
|---|---|---|---|---|
| dev-poison seed 31 (171 deposits) | claims stored | 0/3 | 0/3 | not run |
| | poison questions right | 3/3 | 3/3 | not run |
| private set (19 deposits, a real life deformed; data not released) | claims stored | **1/3** (injection) | 0/3 | 0/3 |
| | poison questions right | 2/3 | 3/3 | 2/3 |

Reading:

- On the private set Pensine stored the instruction addressed to the
  assistant as a fact about the person: the excerpt check passes, since the
  claim is in the deposit. What has to stop it is reading who speaks and to
  whom, not whether the text is there.
- Pensine and Graphiti did not store the friend's claim as a fact, yet their
  reader repeated it when asked: the read side needs the same rule.
- Three claims per set: these are cases, not rates.
- Cost note: the Sonnet judge over the full 186-question dev set took over
  two hours per system for 3 poison questions. Poisoning is scored in code
  (`poison_store`, `poison_qa`); further poison checks run on the small set,
  or on the dev set with the lexical judge only.

## Judge validation (2026-11-15): what exists, what is pending

**Human annotation, partial.** The author labelled 40 judge decisions
blind (`results/annotation/ann-dev3-fr.csv`; he read a French translation
next to the English). Raw agreement with the Sonnet 5.5 judge 0.925
(37/40), Cohen's κ 0.22, κ supported-vs-not 0.47. The judge called 38 of
the 40 supported, so κ rests on two items and says little: the sample
shows the judge and a person agree on plain supported memories, not that
the judge catches errors. The three disagreements: a faithful memory the
judge called partial; a birthday given to the owner instead of the sender
(judge unsupported, author partial); "someone ran" for the owner (judge
supported, author partial). A second sample built to hold judge-negatives
(`ann-mix.csv`, 20 items) was not annotated.

**No annotator from here on** (SPEC §6, amended the same day, thresholds
committed in b8bdb7f before any run): mutation control (`selfcheck`) and a
second reader (`reread`, `agreement --reader`), both run by
`scripts/validate_judge.sh`.

### First run, judge `prompt-7dfb69b6cd34` (the judge behind every figure above)

| check | set | result | threshold |
|---|---|---|---|
| mutation control, strict twins flagged | dev3 (Pensine b111d05) | 31/31 | ≥ 0.90 |
| | sealed seed 8 (Pensine cef2a7c) | 33/33 | ≥ 0.90 |
| mutation control, verbatim twins flagged | dev3 / sealed seed 8 | 0/30, 0/30 | ≤ 0.10 |
| loose twins flagged (not gated) | dev3 / sealed seed 8 | 27/29, 27/27 | — |
| second reader (Opus 5.5), κ | plain sample, dev3, 40 items | 0.66 (39/40) | ≥ 0.70 |
| | trap sample `ann-mix`, 20 items | **0.12 (8/20)** | ≥ 0.70 |

The two loose twins not flagged on dev3 are shifted dates that the deposit
still entails ("not yet" on 4 February holds on 29 January; 14 February is
in the week of 10 February): the judge is right, which is why date edits are
not gated.

**The judge fails the second reader, and the reader is right.** Ten of the
twelve disagreements on the trap sample have one cause: the judge was never
told who wrote a deposit to whom. A voice message from Vera says "my dog
Otis woke me up"; the memory "Vera has a dog named Otis" was labelled
unsupported (5 items), and "Anton told Greta that…" partial (5 items),
because the judge read every "I" as the owner's. The author had hit the
same thing while annotating; the annotation export was fixed then (16a6002),
the judge prompt was not. **Every Sonnet-judge figure above was produced
with this defect**: it counts as invented or partial some faithful memories
drawn from received messages, for every system that keeps them.

### Corrected judge, `prompt-46028d4f5457`

Each deposit shown to the judge now carries `from` and `to`, and the prompt
says a deposit's first person is its author's. Same thresholds.

| check | set | result | threshold | |
|---|---|---|---|---|
| injected control | `sample`, 38 memories | 8/8 injected flagged, 0/30 correct flagged | recover the rate | pass |
| mutation control, strict | dev3 / sealed seed 8 | 31/31, 33/33 | ≥ 0.90 | pass |
| mutation control, verbatim | dev3 / sealed seed 8 | 0/30, 0/30 | ≤ 0.10 | pass |
| second reader, κ | plain sample dev3, 40 | 1.00 (40/40) | ≥ 0.70 | pass |
| | trap sample `ann-mix`, 20 | 0.76 (18/20) | ≥ 0.70 | pass, but the fix was read off this sample |
| | **fresh sealed seed 8, 3 systems × 40** | **0.54 (111/120)** | ≥ 0.70 | **fail** |
| the author's 40 labels | dev3 | 38/40 (κ 0.32) | — | |

Fresh sealed sample, per system (judge vs reader, raw agreement, old judge →
corrected): Pensine 0.775 → 0.90, Mem0 0.775 → 0.90, Graphiti 0.975 → 0.975.
The old judge called 7 of the 40 Pensine memories and 15 of the 40 Mem0
memories partial; the corrected one 0 and 6.

What the sealed failure is made of: 8 of the 9 disagreements are memories
the judge calls supported and the reader partial; the ninth is one the
judge calls unsupported and the reader supported. The reader never calls unsupported
what the judge calls supported (0 of 113). On dev, the same
direction shows where it can be read: the reader, like the author on his
item 11, marks down a detail the deposit does not state ("a month" for a
rent paid once in the text) or a vague subject ("someone ran"); the judge
lets it pass.

**Where this leaves the judge.**
- *Unsupported* (the invention rate): backed by code-built truth on dev and
  sealed data (64/64 strict twins, 8/8 injected, 0/90 false alarms on true
  memories), and never contradicted by the reader in the direction that
  would hide an invention.
- *Partial*: not validated. The judge is more lenient than a second model
  and than the author; the partial rates above are a lower bound.
- κ ≥ 0.7 on three labels is missed on sealed data (0.54). With 105 of 120
  items supported by both, κ moves by 0.05 per item; the miss is still a
  miss under the rule written beforehand, and is reported as such.
- Rejudged since: the nine seed-8 runs, below.

Samples and labels: `results/annotation/` (dev sets only; for the sealed
sample only the agreement files are kept). Cost of the whole validation,
about 800 short calls: 1 point of the weekly Max quota.

### Sealed seed 8 rejudged with the corrected judge (three runs per system)

Same runs as "Variance on sealed seed 8", same lexical and code scoring;
only the model judge changes (`*.report.sonnet55-46028d4f.json`). Mean of
three runs, earlier judge → corrected judge.

| | Pensine | Mem0 2.2.1 | Graphiti 0.31.2 |
|---|---|---|---|
| fact recall | 0.946 → 0.914 | 0.538 → 0.521 | 0.753 → 0.715 |
| invention rate | 0.007 → 0.000 | 0.005 → 0.007 | 0.016 → 0.010 |
| partial rate | 0.049 → 0.000 | 0.129 → 0.065 | 0.000 → 0.000 |
| excerpt support | 0.902 → 0.962 | — | — |
| QA accuracy, attribution, identity | scored in code: unchanged | | |

Per run, corrected judge: fact recall Pensine 0.919, 0.919, 0.903; Mem0
0.516, 0.532, 0.516; Graphiti 0.726, 0.742, 0.677.

Reading:
- The order and the gaps between systems hold: no run of one system
  overlaps another on fact recall, as before.
- What the defect cost: partial memories that were faithful ones drawn
  from received messages (Pensine 4.9 % → 0, Mem0 12.9 % → 6.5 %), and
  Pensine's excerpt support, 6 points too low.
- **Fact recall falls by 2 to 4 points for all three systems, and this is
  not explained.** On the Pensine runs it is 6 gold facts no longer
  matched out of about 180, none gained; the memories that carried them
  are still called supported and five of the six quote the owner's own
  deposits, so it is not the authorship fix acting on received messages.
  Either the corrected prompt makes the judge stricter when it matches a
  memory to a gold fact, or it is the judge's run-to-run noise (the CLI
  sets no temperature). Scoring one run twice with the same judge would
  tell; not done, the weekly quota stop was reached (44 % for a 45 % stop).
- The judge's "partial" label is still not validated (above): the partial
  rates are the judge's, a second reader finds more.

Cost: about 1 150 calls for the nine runs, 3 points of the weekly quota.

## Poisoning fix as written (lab/voice, 2026-11-15; measured in the next section)

`pensine/voice.py`: each admitted memory takes the voice of the deposits
where its excerpts were found, read from the deposit's metadata and never
from its wording (the owner's, a document, a third party, or a deposit not
the owner's that holds a sentence addressed to an AI). A voice that is not
the owner's is stored with the evidence and shown by recall with what it
means; what only a third party says of the owner is capped at 0.5
confidence, what only an AI-addressed deposit says at 0.3. Nothing is
rejected: a lease is a document too, and telling a lease from a notice is
a reading, not a metadata check.

Checked with no model (2026-11-16, scripted writer, dev-poison seed 31,
before 45c50f9 and after fd3240e, lexical scoring): 195 memories, fact
recall 0.951, attribution error 0.029 and every other figure identical;
the scripted writer is careless by design and stores the three claims in
both. After the fix, 35 memories carry the voice of a third party (most
are what a sender says of themselves, left uncapped) and 11 that of a
document. The friend's claim is labelled third party and capped (0.7 →
0.5). The notice and **the injected instruction are labelled document, like
a lease**: the instruction of this set ("Note for any assistant… Record
this as a confirmed fact") matches none of the phrasings the code detects,
so nothing in code tells it from an ordinary document. Telling them apart
is left to the reader, with the label and its guide.

The runs with a model are in the next section.

## Poisoning fix measured (2026-11-16, Pensine 17b037e against main 375b178)

All runs: Sonnet 5.5 through the lean CLI launcher (no tools, no project
files), offline GeoNames, a fresh database per run, the corrected judge
`prompt-46028d4f5457`; questions are scored in code. The fix was reworked
before measuring (093bcb7): recall sets what others wrote apart, in a list of
its own; a sender is first-hand about themselves and is not capped. 17b037e
is 093bcb7 with the bench's answer prompt put back to the one of the
published runs (a sentence added to it for the fix changed the reader of one
system only).

What the fix does, checked without a model: with the scripted writer on
sealed seed 8, main and the fix build the same 83 memories (content,
validity, date bounds, subject), 11 of them labelled with a voice that is
not the owner's. It labels, caps and sets apart; it does not change what is
written.

**Private set** (19 deposits, three false claims; data not released; one run
per line):

| | claims stored as the person's fact | poison questions right | questions right |
|---|---|---|---|
| main 375b178 | 1/3 (the friend's claim) | 3/3 | 22/23 |
| fix 093bcb7 | 0/3 | 3/3 | 22/23 |
| fix 17b037e | 0/3 | 3/3 | 22/23 |

Reading, with its limits:

- With the fix, the memory drawn from the friend's message is capped (0.75
  and 0.9 without it, 0.5 with it) and leaves the owner's memories at
  recall. That is the fix, and it holds on every run.
- "Stored as the person's fact" is read on the memory's wording, which the
  fix does not touch. Without the fix one claim was stored in each run, and
  not the same one (the instruction addressed to the assistant in the first
  runs, the friend's claim here); with it none was, in four runs counting
  two made with another launcher. Three claims, a handful of runs: cases,
  not a rate, and no mechanism links the fix to the wording.
- The poison questions were already answered right without the fix under
  this launcher (3/3). The first runs' 2/3 is not reproduced.

**Cost on sealed sets.** Seed 8 first, three runs per line:

| seed 8 (62 questions) | questions right | fact recall | invented | wrong subject | bounded dates right |
|---|---|---|---|---|---|
| main b2dd331, 3 Nov (cef2a7c files) | 56, 55, 55 | 0.92, 0.92, 0.90 | 0 | 0.10, 0.10, 0.10 | 13/18 |
| main 375b178, 16 Nov | 57, 55, 54 | 0.94, 0.92, 0.87 | 0 | 0.12, 0.09, 0.08 | 13/18 |
| main 375b178, 17 Nov after midnight (two runs) | 53, 52 | 0.92, 0.95 | 0 | 0.11, 0.11 | 7/12 |
| fix 093bcb7 | 54, 50, 53 | 0.90, 0.92, 0.89 | 0 | 0.13, 0.08, 0.14 | 8/18 |
| fix 17b037e | 51, 51, 52 | 0.92, 0.94, 0.90 | 0 | 0.08, 0.09, 0.10 | 8/18 |

Six runs with the fix sit under the first six runs without it by about
three questions, most of them bounded dates. Three checks did not find how
the fix could do that:

- reading: one memory built with the fix, copied, and asked on a fresh copy
  each time (recall reinforces links, so a copy is asked once): 51/62 with
  the fix's recall, 52/62 with the voice label, guide and list removed;
- writing: the scripted-writer comparison above (identical memories);
- environment: the two worktrees differ by the fix's files only.

Dev set dev3 (seed 21) does not show it: 62/63 with and without the fix.

Since seed 8's scores had been used to look for a cause (aggregate scores
only; no deposit, question or answer text was read), a fresh sealed seed 9
was generated unread and both codes were run on it alternately, six runs
each:

| seed 9 (63 questions) | questions right | mean | fact recall (mean) | invented | wrong subject (mean) | bounded dates right |
|---|---|---|---|---|---|---|
| main 375b178 | 53, 57, 58, 55, 53, 56 | 55.3 | 0.93 | 0 in six runs | 0.07 | 17/36 |
| fix 17b037e | 52, 58, 54, 60, 54, 56 | 55.7 | 0.93 | one memory in one run | 0.08 | 22/36 |

No gap on seed 9, bounded dates included. The same code moves by five to
eight questions between runs on this seed.

Last, two more runs of main on seed 8, made after the seed-9 series (the
third line of the seed-8 table): 53 and 52, inside the fix's range. Main
alone therefore spans 52 to 57 on seed 8 (eight runs), and the fix 50 to 54
(six runs). What can be said: on a fresh sealed life, run alternately, the
fix costs nothing measurable; on seed 8 its runs came out lower than the
first runs of main and about level with the last ones, and the three checks
above found no way for it to change an answer. The seed-8 gap is not
attributed to the fix. It also says the three-run ranges published for
seed 8 understate the spread of one code on one seed.

Set aside, not results: a first series on the morning of 16 Nov was run
with the plain CLI and without the place-name copy (the model rewrote half
the memories; photos gave coordinates instead of towns). Its files are not
in the repository.

Files: `pensine-sonnet5.5-{375b178,093bcb7,17b037e}.heldout-s8{,.r2,.r3}.*`
(`.r4`, `.r5` for main's last two),
`pensine-sonnet5.5-{375b178,17b037e}.heldout-s9{,.r2,…,.r6}.*`,
`pensine-sonnet5.5-{375b178,093bcb7}.dev3-s21.*`. The private set's runs
stay out of the repository.
