#!/usr/bin/env bash
# Regenerate the voice files of the 2-week sample (seed 1) with Chatterbox.
#
#   research/benchmarks/sourced/scripts/regen_voices.sh [--dry-run]
#
# What it does:
#   1. refuses to start if less than 40 % of memory is free;
#   2. checks the reference clips, the Perth watermarker and the pinned model
#      files (SHA-256), without loading the model;
#   3. regenerates the whole sample into a temporary folder (text, photos and
#      PDFs are deterministic; only the 7 voice clips are new), printing
#      "clip i/7" as it goes; a watchdog samples RAM every 2 s and stops the
#      run if free memory falls below 15 %;
#   4. checks that every non-audio file is byte-identical to sample/, then
#      copies the .m4a files and manifest.json into sample/;
#   5. prints wall time and peak RAM. It commits nothing.
#
# Environment overrides: TTS_PYTHON, PYTHON (generator, needs Pillow), DEVICE
# (cpu|mps, default cpu), SOURCED_TTS_THREADS (default 4), SOURCED_CHATTERBOX_HOME
# (default ~/.cache/sourced/chatterbox), MIN_FREE (40), ABORT_FREE (15).
# SOURCED_MEM_FREE_PCT replaces the memory reading (tests only).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)              # research/benchmarks/sourced
BASE=${SOURCED_CHATTERBOX_HOME:-$HOME/.cache/sourced/chatterbox}
TTS_PY=${TTS_PYTHON:-$BASE/venv/bin/python}
DEVICE=${DEVICE:-cpu}
MIN_FREE=${MIN_FREE:-40}
ABORT_FREE=${ABORT_FREE:-15}
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

if [ -z "${PYTHON:-}" ]; then
  root=$(git -C "$HERE" rev-parse --show-toplevel)
  common=$(cd "$(git -C "$HERE" rev-parse --git-common-dir)/.." && pwd)  # main checkout
  for p in "$root/.venv/bin/python" "$common/.venv/bin/python"; do
    if [ -x "$p" ]; then PYTHON=$p; break; fi
  done
fi
PYTHON=${PYTHON:-python3}

mem_free_pct() {
  if [ -n "${SOURCED_MEM_FREE_PCT:-}" ]; then echo "$SOURCED_MEM_FREE_PCT"; return; fi
  if command -v memory_pressure >/dev/null 2>&1; then
    memory_pressure | tail -1 | grep -Eo '[0-9]+' | tail -1
  elif [ -r /proc/meminfo ]; then
    awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{printf "%d\n", a*100/t}' /proc/meminfo
  else
    echo 0
  fi
}

free=$(mem_free_pct)
if [ "$free" -lt "$MIN_FREE" ]; then
  echo "refusing to start: ${free}% memory free (< ${MIN_FREE}%). Close other work and retry." >&2
  exit 3
fi
echo "memory free: ${free}%"

GEN=("$PYTHON" -m sourced generate --seed 1 --days 14 --facts 30 --changes 4
     --tts-python "$TTS_PY" --tts-engine chatterbox --tts-device "$DEVICE")
if [ "$DRY_RUN" = 1 ]; then
  echo "dry run, would run in $HERE:"
  echo "  HF_HOME=$BASE/hf HF_HUB_OFFLINE=1 ${GEN[*]} --out <tmp>/sample"
  echo "then compare non-audio files with sample/ and copy the .m4a files and manifest.json"
  exit 0
fi

command -v ffmpeg >/dev/null || { echo "ffmpeg not found" >&2; exit 2; }
[ -x "$TTS_PY" ] || { echo "$TTS_PY not found (see README, Voice)" >&2; exit 2; }
export HF_HOME="$BASE/hf" HF_HUB_OFFLINE=1
"$TTS_PY" -I "$HERE/sourced/tts_worker.py" --check

TMP=$(mktemp -d "${TMPDIR:-/tmp}/sourced-voices.XXXXXX")
LOG="$TMP/run.log"
echo "regenerating into $TMP/sample (log: $LOG)"
cd "$HERE"
set -m                                   # own process group, so the watchdog can stop it all
start=$SECONDS
"${GEN[@]}" --out "$TMP/sample" >"$LOG" 2>&1 &
pid=$!
peak_kb=0
aborted=0
shown=0
progress() {  # print the worker's progress lines that appeared since last call
  local n
  n=$(wc -l <"$LOG" | tr -d ' ')
  if [ "$n" -gt "$shown" ]; then
    awk -v a="$shown" -v b="$n" 'NR>a && NR<=b' "$LOG" | grep -E '^(clip |model loaded|ok |done )' || true
    shown=$n
  fi
}
while kill -0 "$pid" 2>/dev/null; do
  rss=$(ps -A -o pgid=,rss= | awk -v g="$pid" '$1==g {s+=$2} END{print s+0}')
  [ "$rss" -gt "$peak_kb" ] && peak_kb=$rss
  f=$(mem_free_pct)
  if [ "$f" -lt "$ABORT_FREE" ]; then
    echo "memory free fell to ${f}% (< ${ABORT_FREE}%): stopping the run" >&2
    kill -TERM -- "-$pid" 2>/dev/null || true
    aborted=1
    break
  fi
  progress
  sleep 2
done
status=0
wait "$pid" || status=$?
progress
elapsed=$((SECONDS - start))
peak_mb=$((peak_kb / 1024))
if [ "$aborted" = 1 ] || [ "$status" != 0 ]; then
  echo "run failed (exit $status) after ${elapsed}s, peak RAM ${peak_mb} MB; sample/ untouched." >&2
  tail -20 "$LOG" >&2
  exit 1
fi

# Everything except audio and the manifest must be identical to the committed sample.
cd "$TMP/sample"
diffs=0
while IFS= read -r f; do
  cmp -s "$f" "$HERE/sample/$f" || { echo "differs: $f" >&2; diffs=$((diffs + 1)); }
done < <(find . -type f ! -name '*.m4a' ! -name manifest.json | sed 's|^\./||' | sort)
if [ "$diffs" != 0 ]; then
  echo "$diffs non-audio file(s) differ from sample/: nothing copied, see $TMP/sample" >&2
  exit 4
fi
n=0
for f in deposits/*.m4a; do cp "$f" "$HERE/sample/$f"; n=$((n + 1)); done
cp manifest.json "$HERE/sample/manifest.json"
worker_peak=$(grep -Eo 'peak RSS [0-9]+ MB' "$LOG" | tail -1 || true)
echo "done: $n voice clips in ${elapsed}s; peak RAM ${peak_mb} MB (process group, sampled every 2 s); worker ${worker_peak:-peak RSS n/a}"
echo "sample/ updated (not committed). Listen to sample/deposits/*.m4a, then commit."
rm -rf "$TMP"
