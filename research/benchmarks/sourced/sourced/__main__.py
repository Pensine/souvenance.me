"""SOURCED command line.

  python -m sourced generate --out sample --seed 3 --days 14 --facts 30 --changes 4 \
                             [--tts-python /path/to/tts-venv/bin/python]
  python -m sourced run   --data sample --system oracle|injected|verbatim|pensine --out run.json
  python -m sourced score --data sample --run run.json [--judge lexical|model --judge-url URL
                                                        --judge-model NAME] --out report.json
  python -m sourced annotate  --data sample --report report.json --n 100 --out sample.csv
  python -m sourced label     --file sample.csv      # blind, resumable
  python -m sourced agreement --file sample.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

from . import __version__
from .deposits import build_deposits, deposit_dicts
from .tasks import derive_questions, evidence_index, question_dicts
from .world import count_changes, generate_world


def cmd_generate(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w = generate_world(seed=a.seed, start=a.start, days=a.days, n_facts=a.facts,
                       n_changes=a.changes)
    deps = build_deposits(w)
    qs = derive_questions(w, deps)
    hashes = {}
    if not a.text_only:
        from .media import render_all
        hashes = render_all(deps, out, a.seed, a.tts_python)
    (out / "truth.json").write_text(json.dumps(w.to_dict(), indent=1, ensure_ascii=False),
                                    encoding="utf-8")
    (out / "deposits.json").write_text(json.dumps(deposit_dicts(deps), indent=1,
                                                  ensure_ascii=False), encoding="utf-8")
    (out / "questions.jsonl").write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in question_dicts(qs)),
        encoding="utf-8")
    (out / "evidence.json").write_text(json.dumps(evidence_index(deps), indent=1,
                                                  ensure_ascii=False), encoding="utf-8")
    kinds: dict[str, int] = {}
    for d in deps:
        kinds[d.kind] = kinds.get(d.kind, 0) + 1
    cats: dict[str, int] = {}
    for q in qs:
        cats[q.category] = cats.get(q.category, 0) + 1
    manifest = {
        "benchmark": "SOURCED", "generator_version": __version__,
        "params": {"seed": a.seed, "start": a.start, "days": a.days, "facts": a.facts,
                   "changes": a.changes},
        "counts": {"facts": len(w.facts), "changes": count_changes(w.facts, w.start),
                   "people": len(w.people), "traps": len(w.traps), "deposits": len(deps),
                   "questions": len(qs)},
        "deposits_by_kind": kinds, "questions_by_category": cats,
        "audio": "kokoro-82m (mlx-community/Kokoro-82M-bf16)" if a.tts_python and not a.text_only
                 else "not rendered",
        "license": "CC-BY-4.0",
        "truth_sha256": hashlib.sha256((out / "truth.json").read_bytes()).hexdigest(),
        "files_sha256": hashes,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest["counts"]), kinds, cats)


def make_system(name: str, data: Path, a):
    from .runner import load
    truth, deps, qs = load(data)
    if name == "oracle":
        from .adapters.controls import OracleSystem
        return OracleSystem(truth, deps, qs)
    if name == "injected":
        from .adapters.controls import InjectedSystem
        return InjectedSystem(truth, deps, qs, rate=a.inject_rate)
    if name == "verbatim":
        from .adapters.controls import VerbatimSystem
        return VerbatimSystem()
    if name == "pensine":
        from .adapters.pensine import PensineSystem
        return PensineSystem(owner=next(p["name"] for p in truth["people"]
                                        if p["id"] == truth["owner"]),
                             mode=a.pensine_mode, truth=truth, deposits=deps)
    from .adapters import external
    cls = external.REGISTRY.get(name)
    if not cls:
        sys.exit(f"unknown system {name}")
    return cls()


def cmd_run(a) -> None:
    from .runner import run
    data = Path(a.data)
    sysm = make_system(a.system, data, a)
    res = run(sysm, data, track=a.track, qa=not a.no_qa, limit_questions=a.limit)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{a.system}: {len(res['snapshots'])} snapshots, {len(res['answers'])} answers, "
          f"{res['seconds']} s -> {a.out}")


def make_judge(a, truth, deps):
    from .judge import LexicalJudge, ModelJudge
    if a.judge == "model":
        return ModelJudge(truth, deps, a.judge_url, a.judge_model)
    return LexicalJudge(truth, deps)


def cmd_score(a) -> None:
    from .runner import load
    from .score import score_run
    data = Path(a.data)
    truth, deps, qs = load(data)
    run = json.loads(Path(a.run).read_text(encoding="utf-8"))
    rep = score_run(truth, deps, qs, run, make_judge(a, truth, deps))
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"system": rep["system"], "judge": rep["judge"], **rep["headline"]},
                     indent=1))
    if rep["qa"] and "by_category" in rep["qa"]:
        print(json.dumps(rep["qa"]["by_category"]))


def cmd_annotate(a) -> None:
    """Stratified sample of judge decisions for human annotation (SPEC §6)."""
    rep = json.loads(Path(a.report).read_text(encoding="utf-8"))
    run = json.loads(Path(a.run).read_text(encoding="utf-8"))
    from .runner import load
    _, deps, _ = load(Path(a.data))
    texts = {d["id"]: d["text"] for d in deps}
    snap, labs = run["snapshots"][-1], rep["snapshots"][-1]["labels"]
    rows = [(m, lab) for m, lab in zip(snap["memories"], labs)]
    r = random.Random(a.seed)
    strata: dict[str, list] = {}
    for m, lab in rows:
        strata.setdefault(lab["support"], []).append((m, lab))
    picked = []
    for k in sorted(strata):  # proportional, at least 20 per non-empty stratum when possible
        share = max(min(20, len(strata[k])), round(a.n * len(strata[k]) / len(rows)))
        picked += r.sample(strata[k], min(share, len(strata[k])))
    r.shuffle(picked)
    key = {}
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["item", "memory", "cited_excerpts", "cited_deposits_text",
                     "human_support (supported|partial|unsupported)", "human_note"])
        for i, (m, lab) in enumerate(picked[:a.n], 1):
            cits = m.get("citations") or []
            wr.writerow([i, m["content"], " | ".join(c.get("excerpt", "") for c in cits),
                         " || ".join(texts.get(c["deposit_id"], "") for c in cits), "", ""])
            key[str(i)] = lab["support"]
    # the judge's labels stay out of the annotation file: annotation is blind
    Path(a.out).with_suffix(".judge.json").write_text(json.dumps(key, indent=1))
    print(f"{len(key)} items -> {a.out} (judge labels in {Path(a.out).with_suffix('.judge.json')})")


def cmd_agreement(a) -> None:
    rows = list(csv.DictReader(open(a.file, encoding="utf-8")))
    key = json.loads(Path(a.file).with_suffix(".judge.json").read_text())
    hcol = next(c for c in rows[0] if c.startswith("human_support"))
    pairs = [(key[r["item"]], r[hcol].strip()) for r in rows if r[hcol].strip()]
    from .agreement import cohen_kappa
    k = cohen_kappa(pairs)
    print(json.dumps({"n": len(pairs), "raw_agreement": round(sum(x == y for x, y in pairs)
                                                               / len(pairs), 4) if pairs else None,
                      "cohen_kappa": k, "threshold": 0.7,
                      "judge_usable": k is not None and k >= 0.7}, indent=1))


def cmd_label(a) -> None:
    from .label import run as label_run
    label_run(Path(a.file))


def main() -> None:
    ap = argparse.ArgumentParser(prog="sourced")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--start", default="2025-02-03")
    g.add_argument("--days", type=int, default=182)
    g.add_argument("--facts", type=int, default=300)
    g.add_argument("--changes", type=int, default=40)
    g.add_argument("--tts-python", default=None)
    g.add_argument("--text-only", action="store_true", help="truth + text, no media files")
    r_ = sub.add_parser("run")
    r_.add_argument("--data", required=True)
    r_.add_argument("--system", required=True)
    r_.add_argument("--out", required=True)
    r_.add_argument("--track", default="T", choices=["T", "R"])
    r_.add_argument("--no-qa", action="store_true")
    r_.add_argument("--limit", type=int, default=None)
    r_.add_argument("--inject-rate", type=float, default=0.1)
    r_.add_argument("--pensine-mode", default="scripted", choices=["scripted", "llm"])
    s = sub.add_parser("score")
    s.add_argument("--data", required=True)
    s.add_argument("--run", required=True)
    s.add_argument("--out", default=None)
    s.add_argument("--judge", default="lexical", choices=["lexical", "model"])
    s.add_argument("--judge-url", default="http://127.0.0.1:8080/v1")
    s.add_argument("--judge-model", default="")
    n = sub.add_parser("annotate")
    n.add_argument("--data", required=True)
    n.add_argument("--run", required=True)
    n.add_argument("--report", required=True)
    n.add_argument("--n", type=int, default=100)
    n.add_argument("--seed", type=int, default=0)
    n.add_argument("--out", required=True)
    lb = sub.add_parser("label", help="blind annotation in the terminal")
    lb.add_argument("--file", required=True)
    ag = sub.add_parser("agreement")
    ag.add_argument("--file", required=True)
    a = ap.parse_args()
    {"generate": cmd_generate, "run": cmd_run, "score": cmd_score, "annotate": cmd_annotate,
     "agreement": cmd_agreement, "label": cmd_label}[a.cmd](a)


if __name__ == "__main__":
    main()
