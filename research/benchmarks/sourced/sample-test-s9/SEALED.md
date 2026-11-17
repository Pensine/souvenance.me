# SEALED: held-out set

This folder is a **held-out (test) set**, generated unread on 2026-11-16 with
the recipe of seed 8 (dense on identity and bounded dates) and a new seed:

```bash
python -m sourced generate --out sample-test-s9 --seed 9 --days 14 --facts 30 \
    --changes 4 --text-only --phrasing test \
    --identities 6 --bracketed 6
```

77 deposits, 63 questions.

Rules (the same as for every sealed set, see `../sample-test-s8/SEALED.md`):

1. Nobody tunes a system while reading this set. Do not open
   `deposits.json`, `evidence.json`, `questions.jsonl` or `truth.json`
   here, nor `sourced/phrasing.py`.
2. Only aggregate scores are reported from runs on this set.
3. Once its per-item errors have been read for tuning, it is a dev set:
   say so here and generate a fresh one.

Why a new seed: on 2026-11-16 the scores of seed 8 were used to find why the
poisoning fix (lab/voice) lost answers, and reading variants were compared
on it (aggregate scores only; no deposit, question or answer text was read).
A fix chosen with seed 8's scores is confirmed here, not there.

Status: sealed since generation (2026-11-16). Not read for tuning.
