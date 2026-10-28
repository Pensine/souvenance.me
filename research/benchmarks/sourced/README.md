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
    --tts-python /path/to/tts-venv/bin/python   # omit: voice deposits stay transcripts
python -m sourced run   --data sample --system oracle --out runs/oracle.json
python -m sourced score --data sample --run runs/oracle.json --out runs/oracle.report.json
```

The full release is the same command with the defaults (182 days, 300 facts,
40 changes).

**Voice (optional).** A separate environment keeps the generator light:

```bash
python -m venv tts-venv
tts-venv/bin/pip install mlx-audio soundfile "misaki[en]"
```

On macOS the `espeakng_loader` wheel can ship without its data files
(`phontab: No such file or directory`). Link the system espeak-ng data into
it:

```bash
for f in /opt/homebrew/share/espeak-ng-data/*; do ln -sf "$f" tts-venv/lib/python3.11/site-packages/espeakng_loader/; done
```

`mlx-audio` needs Apple silicon. On other machines, swap `tts_worker.py`
for any Kokoro runtime with the same job format.

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
