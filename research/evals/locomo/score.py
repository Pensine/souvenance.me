#!/usr/bin/env python3
"""Scoring of LoCoMo results: token-overlap F1 per category.

Method aligned with the LoCoMo paper (SQuAD-style F1: normalisation,
token overlap). Category 5 (adversarial): the right answer is
NOT to answer — a binary score on abstention.

Usage: score.py [results/conv1.jsonl ...]   (default: all of results/)
"""

import argparse
import json
import re
import string
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

CATEGORIES = {1: "multi-hop", 2: "temporal", 3: "open-domain",
              4: "single-hop", 5: "adversarial"}

NO_INFO = re.compile(
    r"no (information|answer|memory|mention)|not (mentioned|enough|specified|"
    r"stated|known|available)|i don'?t know|unknown|cannot (answer|determine)",
    re.IGNORECASE)


def normalize(s: str) -> list[str]:
    s = str(s).lower()
    s = s.translate(str.maketrans("", "", string.punctuation))
    return [t for t in s.split() if t not in {"a", "an", "the"}]


def f1(pred: str, gold: str) -> float:
    p, g = normalize(pred), normalize(gold)
    if not p or not g:
        return float(p == g)
    common = 0
    g_pool = list(g)
    for tok in p:
        if tok in g_pool:
            g_pool.remove(tok)
            common += 1
    if common == 0:
        return 0.0
    precision, recall = common / len(p), common / len(g)
    return 2 * precision * recall / (precision + recall)


def score_row(row: dict) -> float:
    if row["category"] == 5:
        return 1.0 if NO_INFO.search(row["prediction"]) else 0.0
    return f1(row["prediction"], row["gold"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path,
                    default=sorted((HERE / "results").glob("conv*.jsonl")))
    args = ap.parse_args()
    if not args.files:
        sys.exit("no results — run run.py first")

    by_cat: dict[int, list[float]] = defaultdict(list)
    for path in args.files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            by_cat[row["category"]].append(score_row(row))

    print(f"\n| Category | n | Score |\n|---|---|---|")
    for cat in sorted(by_cat):
        scores = by_cat[cat]
        label = CATEGORIES.get(cat, str(cat))
        metric = "abstention" if cat == 5 else "F1"
        print(f"| {cat} — {label} | {len(scores)} | "
              f"{sum(scores) / len(scores):.3f} ({metric}) |")
    answerable = [s for c, ss in by_cat.items() if c != 5 for s in ss]
    everything = [s for ss in by_cat.values() for s in ss]
    if answerable:
        print(f"| **Overall F1 (cat. 1-4)** | {len(answerable)} | "
              f"**{sum(answerable) / len(answerable):.3f}** |")
    print(f"| overall (cat. 1-5) | {len(everything)} | "
          f"{sum(everything) / len(everything):.3f} |")
    print("\nComparison: report the published numbers (LoCoMo paper, "
          "Mem0 technical report) with their exact references — never "
          "quote them from memory.")


if __name__ == "__main__":
    main()
