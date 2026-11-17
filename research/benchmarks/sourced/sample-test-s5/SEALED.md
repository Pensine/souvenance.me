# SEALED: held-out set

This folder is a **held-out (test) set**. It was generated with
`--phrasing test`: the same generator, a different seed, and deposit
templates written blind, without knowledge of any system's parsing rules
(`sourced/phrasing.py`). Its purpose is to measure, on sentences it has
never seen, a memory system tuned on the dev sample (`../sample/`).

```bash
python -m sourced generate --out sample-test-s5 --seed 5 --days 14 --facts 30 \
    --changes 4 --text-only --phrasing test \
    --identities 6 --bracketed 6
```

Rules:

1. **Nobody tunes a system while reading this set.** Do not open
   `deposits.json`, `evidence.json`, `questions.jsonl` or `truth.json`
   here, nor `sourced/phrasing.py` (it holds the test templates), while
   working on a system's rules, prompts or thresholds.
2. **Only aggregate scores are reported** from runs on this set (headline
   metrics, per-category rates). No per-item errors, no deposit or question
   text, in reports, issues or commit messages.
3. **Once its per-item errors have been read for tuning, it is a dev set.**
   Say so here, stop calling it held out, and generate a fresh one with a
   new seed (`--seed 4`, then 5, …) under `--phrasing test`. If the test
   templates themselves were read for tuning, a new blind set of templates
   is needed, not only a new seed.

What is held out is the **wording**. The truth, the deposit skeleton
(ids, times, authors, which facts and traps each deposit carries) and the
questions are those `--phrasing dev` gives for the same seed; only the
text differs. Voice deposits are transcripts only (`--text-only`): no audio
was rendered.

Status: sealed since generation (2026-10-29). Not yet read for tuning.

Seed 5 is **dense on identity and dating**: six people in the identity
layer (eleven identity questions) and six facts dated only by a "not yet"
then an "already" deposit (six bounded-date questions), against one or two
of each in seeds 3 and 4, whose questions did not separate a store that
records whom and when from one that does not (Mem0 vs Pensine, 2026-10-29).
The identity people the base life lacks are added by the layer itself,
known only through its deposits. 77 deposits, 63 questions.
