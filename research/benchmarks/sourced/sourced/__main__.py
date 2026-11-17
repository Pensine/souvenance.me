"""SOURCED command line.

  python -m sourced generate --out sample --seed 3 --days 14 --facts 30 --changes 4 \
                             [--phrasing dev|test|dev2]
                             [--tts-python /path/to/tts-venv/bin/python
                              --tts-engine chatterbox|piper --tts-device cpu|mps]
  python -m sourced run   --data sample --system oracle|injected|verbatim|pensine --out run.json
  python -m sourced score --data sample --run run.json [--judge lexical|model --judge-url URL
                                                        --judge-model NAME] --out report.json
  python -m sourced annotate  --data sample --report report.json --n 100 --out sample.csv
  python -m sourced label     --file sample.csv      # blind, resumable
  python -m sourced agreement --file sample.csv
  python -m sourced selfcheck --data sample --run r.json --report rep.json --out check.json
  python -m sourced reread    --file sample.csv --model claude-opus-5-5
  python -m sourced agreement --file sample.csv --reader sample.reader.json
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

AUDIO_LABELS = {
    "chatterbox": ("chatterbox-tts 0.1.7 (MIT), ResembleAI/chatterbox@5bb1f6e, Perth-watermarked; "
                   "voices cloned from public-domain LibriVox clips (sourced/voices/refs/REFS.md)"),
    "piper": ("piper-tts 1.8.0, public-domain voices (rhasspy/piper-voices@5041a7a): "
              "en_US-ljspeech, en_US-kristin, en_US-norman, en_US-john, en_GB-cori (medium)"),
}


def cmd_generate(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w = generate_world(seed=a.seed, start=a.start, days=a.days, n_facts=a.facts,
                       n_changes=a.changes, n_identity=a.identities,
                       n_bracketed=a.bracketed, poison=a.poison)
    deps = build_deposits(w, phrasing=a.phrasing)
    qs = derive_questions(w, deps)
    hashes = {}
    if not a.text_only:
        from .media import render_all
        hashes = render_all(deps, out, a.seed, a.tts_python, a.tts_engine, a.tts_device)
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
                   "changes": a.changes, "phrasing": a.phrasing,
                   # only when set: default manifests stay byte-identical
                   **{k: v for k, v in (("identities", a.identities),
                                        ("bracketed", a.bracketed)) if v is not None}},
        "counts": {"facts": len(w.facts), "changes": count_changes(w.facts, w.start),
                   "people": len(w.people), "traps": len(w.traps), "deposits": len(deps),
                   "questions": len(qs)},
        "deposits_by_kind": kinds, "questions_by_category": cats,
        "audio": (AUDIO_LABELS[a.tts_engine] if a.tts_python and not a.text_only
                  else "not rendered"),
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
        return InjectedSystem(truth, deps, qs, rate=a.inject_rate,
                              misattribution=a.misattribution_rate,
                              imprecision=a.imprecision_rate,
                              false_links=a.false_links)
    if name == "verbatim":
        from .adapters.controls import VerbatimSystem
        return VerbatimSystem()
    if name == "pensine":
        from .adapters.pensine import PensineSystem
        return PensineSystem(owner=next(p["name"] for p in truth["people"]
                                        if p["id"] == truth["owner"]),
                             mode=a.pensine_mode, truth=truth, deposits=deps)
    if name == "mem0":
        from .adapters.mem0 import Mem0System
        return Mem0System(owner=next(p["name"] for p in truth["people"]
                                     if p["id"] == truth["owner"]))
    if name == "graphiti":
        from .adapters.graphiti import GraphitiSystem
        return GraphitiSystem(owner=next(p["name"] for p in truth["people"]
                                         if p["id"] == truth["owner"]))
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
        if getattr(a, "judge_backend", "openai") == "claude-cli":
            from .judge import claude_cli_transport
            model = a.judge_model or "claude-sonnet-5-5"
            return ModelJudge(truth, deps, a.judge_url, model,
                              transport=claude_cli_transport(model))
        return ModelJudge(truth, deps, a.judge_url, a.judge_model)
    return LexicalJudge(truth, deps)


def cmd_score(a) -> None:
    from .runner import load
    from .score import score_run
    data = Path(a.data)
    truth, deps, qs = load(data)
    run = json.loads(Path(a.run).read_text(encoding="utf-8"))
    judge = make_judge(a, truth, deps)
    judge.workers = a.workers
    rep = score_run(truth, deps, qs, run, judge)
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
    truth, deps, _ = load(Path(a.data))
    names = {p["id"]: p["name"] for p in truth["people"]}

    def header(d) -> str:
        # who wrote it to whom: "my birthday" in a friend's message is the friend's
        who = f" from {names.get(d.get('author'), d.get('author'))}" if d.get("author") else ""
        to = f" to {names.get(d.get('recipient'), d.get('recipient'))}" if d.get("recipient") else ""
        return f"[{d['kind']}{who}{to}, {d['created_at'][:10]}]\n"

    texts = {d["id"]: header(d) + (d["text"] or "") for d in deps}
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
    """Judge against the human column, or against a second reader's labels
    (`--reader`, written by `reread`): the reference is named in the output."""
    rows = list(csv.DictReader(open(a.file, encoding="utf-8")))
    key = json.loads(Path(a.key or Path(a.file).with_suffix(".judge.json")).read_text())
    key = key.get("labels", key)  # a key written by `rejudge` names its judge
    if a.reader:
        other = json.loads(Path(a.reader).read_text(encoding="utf-8"))
        reference = other["reader"]
        pairs = [(key[i], lab) for i, lab in other["labels"].items() if i in key]
    else:
        reference = "human"
        hcol = next(c for c in rows[0] if c.startswith("human_support"))
        pairs = [(key[r["item"]], r[hcol].strip()) for r in rows if r[hcol].strip()]
    from .agreement import cohen_kappa
    k = cohen_kappa(pairs)
    binary = cohen_kappa([(x == "supported", y == "supported") for x, y in pairs])
    out = {"reference": reference, "n": len(pairs),
           "raw_agreement": round(sum(x == y for x, y in pairs) / len(pairs), 4)
           if pairs else None,
           "cohen_kappa": k, "cohen_kappa_supported_vs_not": binary, "threshold": 0.7,
           "judge_usable": k is not None and k >= 0.7}
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


def cmd_rejudge(a) -> None:
    """Label an annotation sample again with the current judge: each item's
    memory is found by its text in the final snapshot of the given runs."""
    from concurrent.futures import ThreadPoolExecutor
    from .runner import load
    rows = list(csv.DictReader(open(a.file, encoding="utf-8")))
    todo = {}
    for pair in a.source:
        data, run_path = pair.split(":", 1)
        truth, deps, _ = load(Path(data))
        judge = make_judge(a, truth, deps)
        run = json.loads(Path(run_path).read_text(encoding="utf-8"))
        by_text = {m["content"]: m for m in run["snapshots"][-1]["memories"]}
        for r in rows:
            if r["item"] not in todo and r["memory"] in by_text:
                todo[r["item"]] = (judge, by_text[r["memory"]])
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        labels = list(ex.map(lambda jm: jm[0].label(jm[1])["support"], todo.values()))
    out = Path(a.out) if a.out else Path(a.file).with_suffix(".rejudge.json")
    name = next(iter(todo.values()))[0].name if todo else None
    out.write_text(json.dumps({"judge": name, "labels": dict(zip(todo, labels)),
                               "not_found": [r["item"] for r in rows if r["item"] not in todo]},
                              indent=1), encoding="utf-8")
    print(f"{len(todo)}/{len(rows)} items judged by {name} -> {out}")


def cmd_selfcheck(a) -> None:
    """Mutation control: does the judge flag memories edited to be false,
    and leave verbatim excerpts alone? (SPEC §6, no annotator needed.)"""
    from .runner import load
    from .selfcheck import dump, mutation_control
    truth, deps, _ = load(Path(a.data))
    run = json.loads(Path(a.run).read_text(encoding="utf-8"))
    rep = json.loads(Path(a.report).read_text(encoding="utf-8")) if a.report else None
    res = mutation_control(truth, deps, run, make_judge(a, truth, deps), report=rep, n=a.n,
                           n_verbatim=a.verbatim, seed=a.seed, workers=a.workers)
    if a.out:
        Path(a.out).write_text(dump(res), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "items"}, indent=1))


def cmd_reread(a) -> None:
    """Second reader: another model labels the `annotate` sample blind."""
    from .judge import claude_cli_transport
    from .selfcheck import dump, reread
    rows = list(csv.DictReader(open(a.file, encoding="utf-8")))
    res = reread(rows, claude_cli_transport(a.model), a.model, workers=a.workers)
    out = Path(a.out) if a.out else Path(a.file).with_suffix(".reader.json")
    out.write_text(dump(res), encoding="utf-8")
    print(f"{len(res['labels'])} items read by {res['reader']}, "
          f"{len(res['unparsed'])} unparsed -> {out}")


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
    g.add_argument("--tts-engine", default="chatterbox", choices=["chatterbox", "piper"])
    g.add_argument("--tts-device", default="cpu", choices=["cpu", "mps"])
    g.add_argument("--identities", type=int, default=None,
                   help="people in the identity layer (default: one per 60 facts, at least 2)")
    g.add_argument("--bracketed", type=int, default=None,
                   help="facts dated only by a not-yet / already pair (default: one per 30)")
    g.add_argument("--poison", action="store_true",
                   help="add the poison layer: false claims about the owner from sources "
                        "with no authority (dev wordings only)")
    g.add_argument("--text-only", action="store_true", help="truth + text, no media files")
    g.add_argument("--phrasing", default="dev", choices=["dev", "test", "dev2"],
                   help="deposit templates: dev (the published sample), the held-out set "
                        "(test), or a second development set (dev2)")
    r_ = sub.add_parser("run")
    r_.add_argument("--data", required=True)
    r_.add_argument("--system", required=True)
    r_.add_argument("--out", required=True)
    r_.add_argument("--track", default="T", choices=["T", "R"])
    r_.add_argument("--no-qa", action="store_true")
    r_.add_argument("--limit", type=int, default=None)
    r_.add_argument("--inject-rate", type=float, default=0.1)
    r_.add_argument("--misattribution-rate", type=float, default=0.0,
                    help="injected control: share of true memories given a wrong subject")
    r_.add_argument("--false-links", type=int, default=0,
                    help="injected control: number of decoy identity links added")
    r_.add_argument("--imprecision-rate", type=float, default=0.0,
                    help="injected control: share of bounded_date answers given as one date")
    r_.add_argument("--pensine-mode", default="scripted", choices=["scripted", "llm"])
    s = sub.add_parser("score")
    s.add_argument("--data", required=True)
    s.add_argument("--run", required=True)
    s.add_argument("--out", default=None)
    s.add_argument("--judge", default="lexical", choices=["lexical", "model"])
    s.add_argument("--judge-url", default="http://127.0.0.1:8080/v1")
    s.add_argument("--judge-model", default="")
    s.add_argument("--judge-backend", default="openai", choices=["openai", "claude-cli"],
                   help="claude-cli: Claude Code headless on the user's subscription")
    s.add_argument("--workers", type=int, default=1, help="parallel calls to a model judge")
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
    ag.add_argument("--reader", default=None,
                    help="labels written by `reread`: agreement with a second reader")
    ag.add_argument("--out", default=None)
    ag.add_argument("--key", default=None,
                    help="judge labels to compare (default: the .judge.json beside the file)")
    rj = sub.add_parser("rejudge", help="label an annotation sample with the current judge")
    rj.add_argument("--file", required=True)
    rj.add_argument("--source", action="append", required=True, metavar="DATA:RUN",
                    help="a data directory and a run file holding the sampled memories")
    rj.add_argument("--workers", type=int, default=1)
    rj.add_argument("--out", default=None)
    rj.add_argument("--judge", default="lexical", choices=["lexical", "model"])
    rj.add_argument("--judge-url", default="http://127.0.0.1:8080/v1")
    rj.add_argument("--judge-model", default="")
    rj.add_argument("--judge-backend", default="openai", choices=["openai", "claude-cli"])
    sc = sub.add_parser("selfcheck", help="mutation control of the judge, no annotator")
    sc.add_argument("--data", required=True)
    sc.add_argument("--run", required=True)
    sc.add_argument("--report", default=None,
                    help="this judge's report on the run: only memories it called supported")
    sc.add_argument("--n", type=int, default=60)
    sc.add_argument("--verbatim", type=int, default=30)
    sc.add_argument("--seed", type=int, default=0)
    sc.add_argument("--workers", type=int, default=1)
    sc.add_argument("--out", default=None)
    sc.add_argument("--judge", default="lexical", choices=["lexical", "model"])
    sc.add_argument("--judge-url", default="http://127.0.0.1:8080/v1")
    sc.add_argument("--judge-model", default="")
    sc.add_argument("--judge-backend", default="openai", choices=["openai", "claude-cli"])
    rr = sub.add_parser("reread", help="second reader: a model labels the sample blind")
    rr.add_argument("--file", required=True)
    rr.add_argument("--model", required=True)
    rr.add_argument("--workers", type=int, default=1)
    rr.add_argument("--out", default=None)
    a = ap.parse_args()
    {"generate": cmd_generate, "run": cmd_run, "score": cmd_score, "annotate": cmd_annotate,
     "agreement": cmd_agreement, "label": cmd_label, "selfcheck": cmd_selfcheck,
     "reread": cmd_reread, "rejudge": cmd_rejudge}[a.cmd](a)


if __name__ == "__main__":
    main()
