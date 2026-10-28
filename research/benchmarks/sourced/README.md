# SOURCED

A benchmark of **memory integrity over a synthetic life**. It checks whether a
personal memory system writes only what the person's deposits support,
whether each memory can show the excerpt it comes from, and whether it stays
right as facts change over months.

- Protocol, metrics, prior work and their verification: [SPEC.md](SPEC.md)
- 2-week sample, actually generated: [sample/](sample/)
- What the numbers in `results/` mean (and do not mean): [results/README.md](results/README.md)

Status: **v0.1 draft**. The generator, harness, controls and Pensine adapter
work. No system has been measured yet.

## Layout

```
sourced/world.py       truth first: people, facts with validity, traps
sourced/deposits.py    notes, messages, voice transcripts, photos, documents + exact spans
sourced/tasks.py       questions derived from the truth (abstention included)
sourced/media.py       neutral photos with EXIF, minimal PDFs, voice via tts_worker.py
sourced/tts_worker.py  TTS worker: Chatterbox (default) or Piper, in its own environment
sourced/voices/refs/   public-domain LibriVox reference clips for Chatterbox (REFS.md)
scripts/               regen_voices.sh: re-voices the 2-week sample with Chatterbox
sourced/judge.py       lexical judge (harness checks) and open-weights model judge
sourced/score.py       invention, excerpt support, recall, curve, QA
sourced/runner.py      day-by-day driver, weekly snapshots, questions
sourced/adapters/      base contract, controls, pensine, external skeletons (not run)
tests/                 determinism, validity intervals, labelling, scorer controls
```

## Run

From this folder, with the repository's Python environment (Python 3.11+,
Pillow for photos; nothing else for the generator):

```bash
python -m pytest tests -q
python -m sourced generate --out sample --seed 1 --days 14 --facts 30 --changes 4 \
    --tts-python ~/.cache/sourced/chatterbox/venv/bin/python   # omit: voice deposits stay transcripts
python -m sourced run   --data sample --system oracle --out runs/oracle.json
python -m sourced score --data sample --run runs/oracle.json --out runs/oracle.report.json
```

The full release is the same command with the defaults (182 days, 300 facts,
40 changes).

**Voice (optional).** A separate environment keeps the generator light.
The default engine is **Chatterbox** (Resemble AI, MIT). It clones five
voices zero-shot from ~10 s public-domain LibriVox clips
([sourced/voices/refs/REFS.md](sourced/voices/refs/REFS.md)), and every file
it writes carries Resemble's imperceptible **Perth watermark**, which marks
the audio as synthetic (licences and checks in SPEC §9):

```bash
python3.11 -m venv ~/.cache/sourced/chatterbox/venv
~/.cache/sourced/chatterbox/venv/bin/pip install -r requirements-chatterbox.txt
HF_HOME=~/.cache/sourced/chatterbox/hf \
    ~/.cache/sourced/chatterbox/venv/bin/python sourced/tts_worker.py --download
```

`--download` fetches the pinned model revision (about 3.2 GB) into that
`HF_HOME` and checks every file against SHA-256; `--check` repeats the checks
without loading the model. Keep `HF_HOME` set (and `HF_HUB_OFFLINE=1`) when
generating. Order of magnitude: the environment takes about 1.3 GB on disk
and the model about 3 GB. The weights alone are about 3.2 GB in float32, so
expect at least that much RAM in use; the regeneration script reports the
real peak. CPU is
the default device (`--tts-device mps` is faster on Apple silicon but not
promised reproducible); `SOURCED_TTS_THREADS` sets the CPU threads (4).

To re-voice the 2-week sample in one step (seed 1, progress per clip, peak
RAM and time reported; it refuses to start below 40 % free memory and stops
below 15 %):

```bash
research/benchmarks/sourced/scripts/regen_voices.sh   # --dry-run to see the command
```

The voice files committed in `sample/` were made this way on 2026-10-28
(7 clips in 201 s on CPU, peak RAM 4.4 GB, Apple M-series, 16 GB), and
listened to before commit.

**Piper** stays available as a fallback (`--tts-engine piper`): CPU only,
five English voices trained on public-domain speech, much lighter.

```bash
python3.11 -m venv ~/.cache/sourced/piper-venv
~/.cache/sourced/piper-venv/bin/pip install piper-tts==1.8.0 onnx soundfile
~/.cache/sourced/piper-venv/bin/python sourced/tts_worker.py --engine piper --download
```

The Piper voices land in `~/.cache/sourced/piper-voices` (override with
`SOURCED_PIPER_VOICES`). Keep venv paths short: espeak-ng ignores a data path
longer than about 160 characters and fails with `phontab: No such file or
directory`. `ffmpeg` encodes the `.m4a` files.

**Pensine adapter.** It uses a throwaway database:

```bash
docker compose -p sourced-eval up -d
python -m sourced run --data sample --system pensine --pensine-mode scripted --out runs/pensine.json
# real measurement: PENSINE_LLM_BACKEND=openai|ollama|api|claude-cli ... --pensine-mode llm
docker compose -p sourced-eval down -v
```

**Model judge.** It runs on any OpenAI-compatible server hosting an
open-weights model:

```bash
python -m sourced score --data sample --run runs/x.json --judge model \
    --judge-url http://127.0.0.1:8080/v1 --judge-model <name>
```

**Human agreement.** Before a judge is used for publication:

```bash
python -m sourced annotate --data sample --run runs/x.json --report runs/x.report.json --n 100 --out ann.csv
# fill the human_support column (labels of the judge are in ann.judge.json, kept apart)
python -m sourced agreement --file ann.csv     # kappa >= 0.7 required
```

## License

Data (truth, deposits, questions, media): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (see SPEC §9).
Code: Apache-2.0, like the rest of the repository.
