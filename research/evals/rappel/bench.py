#!/usr/bin/env python3
"""Banc de rappel : la Pensine retrouve-t-elle les tours qui portent la preuve ?

Sans juge LLM, sans API, sans consolidation : chaque tour de dialogue LoCoMo
devient une mémoire (texte du tour, date de sa session, embedding local),
puis chaque question passe par la première étape de `recall` — recherche,
puis `temporal.rank` — et l'on regarde si les tours cités en preuve par
LoCoMo (`evidence`, ex. « D1:3 ») sont dans les 5 ou 10 premiers.

Usage :
  bench.py                         # les 10 conversations, toutes les conditions
  bench.py --conv 1 --conditions avant,hybride
  bench.py --reset                 # reconstruit les bases du banc

Base jetable : conteneur locomo-eval (port 5442), une base `rappel_c<n>`
par conversation — jamais la prod (URL fixée ici, aucun .env lu).
"""

import argparse
import json
import os
import re
import resource
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCOMO = HERE.parent / "locomo"
sys.path.insert(0, str(LOCOMO))
import common  # noqa: E402  (dataset, dates de session, URL de la base jetable)

os.environ["PENSINE_DATABASE_URL"] = common.db_url(0, "locomo")  # avant tout import pensine
os.environ["PENSINE_CONSTITUTION"] = str(LOCOMO / "constitution-eval.yaml")
os.environ.setdefault("PENSINE_RERANKER", "")
sys.path.insert(0, str(common.REPO))

RESULTS = HERE / "results"
KS = (5, 10)

# condition → (mode de recherche, période ciblée ?, reranker)
CONDITIONS = {
    "avant": ("vector", False, ""),
    "plein-texte": ("lexical", False, ""),
    "hybride": ("hybrid", False, ""),
    "hybride+temps": ("hybrid", True, ""),
    "rerank-minilm": ("hybrid", True, "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"),
    "rerank-bge-m3": ("hybrid", True, "BAAI/bge-reranker-v2-m3"),
}
CATEGORIES = {1: "multi-saut", 2: "temporel", 3: "ouvert", 4: "simple", 5: "adversarial"}


def db_name(conv: int) -> str:
    return f"rappel_c{conv}"


def use_db(conv: int) -> None:
    from pensine import config
    config.DATABASE_URL = common.db_url(conv, db_name(conv))


def build(conv: int, sample: dict, reset: bool) -> int:
    """Crée la base de la conversation et y écrit un souvenir par tour."""
    import subprocess

    import psycopg

    from pensine import db, embeddings

    name = db_name(conv)
    with psycopg.connect(common.db_url(conv, "locomo"), autocommit=True) as c:
        if reset:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            c.execute(f'CREATE DATABASE "{name}"')
    url = common.db_url(conv, name)
    with psycopg.connect(url) as c:
        if not c.execute("SELECT 1 FROM information_schema.tables "
                         "WHERE table_name = 'events'").fetchone():
            c.execute((common.REPO / "db" / "schema.sql").read_text(encoding="utf-8"))
            c.commit()
    subprocess.run([sys.executable, str(common.REPO / "scripts" / "migrate.py")],
                   env={**os.environ, "PENSINE_DATABASE_URL": url},
                   check=True, stdout=subprocess.DEVNULL)
    use_db(conv)
    turns = [(dt, t) for _, dt, ts in common.sessions(sample) for t in ts]
    with db.connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS bench_turns "
                     "(memory_id BIGINT PRIMARY KEY, dia_id TEXT UNIQUE)")
        have = conn.execute("SELECT count(*) AS n FROM bench_turns").fetchone()["n"]
        if have == len(turns):
            return have
        conn.execute("TRUNCATE memories, bench_turns CASCADE")
        t0 = time.time()
        for i, (dt, t) in enumerate(turns):
            text = f"{t['speaker']}: {t.get('text', '')}"
            if t.get("blip_caption"):
                text += f" [shares a photo: {t['blip_caption']}]"
            vec = embeddings.embed(text, "document")
            mid = conn.execute(
                """INSERT INTO memories (type, content, embedding, confidence,
                                         importance, valid_from)
                   VALUES ('episodic', %s, %s::vector, 1.0, 0.5, %s) RETURNING id""",
                (text, str(list(vec)) if vec else None, dt)).fetchone()["id"]
            conn.execute("INSERT INTO bench_turns VALUES (%s, %s) "
                         "ON CONFLICT (dia_id) DO NOTHING", (mid, t["dia_id"]))
            if (i + 1) % 200 == 0:
                print(f"    {i + 1}/{len(turns)} tours ({time.time() - t0:.0f} s)", flush=True)
        conn.commit()
    return len(turns)


def gold(q: dict, known: set[str]) -> list[str]:
    """Les tours cités en preuve. Quelques preuves LoCoMo sont mal formées
    (« D8:6; D9:17 », « D:11:26 ») : on en extrait tous les « D<n>:<m> »."""
    found = []
    for e in q.get("evidence") or []:
        for s, t in re.findall(r"D:?(\d+):(\d+)", e):
            d = f"D{s}:{t}"
            if d in known and d not in found:
                found.append(d)
    return found


def retrieve(conn, question: str, mode: str, use_window: bool, limit: int):
    """La première étape de recall, à l'identique : 24 candidats, puis le temps."""
    from pensine import db, embeddings, temporal

    vector = embeddings.embed(question)
    orientation = temporal.intent(question)
    window = None
    cue = None
    if use_window:
        cue = temporal.cues(question, landmarks=[])
        window = temporal.window_bounds(cue)
        if cue and cue["passee"] and orientation is None:
            orientation = "past"
    t0 = time.perf_counter()
    if mode == "lexical":
        from pensine import retrieval
        where, params = db._search_filters(True, orientation == "past")
        rows = db.lexical_candidates(conn, retrieval.terms(question), 24, where, params)
    else:
        rows = db.search_memories(conn, question, list(vector) if vector else None,
                                  limit=24, include_past=True,
                                  include_archived=(orientation == "past"), mark=False,
                                  window=window, mode=mode)
    found = temporal.rank(rows, orientation, limit=limit, window=window)
    return found, (time.perf_counter() - t0) * 1000, cue


def evaluate(conv: int, sample: dict, condition: str) -> list[dict]:
    from pensine import config, db, retrieval
    from pensine import temporal

    mode, use_window, reranker = CONDITIONS[condition]
    if config.RERANKER_MODEL != reranker:
        config.RERANKER_MODEL = reranker
        retrieval._reranker, retrieval._reranker_failed = None, False
    use_db(conv)
    # le « présent » du banc : le lendemain de la dernière session
    corpus_end = max(dt for _, dt, _ in common.sessions(sample))
    frozen = corpus_end + timedelta(days=1)

    class Frozen(temporal.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: N805
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)
    temporal.datetime = Frozen

    out = []
    with db.connection() as conn:
        ids = {r["memory_id"]: r["dia_id"] for r in
               conn.execute("SELECT memory_id, dia_id FROM bench_turns").fetchall()}
        known = set(ids.values())
        for idx, q in enumerate(sample["qa"]):
            g = gold(q, known)
            if not g:
                continue
            found, ms, cue = retrieve(conn, q["question"], mode, use_window, max(KS))
            got = [ids.get(r["id"]) for r in found]
            rec = {"conv": conv, "idx": idx, "category": q["category"],
                   "gold": g, "got": got, "ms": round(ms, 1),
                   "rerank_ms": retrieval.last_rerank_ms,
                   "cue": cue["repere"] if cue else None}
            for k in KS:
                rec[f"r@{k}"] = len(set(g) & set(got[:k])) / len(g)
            first = next((i for i, d in enumerate(got) if d in g), None)
            rec["rr"] = 1 / (first + 1) if first is not None else 0.0
            out.append(rec)
        conn.rollback()  # rien n'est écrit pendant la mesure
    return out


def summarize(records: list[dict]) -> dict:
    def agg(rs):
        if not rs:
            return None
        return {"n": len(rs),
                **{f"R@{k}": round(statistics.mean(r[f"r@{k}"] for r in rs), 4) for k in KS},
                "MRR@10": round(statistics.mean(r["rr"] for r in rs), 4),
                "ms_moy": round(statistics.mean(r["ms"] for r in rs), 1),
                "ms_p95": round(sorted(r["ms"] for r in rs)[int(0.95 * (len(rs) - 1))], 1)}
    main = [r for r in records if r["category"] != 5]
    return {"cat1-4": agg(main),
            **{f"cat{c}-{CATEGORIES[c]}": agg([r for r in records if r["category"] == c])
               for c in CATEGORIES},
            "avec_repere_temporel": agg([r for r in main if r["cue"]])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conv", type=int, action="append", choices=range(1, 11),
                    help="répétable ; défaut : les 10")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--reset", action="store_true", help="reconstruit les bases du banc")
    ap.add_argument("--tag", default="", help="suffixe du fichier de résultats")
    args = ap.parse_args()

    data = common.load_dataset()
    convs = args.conv or list(range(1, 11))
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    for c in conditions:
        if c not in CONDITIONS:
            sys.exit(f"condition inconnue : {c} ({', '.join(CONDITIONS)})")

    for conv in convs:
        n = build(conv, data[conv - 1], args.reset)
        print(f"conv {conv} : {n} tours en base", flush=True)

    RESULTS.mkdir(exist_ok=True)
    report = {"conversations": convs, "conditions": {}}
    for cond in conditions:
        t0 = time.time()
        records = [r for conv in convs for r in evaluate(conv, data[conv - 1], cond)]
        s = summarize(records)
        rms = [r["rerank_ms"] for r in records if r["rerank_ms"] is not None]
        s["rerank_ms_moy"] = round(statistics.mean(rms), 1) if rms else None
        s["rss_max_mo"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                                / (1024 * 1024 if sys.platform == "darwin" else 1024))
        report["conditions"][cond] = s
        with (RESULTS / f"{cond}{args.tag}.jsonl").open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        m = s["cat1-4"]
        print(f"{cond:15s} R@5 {m['R@5']:.3f}  R@10 {m['R@10']:.3f}  "
              f"MRR {m['MRR@10']:.3f}  {m['ms_moy']:.0f} ms  ({time.time() - t0:.0f} s)",
              flush=True)
    (RESULTS / f"resume{args.tag}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
