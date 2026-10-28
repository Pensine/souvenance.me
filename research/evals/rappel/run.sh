#!/usr/bin/env bash
# Banc de rappel complet, en une commande : base jetable, 10 conversations,
# 6 conditions, mesures RAM/latence des rerankers, tableau final.
#   research/evals/rappel/run.sh            # tout (~2 h 30, dont ~2 h 15 de bge-m3 sur CPU)
#   research/evals/rappel/run.sh --rapide   # sans les rerankers (~4 min)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PY="${PYTHON:-$REPO/.venv/bin/python}"

[ -f "$HERE/../locomo/data/locomo10.json" ] || (cd "$HERE/../locomo" && ./download.sh)
(cd "$HERE/../locomo" && docker compose -p locomo-eval up -d)
sleep 3

"$PY" "$HERE/bench.py" --conditions avant,plein-texte,hybride,hybride+temps
if [ "${1:-}" != "--rapide" ]; then
  for m in cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 BAAI/bge-reranker-v2-m3; do
    "$PY" "$HERE/mesure_reranker.py" "$m" | tail -1 >> "$HERE/results/reranker_ram_latence.jsonl"
  done
  "$PY" "$HERE/bench.py" --conditions rerank-minilm,rerank-bge-m3 --tag=-rerank
fi
"$PY" "$HERE/rapport.py"
