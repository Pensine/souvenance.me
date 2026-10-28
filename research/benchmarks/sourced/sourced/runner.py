"""Drives one system through a life: day by day, checkpoints, questions."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from .adapters.base import DepositView, MemorySystem


def load(data_dir: Path) -> tuple[dict, list[dict], list[dict]]:
    truth = json.loads((data_dir / "truth.json").read_text(encoding="utf-8"))
    deposits = json.loads((data_dir / "deposits.json").read_text(encoding="utf-8"))
    questions = [json.loads(line) for line in
                 (data_dir / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return truth, deposits, questions


def view(d: dict, people: dict[str, str], data_dir: Path, track: str) -> DepositView:
    """The only door between the dataset and a system: no labels pass."""
    return DepositView(id=d["id"], kind=d["kind"], created_at=d["created_at"],
                       author=people.get(d["author"], ""),
                       recipient=people.get(d["recipient"] or "", ""),
                       text=d["text"] if track == "T" else None,
                       path=str((data_dir / d["file"]).resolve()) if d.get("file") else None)


def run(system: MemorySystem, data_dir: Path, track: str = "T", checkpoint_every: int = 7,
        qa: bool = True, limit_questions: int | None = None) -> dict:
    truth, deposits, questions = load(data_dir)
    people = {p["id"]: p["name"] for p in truth["people"]}
    start = date.fromisoformat(truth["start"])
    system.reset()
    snapshots = []
    write_unavailable = None
    t0 = time.time()
    for i in range(truth["days"]):
        day = start + timedelta(days=i)
        todays = [view(d, people, data_dir, track) for d in deposits
                  if d["created_at"][:10] == day.isoformat()]
        system.ingest(todays, day)
        system.end_of_day(day)
        last = i == truth["days"] - 1
        if write_unavailable is None and ((i + 1) % checkpoint_every == 0 or last):
            try:
                mems = system.memories()
            except NotImplementedError as exc:
                write_unavailable = f"not measurable: {exc}"
                continue
            snapshots.append({"at": (day + timedelta(days=1)).isoformat() + "T00:00:00",
                              "memories": [asdict(m) for m in mems]})
    answers = {}
    if qa:
        asked = date.fromisoformat(questions[0]["asked_at"]) if questions else start
        for q in questions[:limit_questions]:
            answers[q["id"]] = asdict(system.answer(q["question"], asked))
    return {"system": system.describe(), "track": track, "data": str(data_dir),
            "seconds": round(time.time() - t0, 1), "snapshots": snapshots,
            "write_unavailable": write_unavailable, "answers": answers}
