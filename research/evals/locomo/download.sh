#!/usr/bin/env bash
# Downloads the LoCoMo-10 dataset (Maharana et al., 2024 — snap-research/locomo).
# Not committed: the source repository declares no licence, so we do not redistribute it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HERE/data"
URL="https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
OUT="$HERE/data/locomo10.json"
[ -s "$OUT" ] && { echo "already present: $OUT"; exit 0; }
curl -fsSL "$URL" -o "$OUT"
python3 -c "import json,sys; d=json.load(open('$OUT')); assert len(d)==10, 'expected 10 conversations'; print('OK:', len(d), 'conversations,', sum(len(s['qa']) for s in d), 'questions')"
