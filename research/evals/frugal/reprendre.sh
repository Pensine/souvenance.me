#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../../.."
for M in mlx-community/Qwen3.5-4B-MLX-4bit mlx-community/Qwen3.5-9B-MLX-4bit; do
  echo "=== $M $(date +%H:%M:%S)"
  research/evals/frugal/.venv/bin/python research/evals/frugal/run.py "$HERE/donnees-privees"/dataset.json --model $M --out "$HERE/donnees-privees"/sorties --owner "${PENSINE_OWNER:-la personne}" --skip-nights 2026-10-23 2>&1 | grep -v "Fetching\|it/s\]" 
  # delete the model AND its real files (the cache keeps shared files elsewhere)
  python3 - "$HOME/.cache/huggingface/hub/models--$(echo $M | sed 's|/|--|')" <<'PY'
import os, shutil, sys
d = sys.argv[1]
for root, dirs, files in os.walk(d):
    for f in files + dirs:
        p = os.path.join(root, f)
        if os.path.islink(p) and os.path.exists(os.path.realpath(p)):
            os.remove(os.path.realpath(p))
shutil.rmtree(d, ignore_errors=True)
PY
  df -h / | tail -1 | awk '{print "free disk:", $4}'
done
echo "=== DONE $(date +%H:%M:%S)"
