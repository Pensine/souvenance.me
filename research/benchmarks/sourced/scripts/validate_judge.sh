#!/bin/sh
# Judge validation with no annotator (SPEC §6): mutation control, then a
# second reader on the annotation samples. Needs `claude` signed in.
#   SEALED=/path/to/sample-test-s8 scripts/validate_judge.sh
set -eu
cd "$(dirname "$0")/.."
JUDGE=${JUDGE_MODEL:-claude-sonnet-5-5}
READER=${READER_MODEL:-claude-opus-5-5}
W=${WORKERS:-4}
R=results
J="--judge model --judge-backend claude-cli --judge-model $JUDGE --workers $W"

python3 -m sourced selfcheck --data sample-dev3 \
  --run $R/pensine-sonnet5.5-b111d05.dev3-s21.run.json \
  --report $R/pensine-sonnet5.5-b111d05.dev3-s21.report.sonnet55.json \
  $J --out $R/selfcheck.pensine-b111d05.dev3-s21.json

if [ -d "${SEALED:-}" ]; then  # sealed set: only the aggregates are read
  python3 -m sourced selfcheck --data "$SEALED" \
    --run $R/pensine-sonnet5.5-cef2a7c.heldout-s8.run.json \
    --report $R/pensine-sonnet5.5-cef2a7c.heldout-s8.report.sonnet55.json \
    $J --out $R/selfcheck.pensine-cef2a7c.heldout-s8.json
fi

for f in ann-mix ann-dev3-b111d05; do
  python3 -m sourced reread --file $R/annotation/$f.csv --model "$READER" --workers $W
  python3 -m sourced agreement --file $R/annotation/$f.csv \
    --reader $R/annotation/$f.reader.json --out $R/annotation/$f.agreement.json
done
