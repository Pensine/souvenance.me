"""Scoring: write-time integrity, recall/invention curve, question answering.

All definitions are in SPEC.md §4; this file is their executable form.
Denominators are always reported next to rates, and nothing is imputed: a
metric a system cannot be measured on is reported as null with a reason.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .judge import date_mentions, normalize

ABSTAIN = re.compile(r"(?i)\b(no information|not (?:mentioned|recorded|stated|known|in (?:my|the) "
                     r"memor)|i don'?t know|unknown|cannot (?:tell|answer|find)|no record|"
                     r"there is no (?:record|mention|information)|not enough information|"
                     r"i have no)\b")
# a city named in another language is the same answer (systems may write
# memories in the owner's language: Pensine's prompt is French)
EXONYMS = {"Ghent": ["Gand", "Gent"], "Turin": ["Torino"], "Edinburgh": ["Édimbourg"],
           "Gothenburg": ["Göteborg", "Goteborg"], "Montreal": ["Montréal"],
           "Valencia": ["Valence", "València"], "Lyon": ["Lyons"], "Porto": ["Oporto"]}
WORDNUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}


# --- write-time ------------------------------------------------------------

def gold_facts_at(truth: dict, deposits: list[dict], at: str) -> list[dict]:
    """Facts carried by at least one deposit created before `at`."""
    seen = {f for d in deposits if d["created_at"] < at for f in d["fact_ids"]}
    return [f for f in truth["facts"] if f["id"] in seen]


def score_snapshot(truth: dict, deposits: list[dict], snapshot: dict, judge) -> dict:
    at = snapshot["at"]
    mems = snapshot["memories"]
    labels = [judge.label(m) for m in mems]
    gold = gold_facts_at(truth, deposits, at)
    gold_ids = {f["id"] for f in gold}
    n = len(mems)
    invented = [i for i, lab in enumerate(labels) if lab["support"] == "unsupported"]
    partial = [i for i, lab in enumerate(labels) if lab["support"] == "partial"]
    trap_hits = sorted({t for lab in labels for t in lab["traps"]})
    covered = {x["fact_id"] for lab in labels for x in lab["facts"]
               if x["status"] == "correct"} & gold_ids
    cited = [i for i, m in enumerate(mems) if m.get("citations")]
    cit_ok = [i for i in cited if labels[i]["citation_found"] and labels[i]["citation_supports"]]
    # temporal integrity: superseded facts still presented as current
    superseded = {f["id"] for f in gold if f["valid_to"] and f["valid_to"] <= at[:10]}
    exposes_currency = any(m.get("current") is not None for m in mems)
    stale = sorted({x["fact_id"] for i, lab in enumerate(labels) for x in lab["facts"]
                    if x["fact_id"] in superseded and mems[i].get("current") is True})
    per_kind: dict[str, list[int]] = {}
    for f in gold:
        k = "change" if (f["supersedes"] or (f["kind"] == "state" and
                                             f["valid_from"] >= truth["start"])) else f["kind"]
        per_kind.setdefault(k, [0, 0])
        per_kind[k][1] += 1
        per_kind[k][0] += f["id"] in covered
    return {
        "at": at,
        "memories": n,
        "invention_rate": _rate(len(invented), n),
        "partial_rate": _rate(len(partial), n),
        "invented": [mems[i]["content"] for i in invented][:50],
        "trap_hits": trap_hits,
        "traps_total": len([t for t in truth["traps"] if t["day"] < at[:10]]),
        "excerpt_support_rate": _rate(len(cit_ok), n),   # over ALL memories: no citation = no support
        "citing_memories": len(cited),
        "fact_recall": _rate(len(covered), len(gold)),
        "omission_rate": _rate(len(gold) - len(covered), len(gold)),
        "recall_by_kind": {k: _rate(a, b) for k, (a, b) in sorted(per_kind.items())},
        "stale_as_current": (_rate(len(stale), len(superseded)) if exposes_currency and superseded
                             else None),
        "stale_reason": None if exposes_currency else "system does not expose currency",
        "curve": curve(mems, labels, gold_ids),
        "labels": labels,
    }


def curve(mems: list[dict], labels: list[dict], gold_ids: set[str]) -> dict:
    """Recall/invention curve over the system's own confidence.

    Memories are kept from most to least confident; at each distinct
    threshold we record (invention rate among kept, recall of gold facts).
    Headline points: recall at invention <= 1 % and <= 5 %."""
    if not mems:
        return {"points": [], "recall_at_inv_1pct": 0.0, "recall_at_inv_5pct": 0.0,
                "has_confidence": False}
    has_conf = all(m.get("confidence") is not None for m in mems)
    order = sorted(range(len(mems)), key=lambda i: -(mems[i].get("confidence") or 0)) \
        if has_conf else list(range(len(mems)))
    points, kept_inv, covered = [], 0, set()
    for rank, i in enumerate(order, 1):
        kept_inv += labels[i]["support"] == "unsupported"
        covered |= {x["fact_id"] for x in labels[i]["facts"] if x["status"] == "correct"} & gold_ids
        last = rank == len(order)
        nxt = None if last else mems[order[rank]].get("confidence")
        if not has_conf and not last:
            continue
        if has_conf and not last and nxt == mems[i].get("confidence"):
            continue
        points.append({"threshold": mems[i].get("confidence"), "kept": rank,
                       "invention": kept_inv / rank,
                       "recall": len(covered) / len(gold_ids) if gold_ids else 0.0})

    def best(limit):
        ok = [p["recall"] for p in points if p["invention"] <= limit]
        return max(ok) if ok else 0.0
    return {"points": points, "recall_at_inv_1pct": best(0.01),
            "recall_at_inv_5pct": best(0.05), "has_confidence": has_conf}


# --- question answering ----------------------------------------------------

def is_abstention(answer: dict) -> bool:
    if answer.get("abstained") is not None:
        return bool(answer["abstained"])
    return bool(ABSTAIN.search(answer.get("text") or ""))


def _numbers(text: str) -> list[int]:
    t = normalize(text)
    out = [int(x) for x in re.findall(r"\b\d+\b", t)]
    out += [WORDNUM[w] for w in t.split() if w in WORDNUM]
    if re.search(r"\ba week\b|\bone week\b", t):
        out.append(7)
    return out


def correct(q: dict, answer: dict) -> bool:
    abst = is_abstention(answer)
    if q["answer_type"] == "abstain":
        return abst
    if abst:
        return False
    text = answer.get("text") or ""
    if q["answer_type"] == "date":
        g = date.fromisoformat(q["gold"])
        tol = timedelta(days=q["tolerance_days"])
        return any(abs(date.fromisoformat(d) - g) <= tol for d in date_mentions(text)
                   if _valid_iso(d))
    if q["answer_type"] == "duration_days":
        g = int(q["gold"])
        return any(abs(n - g) <= q["tolerance_days"] for n in _numbers(text))
    pred = normalize(text)
    golds = [q["gold"], *q["aliases"]]
    golds += [x for g in golds for x in EXONYMS.get(g, [])]
    return any(normalize(a) and normalize(a) in pred for a in golds)


def _valid_iso(d: str) -> bool:
    try:
        date.fromisoformat(d)
        return True
    except ValueError:
        return False


def score_qa(questions: list[dict], answers: dict[str, dict]) -> dict:
    by_cat: dict[str, list[int]] = {}
    rows = []
    answered = answered_ok = 0
    for q in questions:
        a = answers.get(q["id"])
        ok = bool(a) and correct(q, a)
        by_cat.setdefault(q["category"], [0, 0])
        by_cat[q["category"]][0] += ok
        by_cat[q["category"]][1] += 1
        if a and not is_abstention(a):
            answered += 1
            answered_ok += ok
        rows.append({"id": q["id"], "category": q["category"], "ok": ok,
                     "answer": (a or {}).get("text")})
    total_ok = sum(v[0] for v in by_cat.values())
    abst_q = [q for q in questions if q["answer_type"] == "abstain"]
    false_answers = sum(1 for q in abst_q if q["id"] in answers
                        and not is_abstention(answers[q["id"]]))
    return {
        "accuracy": _rate(total_ok, len(questions)),   # abstention included, never excluded
        "n_questions": len(questions),
        "by_category": {k: {"accuracy": _rate(a, b), "n": b} for k, (a, b) in by_cat.items()},
        "answered_precision": _rate(answered_ok, answered),
        "coverage": _rate(answered, len(questions)),
        "invented_answers": _rate(false_answers, len(abst_q)),
        "rows": rows,
    }


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def score_run(truth: dict, deposits: list[dict], questions: list[dict], run: dict, judge) -> dict:
    snaps = [score_snapshot(truth, deposits, s, judge) for s in run.get("snapshots", [])]
    final = snaps[-1] if snaps else None
    qa = score_qa(questions, run.get("answers", {})) if run.get("answers") else None
    context_only = (run.get("system") or {}).get("qa_mode") == "context"
    if qa and context_only:
        # the "answers" are retrieved contexts: report a hit rate on answerable
        # questions only, and never call it accuracy
        # dates and numbers are almost always somewhere in a large context:
        # only text answers give a meaningful hit rate
        ans = [r for r, q in zip(qa["rows"], questions) if q["answer_type"] == "text"]
        qa = {"context_hit_rate": _rate(sum(r["ok"] for r in ans), len(ans)),
              "n_text_questions": len(ans), "note": "retrieval context, not an answer: "
              "abstention and accuracy not measurable in this mode",
              "upper_bound": True}
    return {
        "system": run.get("system"),
        "judge": judge.name,
        "headline": {
            "invention_rate": final["invention_rate"] if final else None,
            "excerpt_support_rate": final["excerpt_support_rate"] if final else None,
            "fact_recall": final["fact_recall"] if final else None,
            "recall_at_inv_1pct": final["curve"]["recall_at_inv_1pct"] if final else None,
            "qa_accuracy": qa.get("accuracy") if qa else None,
            "invented_answers": qa.get("invented_answers") if qa else None,
            "context_hit_rate": qa.get("context_hit_rate") if qa else None,
            "write_metrics": "measured" if final else run.get("write_unavailable",
                                                             "not measured"),
        },
        "snapshots": snaps,
        "qa": qa,
    }
