#!/usr/bin/env python3
"""Integrity report: three indicators, one command (see pensine/integrity.py).

  A. invention rate at write time    (the database's audit log)
  B. support rate of kept memories   (the database's memories + deposits)
  C. recall / invention frontier     (raw candidates kept by the database,
                                      or nights replayed from a file)

Usage:
  integrity_report.py --out report/                       # A and B on the configured database
  integrity_report.py --no-db --nights nights.json --out report/        # C only
  integrity_report.py --no-db --dataset dataset.json --run outputs/M.json \\
                      [--verdicts verdicts.json --model M] [--palier2] --out report/
                                                         # C on the frugal bench (--run reference: control)

`nights.json`: [{"night", "events": [...], "candidates": [...]}], a candidate
may carry `_verdict` (fidele | approximative | inventee).

No model call by default. `--modele` enables the review by the configured
model (indicator B, and tier 3 of the frontier): it costs money.

Outputs: rapport.md (readable) and rapport.json (machine). Counts only:
no memory content comes out of it, the report is publishable.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, integrity  # noqa: E402


def from_db(args, ask, extract_json) -> dict:
    from pensine import db
    with db.connection() as conn:
        audits = conn.execute(
            "SELECT at, detail FROM audit_log WHERE actor = 'consolidation' "
            "AND action = 'evidence' ORDER BY at").fetchall()
        mems = conn.execute(
            "SELECT id, type, content, evidence, source_event_ids FROM memories "
            "WHERE superseded_by IS NULL").fetchall()
        ids = sorted({i for m in mems if m["evidence"] for i in m["source_event_ids"] or []})
        sources = {}
        for r in db.source_events(conn, ids):
            r = dict(r)
            if r.get("forgotten"):
                continue
            r["media_transcript"], r["media_description"] = r.get("transcript"), \
                r.get("description")
            sources[r["id"]] = r
        try:
            with conn.transaction():
                nights = integrity.nights_from_db(conn)
        except Exception:  # noqa: BLE001 — table missing: migration 014 not applied
            nights = []
    out = {"invention": integrity.invention_at_write([dict(a) for a in audits]),
            "soutien": integrity.support_rate([dict(m) for m in mems], sources,
                                              config.OWNER_NAME, ask=ask,
                                              extract_json=extract_json,
                                              max_modele=args.max_modele)}
    if nights:
        out["frontiere"] = integrity.frontier(nights, owner=args.owner, ask=ask,
                                              extract_json=extract_json)
    return out


def load_nights(args) -> list[dict] | None:
    if args.nights:
        return json.loads(args.nights.read_text(encoding="utf-8"))
    if args.dataset and args.run:
        ref = str(args.run) == "reference"
        verdicts = None
        if args.verdicts:
            allv = json.loads(args.verdicts.read_text(encoding="utf-8"))
            verdicts = allv.get(args.model or ("reference (production)" if ref
                                               else args.run.stem))
        return integrity.nights_from_bench(
            json.loads(args.dataset.read_text(encoding="utf-8")),
            None if ref else json.loads(args.run.read_text(encoding="utf-8")), verdicts)
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--no-db", action="store_true", help="do not read the database (A and B omitted)")
    p.add_argument("--nights", type=Path)
    p.add_argument("--dataset", type=Path)
    p.add_argument("--run", type=Path, help="output of run.py, or \"reference\"")
    p.add_argument("--palier2", action="store_true",
                   help="also evaluate tier 2 alone against the judge's verdicts")
    p.add_argument("--verdicts", type=Path)
    p.add_argument("--model", help="model key in verdicts.json (default: the run's name)")
    p.add_argument("--owner", default=config.OWNER_NAME)
    p.add_argument("--modele", action="store_true",
                   help="review by the configured model (paid, depending on the backend)")
    p.add_argument("--max-modele", type=int, default=50)
    args = p.parse_args()

    ask = extract_json = None
    if args.modele:
        from pensine import llm
        ask, extract_json = llm.complete, llm.extract_json

    report = {"genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "relecture_modele": bool(args.modele)}
    if not args.no_db:
        report.update(from_db(args, ask, extract_json))
    nights = load_nights(args)
    if nights is not None:
        report["frontiere"] = integrity.frontier(nights, owner=args.owner, ask=ask,
                                                 extract_json=extract_json)
        if args.palier2:
            report["palier2"] = integrity.palier2(nights, owner=args.owner)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "rapport.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = integrity.render_markdown(report)
    (args.out / "rapport.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
