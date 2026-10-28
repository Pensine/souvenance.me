#!/usr/bin/env python3
"""Tableaux du banc de rappel, avec intervalles de confiance appariés.

Lit results/<condition>*.jsonl et écrit results/tableau.md. Chaque écart à
« avant » porte un intervalle de confiance à 95 % par bootstrap apparié
(mêmes questions rééchantillonnées pour les deux conditions, 2 000 tirages,
graine fixe) : un gain dont l'intervalle contient 0 n'est pas un gain.
"""

import json
import random
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
ORDER = ["avant", "plein-texte", "hybride", "hybride+temps", "rerank-minilm", "rerank-bge-m3"]
METRICS = [("r@5", "R@5"), ("r@10", "R@10"), ("rr", "MRR@10")]
SUBSETS = {
    "toutes (cat. 1-4)": lambda r: r["category"] != 5,
    "conv. 1 (réglage)": lambda r: r["category"] != 5 and r["conv"] == 1,
    "conv. 2-10 (jamais vues au réglage)": lambda r: r["category"] != 5 and r["conv"] > 1,
    "avec repère temporel": lambda r: r["category"] != 5 and r.get("cue"),
    "multi-saut (cat. 1)": lambda r: r["category"] == 1,
    "temporel (cat. 2)": lambda r: r["category"] == 2,
    "ouvert (cat. 3)": lambda r: r["category"] == 3,
    "simple (cat. 4)": lambda r: r["category"] == 4,
}


def load() -> dict[str, dict]:
    out = {}
    for cond in ORDER:
        files = sorted(RESULTS.glob(f"{cond}.jsonl")) + sorted(RESULTS.glob(f"{cond}-rerank.jsonl"))
        if files:
            out[cond] = {(r["conv"], r["idx"]): r for r in
                         map(json.loads, files[0].read_text(encoding="utf-8").splitlines())}
    return out


def ci(base: list[float], new: list[float], n: int = 2000) -> tuple[float, float]:
    rng = random.Random(42)
    diffs = [b - a for a, b in zip(base, new)]
    means = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def main() -> None:
    data = load()
    base = data["avant"]
    lines = []
    # « avant » au sens strict : questions où le repère temporel a été calculé
    cued = {k for c in data.values() for k, r in c.items() if r.get("cue")}
    for name, keep in SUBSETS.items():
        keys = [k for k, r in base.items()
                if (keep(r) if name != "avec repère temporel"
                    else r["category"] != 5 and k in cued)]
        if not keys:
            continue
        lines += [f"\n### {name} — {len(keys)} questions\n",
                  "| condition | R@5 | R@10 | MRR@10 | ms (moy.) |", "|---|---|---|---|---|"]
        for cond, recs in data.items():
            cells = []
            for m, _ in METRICS:
                vals = [recs[k][m] for k in keys]
                cell = f"{statistics.mean(vals):.3f}"
                if cond != "avant":
                    lo, hi = ci([base[k][m] for k in keys], vals)
                    cell += f" ({statistics.mean(vals) - statistics.mean(base[k][m] for k in keys):+.3f} [{lo:+.3f} ; {hi:+.3f}])"
                cells.append(cell)
            ms = statistics.mean(recs[k]["ms"] for k in keys)
            lines.append(f"| {cond} | " + " | ".join(cells) + f" | {ms:.0f} |")
    text = ("Écarts à « avant » entre parenthèses, avec IC 95 % par bootstrap apparié.\n"
            + "\n".join(lines) + "\n")
    (RESULTS / "tableau.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
