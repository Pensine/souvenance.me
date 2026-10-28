#!/usr/bin/env python3
"""RAM et latence d'un reranker, mesurées dans un processus neuf.

Usage : mesure_reranker.py <modèle> [--device cpu] [--paires 30] [--repetitions 20]

Mesure la mémoire résidente avant et après chargement, puis le temps de
notation de N paires (question, souvenir) — le travail réel d'un rappel.
Les paires sont des tours de dialogue LoCoMo de longueur réaliste.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "locomo"))


def rss_mo() -> float:
    """Mémoire résidente courante (ps, en Mo) — pas le pic de getrusage."""
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(__import__("os").getpid())],
                         capture_output=True, text=True).stdout
    return int(out.strip()) / 1024


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--paires", type=int, default=30)
    ap.add_argument("--repetitions", type=int, default=20)
    args = ap.parse_args()

    import common
    sample = common.load_dataset()[0]
    turns = [f"{t['speaker']}: {t['text']}" for _, _, ts in common.sessions(sample)
             for t in ts][: args.paires]
    questions = [q["question"] for q in sample["qa"][: args.repetitions]]

    import torch  # noqa: F401  (chargé avant la mesure : il n'est pas le modèle)
    from sentence_transformers import CrossEncoder
    base = rss_mo()
    t0 = time.perf_counter()
    model = CrossEncoder(args.model, max_length=512, device=args.device)
    load_s = time.perf_counter() - t0
    loaded = rss_mo()
    model.predict([(questions[0], turns[0])], show_progress_bar=False)  # échauffement
    times = []
    for q in questions:
        t0 = time.perf_counter()
        model.predict([(q, t) for t in turns], batch_size=16, show_progress_bar=False)
        times.append((time.perf_counter() - t0) * 1000)
    after = rss_mo()
    print(json.dumps({
        "modele": args.model, "device": args.device, "paires": args.paires,
        "chargement_s": round(load_s, 1),
        "ram_modele_mo": round(loaded - base), "ram_apres_inference_mo": round(after - base),
        "rss_total_mo": round(after),
        "latence_ms_moy": round(statistics.mean(times)),
        "latence_ms_p95": round(sorted(times)[int(0.95 * (len(times) - 1))]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
