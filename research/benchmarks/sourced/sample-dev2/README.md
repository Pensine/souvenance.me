# sample-dev2: second development set

Generated with:

```bash
python -m sourced generate --out sample-dev2 --seed 6 --days 14 --facts 30 \
                           --changes 4 --text-only --phrasing dev2
```

Seed 6, two weeks, `dev2` templates (`sourced/phrasing_dev2.py`): the deposit
skeleton is the one `--phrasing dev` would give for this seed (same ids,
times, authors, facts, traps, span roles), the words are new. 54 deposits
(4 incoming messages), 47 questions, among them 4 `identity` and 2
`bounded_date`.

Text only (Track T): no audio, image or PDF files were rendered, so the
`file` paths in `deposits.json` point at nothing.

**Development set: reading its errors is allowed; never used for a claimed
figure.** Claimed figures come from the sealed held-out set
([../sample-test/](../sample-test/)) only.
