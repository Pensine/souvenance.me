# Measuring integrity

"The personal memory that makes nothing up, and proves it": three
indicators, computed in code, produced by one command.

```bash
python3 scripts/integrity_report.py --out rapport/                  # A and B, configured database
python3 scripts/integrity_report.py --no-db --nights nuits.json --out rapport/   # C
```

Outputs: `rapport.md` and `rapport.json`. Counts only, no content: the
report can be published. Every proportion carries its sample size and a
95% Wilson interval ("0 out of 5" still allows up to 43%).

## A. Invention rate at write time

**Candidates rejected or flagged by the evidence cascade / candidates
proposed by consolidation.** Read from the audit log (one summary per
night). Rejected = excerpt missing or not found (tier 1), or a review that
finds it "not supported" (tier 3). Flagged = a number or proper noun missing
from the deposit (tier 2). Summaries written before the instrumentation only
give a lower bound; the report says so.

This measures what **the filter catches**, not what it lets through:
that is B's job.

## B. Support rate

**Kept memories whose cited excerpts support their content.** A
deterministic check with three conditions:

- S1 every cited excerpt is still in the deposit (catches a source that was
  deleted or re-transcribed);
- S2 every number and proper noun in the memory appears **in the cited
  excerpts** (stricter than tier 2, which searches the whole deposit);
- S3 at least a third of the memory's content words appear in the
  excerpts (a paraphrase passes, an addition does not).

An optional review by a model (`--modele`), off by default.

## C. Recall / invention frontier

The same night replayed under three filter severities (`PENSINE_EVIDENCE_SEVERITY`):
`desactive` (annotate without filtering), `defaut`, `strict` (a doubtful memory
that the review does not confirm is rejected). With candidates labelled
by a judge (`fidele` faithful, `approximative` approximate, `inventee` invented — see the frugal bench),
we plot the recall of faithful candidates against the share of inventions kept. Without
labels, invention is approximated by lack of support (B).

## Modality (S4, and the cascade behind a setting)

The cited evidence checks that the words exist; it does not see "maybe
I'll learn to sail" cited under "learned to sail".
`pensine/modality.py` spots in the excerpt, in French and in English, the
conditional, the future, hypotheses, wishes, negation, questions and
hearsay, when they bear on what the memory states as fact (a content word
of the memory within the six words that follow the marker, same
clause; the whole sentence for "si" / "if"). A memory that keeps the
mood ("is considering", "according to Léa", "might") is not at fault.

- S4 is part of the support rate.
- In the cascade: `PENSINE_EVIDENCE_MODALITY=signaler` sends these memories
  to review (tier 3); under `strict`, without review, they are rejected.
  Default `off`: the previous behaviour.
- The model review is explicitly asked about the mood.

## Re-running the frugal bench with the current instructions (prepared, not run)

The October outputs predate cited evidence: without an excerpt, the
full cascade rejects all of them. To be re-run during a quiet window, on an
Apple Silicon Mac (local MLX models, free), then judged:

```bash
cd research/evals/frugal && bash reprendre.sh           # Qwen 3.5 4B and 9B, sorties/
PENSINE_LLM_BACKEND=claude-cli research/evals/frugal/.venv/bin/python \
  research/evals/frugal/judge.py donnees-privees/dataset.json donnees-privees/sorties \
  --out donnees-privees/verdicts.json
for M in donnees-privees/sorties/*.json; do
  python3 scripts/integrity_report.py --no-db --dataset donnees-privees/dataset.json \
    --run "$M" --verdicts donnees-privees/verdicts.json --owner "$PENSINE_OWNER_NAME" \
    --palier2 --out "donnees-privees/integrite/$(basename "$M" .json)"
done
```

Estimated cost (not measured): local generation, no quota; the judge makes one
call per night and per model, plus the reference, i.e. about 25 calls of
4 to 6k tokens, on the order of a few percent of a subscription's 5-hour
window. Outputs stay in `donnees-privees/` (outside the repository); only the
counts are published.

## Known limits

- Modality is lexical: it misses irony, context, markers that are not in
  its lists, and a marker close to a shared word can raise a
  false alarm ("Fully recovered, no more rest" under "healed by rest").
- Tier 2 does not see over-interpretation ("Tension between…"): only
  missing numbers and proper nouns. That is the review's job.
  Since it was fixed, an invented name placed at the start of a sentence also
  slips past it (the price of ending false alarms on sentence-initial words).
- Nights are few and correlated (one model, one life):
  the Wilson interval assumes independent candidates, so it is
  optimistic. The per-night range is given alongside.
- On a real database, the frontier is replayed from the log of raw
  candidates (`night_candidates`, migration 014): each night keeps there what the
  model proposed before the cascade, sealed under its deposits' key when
  `PENSINE_SHRED=1`, purged with them when forgotten, and kept at most one year
  (`PENSINE_CANDIDATES_RETENTION_DAYS`, 0 to keep nothing). Without
  judge labels, invention is approximated there by lack of support.
