"""Blind annotation in the terminal: one memory at a time, nothing else.

    python -m sourced label --file ann.csv

The annotator sees the memory, the excerpts it cites and the full text of
the cited deposits, never the judge's label (kept in ann.judge.json, which
this tool does not open). Each answer is written to the CSV immediately:
quitting and coming back resumes at the first unlabelled item.

Keys: s = supported, p = partial, u = unsupported, n = add a note,
      b = back one item, q = quit.
"""

from __future__ import annotations

import csv
import shutil
import textwrap
from pathlib import Path

LABELS = {"s": "supported", "p": "partial", "u": "unsupported"}
GUIDE = """Question: do the person's deposits support this memory?
  supported   - every part of it is said, or plainly implied, by the deposits
  partial     - part of it is supported, part is not (a detail, a date, a name)
  unsupported - it is not in the deposits, or it turns a plan, a hypothesis,
                a negation or hearsay into a fact, or describes a photo
Photo deposits only carry a date and a GPS position. Knowing which city a
position is in counts as ordinary knowledge."""


def _wrap(text: str, width: int, indent: str = "  ") -> str:
    return "\n".join(textwrap.fill(line, width, initial_indent=indent,
                                   subsequent_indent=indent) or indent
                     for line in (text or "").split("\n"))


def run(path: Path, inp=input, out=print) -> dict:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    head, items = rows[0], rows[1:]
    hcol = next(i for i, c in enumerate(head) if c.startswith("human_support"))
    ncol = head.index("human_note")
    width = min(100, shutil.get_terminal_size((100, 30)).columns - 2)

    def save():
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows([head, *items])
        tmp.replace(path)

    out(GUIDE)
    i = next((k for k, r in enumerate(items) if not r[hcol].strip()), len(items))
    while i < len(items):
        r = items[i]
        done = sum(1 for x in items if x[hcol].strip())
        out("\n" + "=" * width)
        out(f"Item {r[0]}  ({done}/{len(items)} labelled)")
        out("MEMORY:\n" + _wrap(r[1], width))
        out("CITED EXCERPTS:\n" + _wrap(r[2] or "(none)", width))
        out("CITED DEPOSITS:\n" + _wrap((r[3] or "(none)").replace(" || ", "\n---\n"), width))
        k = inp("[s/p/u, n=note, b=back, q=quit] > ").strip().lower()
        if k == "q":
            break
        if k == "b":
            i = max(0, i - 1)
            items[i][hcol] = ""
            continue
        if k == "n":
            r[ncol] = inp("note > ").strip()
            save()
            continue
        if k in LABELS:
            r[hcol] = LABELS[k]
            save()
            i += 1
    done = sum(1 for x in items if x[hcol].strip())
    out(f"\n{done}/{len(items)} labelled, saved in {path}")
    return {"labelled": done, "total": len(items)}
