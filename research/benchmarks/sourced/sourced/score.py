"""Scoring: write-time integrity, recall/invention curve, question answering.

All definitions are in SPEC.md §4; this file is their executable form.
Denominators are always reported next to rates, and nothing is imputed: a
metric a system cannot be measured on is reported as null with a reason.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .judge import _MONTHS, date_mentions, normalize

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
    from .tasks import asserted
    seen = {f for d in deposits if d["created_at"] < at for f in asserted(d)}
    return [f for f in truth["facts"] if f["id"] in seen]


def score_snapshot(truth: dict, deposits: list[dict], snapshot: dict, judge) -> dict:
    at = snapshot["at"]
    mems = snapshot["memories"]
    workers = getattr(judge, "workers", 1)
    if workers > 1:  # a model judge waits on its endpoint: label in parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            labels = list(ex.map(judge.label, mems))
    else:
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
    attribution = attribution_errors(mems, labels)
    dating = dating_store(truth, deposits, mems, labels, at)
    aliases = alias_metrics(truth, deposits, snapshot, judge, at)
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
        # poison layer: false claims from sources with no authority over the
        # owner, written as memories (None when the set has no poison layer)
        **poison_store(truth, trap_hits, at),
        "excerpt_support_rate": _rate(len(cit_ok), n),   # over ALL memories: no citation = no support
        "citing_memories": len(cited),
        "fact_recall": _rate(len(covered), len(gold)),
        "omission_rate": _rate(len(gold) - len(covered), len(gold)),
        "recall_by_kind": {k: _rate(a, b) for k, (a, b) in sorted(per_kind.items())},
        "stale_as_current": (_rate(len(stale), len(superseded)) if exposes_currency and superseded
                             else None),
        "stale_reason": None if exposes_currency else "system does not expose currency",
        **attribution,
        **dating,
        **aliases,
        "curve": curve(mems, labels, gold_ids),
        "labels": labels,
    }


def poison_store(truth: dict, trap_hits: list[str], at: str) -> dict:
    poison = [t for t in truth["traps"] if t["kind"] == "poison" and t["day"] < at[:10]]
    if not poison:
        return {"poison_rate": None, "poison_hits": []}
    hit = [t for t in poison if t["id"] in trap_hits]
    return {"poison_rate": _rate(len(hit), len(poison)),
            "poison_hits": [{"id": t["id"], "channel": t["channel"]} for t in hit]}


def attribution_errors(mems: list[dict], labels: list[dict]) -> dict:
    """Attribution error rate (SPEC section 4.1): among memories that state the
    value of a gold fact AND declare whom they are about (`subject`), the
    share whose subject is not the fact's subject. A system that declares no
    subject is not measurable: the rate is null with a reason, never 0."""
    with_subject = [i for i, m in enumerate(mems) if (m.get("subject") or "").strip()]
    measurable = [i for i in with_subject if labels[i].get("subject_ok") is not None]
    wrong = [i for i in measurable if labels[i]["subject_ok"] is False]
    reason = None
    if not with_subject:
        reason = "system does not declare memory subjects"
    elif not measurable:
        reason = "no memory with a subject states a gold fact"
    return {"attribution_error_rate": _rate(len(wrong), len(measurable)),
            "attribution_measurable": len(measurable),
            "attribution_wrong": [{"content": mems[i]["content"], "subject": mems[i]["subject"]}
                                  for i in wrong][:50],
            "attribution_reason": reason}


def alias_metrics(truth: dict, deposits: list[dict], snapshot: dict, judge, at: str) -> dict:
    """Identity coverage (SPEC section 4.1). True identities: each identity-
    layer person (role and name written together once: `written_together`)
    and each coverage `converging` person (never written together), once the
    deposits that make the identity knowable precede the snapshot. A link
    is correct when its alias and its name designate the same person.
      alias_recall     true identities linked / true identities (also by kind
                       and by the tier of the link that covers them);
      alias_precision  correct links / all links (false links listed).
    Null with a reason when the system exposes no identity links."""
    if "aliases" not in snapshot:
        return {"alias_recall": None, "alias_precision": None, "alias_detail": None,
                "alias_reason": snapshot.get("aliases_unavailable")
                or "system does not expose identity links"}
    before = [d for d in deposits if d["created_at"] < at]
    alias_deps = {pid for d in before for pid, *_ in d["meta"].get("alias_spans", [])}
    truth_ids = {x["person"]: "written_together" for x in truth.get("identity", [])
                 if x["person"] in alias_deps}
    for x in truth.get("coverage", []):
        days = [m["day"] for m in x["mentions"]]
        if x["same"] and max(days) < at[:10]:
            truth_ids[x["role_person"]] = "converging"
    links = snapshot["aliases"]
    mapped = [(judge.subject_of(a["alias"]), judge.subject_of(a["name"]), a) for a in links]
    good = [(p, a) for p, q, a in mapped if p is not None and p == q]
    false = [a for p, q, a in mapped if p is None or p != q]
    linked: dict[str, set[str]] = {}
    for p, a in good:
        if p in truth_ids:
            linked.setdefault(p, set()).add(a.get("tier") or "")
    by_kind = {}
    for kind in ("written_together", "converging"):
        ids = [p for p, k in truth_ids.items() if k == kind]
        by_kind[kind] = _rate(sum(p in linked for p in ids), len(ids))
    by_tier = {t: _rate(sum(t in linked.get(p, set()) for p in truth_ids), len(truth_ids))
               for t in ("proven", "inferred")}
    return {"alias_recall": _rate(len(linked), len(truth_ids)),
            "alias_precision": _rate(len(good), len(links)),
            "alias_detail": {"true_identities": len(truth_ids), "links": len(links),
                             "false_links": false[:50], "recall_by_kind": by_kind,
                             "recall_by_tier": by_tier},
            "alias_reason": None}


def dating_store(truth: dict, deposits: list[dict], mems: list[dict], labels: list[dict],
                 at: str) -> dict:
    """Bounded dating in the store (SPEC section 4.1): for each bracketed
    gold fact whose two deposits precede the snapshot, the event bounds the
    memories stating it expose. Per fact: 'justified' (both bounds, inside
    the gold interval or equal to it), 'invented_precision' (an exact date:
    earliest == latest), 'loose' (one bound, or wider), 'not_exposed'.
    Null with a reason when the system exposes no event bounds at all."""
    exposes = any(m.get("event_earliest") or m.get("event_latest") for m in mems)
    gold = {x["fact"]: x for x in truth.get("dating", [])
            if x["already_day"] < at[:10]}
    stated: dict[str, list[dict]] = {}
    for m, lab in zip(mems, labels):
        for fid in lab.get("stated") or []:
            if fid in gold:
                stated.setdefault(fid, []).append(m)
    out = {"justified": 0, "invented_precision": 0, "loose": 0, "not_exposed": 0}
    for fid, x in gold.items():
        bounds = [(m.get("event_earliest"), m.get("event_latest")) for m in stated.get(fid, [])
                  if m.get("event_earliest") or m.get("event_latest")]
        if not bounds:
            out["not_exposed"] += 1
        elif any(lo and lo == hi for lo, hi in bounds):
            out["invented_precision"] += 1
        elif all(lo and hi and x["not_yet_day"] <= lo <= hi <= x["already_day"]
                 for lo, hi in bounds):
            out["justified"] += 1
        else:
            out["loose"] += 1
    exposed = len(gold) - out["not_exposed"]
    return {"store_dating": {"facts": len(gold), **out} if exposes else None,
            "store_invented_precision_rate": _rate(out["invented_precision"], exposed)
            if exposes else None,
            "store_dating_reason": None if exposes else "system exposes no event bounds"}


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


def answer_dates(text: str) -> list[date]:
    """Distinct dates in an answer, sorted. Beyond `date_mentions`, a day
    written without its year borrows the next year written ("between 3
    February and 9 March 2025"), and "3 and 9 February 2025" gives two."""
    t = normalize(text)
    mon = "|".join(_MONTHS)
    found = {date.fromisoformat(d) for d in date_mentions(text) if _valid_iso(d)}
    for d1, d2, m_, y_ in re.findall(rf"\b(\d{{1,2}}) (?:and|to|-) (\d{{1,2}}) ({mon}) (\d{{4}})", t):
        for d_ in (d1, d2):
            if _valid_iso(iso := f"{y_}-{_MONTHS.index(m_) + 1:02d}-{int(d_):02d}"):
                found.add(date.fromisoformat(iso))
    pending = []
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? ({mon})(?: (\d{{4}}))?", t):
        pending.append((int(m[1]), _MONTHS.index(m[2]) + 1))
        if m[3]:
            for d_, mo in pending:
                if _valid_iso(iso := f"{m[3]}-{mo:02d}-{d_:02d}"):
                    found.add(date.fromisoformat(iso))
            pending = []
    return sorted(found)


def interval_verdict(q: dict, answer: dict | None) -> str:
    """bounded_date questions (SPEC section 4.3). 'correct': the answer gives
    an interval that lies within the gold interval or equals it (with
    `tolerance_days` on each side); 'invented_precision': it gives a single
    exact date, which the evidence never supports; 'abstained'; 'wrong'
    otherwise (a wider interval, no date, a date outside)."""
    if not answer:
        return "wrong"
    if is_abstention(answer):
        return "abstained"
    lo_g, hi_g = (date.fromisoformat(x) for x in q["gold"].split("/"))
    tol = timedelta(days=q.get("tolerance_days") or 0)
    ds = answer_dates(answer.get("text") or "")
    if len(ds) == 1:
        return "invented_precision"
    if len(ds) >= 2 and lo_g - tol <= ds[0] and ds[-1] <= hi_g + tol:
        return "correct"
    return "wrong"


def correct(q: dict, answer: dict) -> bool:
    abst = is_abstention(answer)
    if q["answer_type"] == "abstain":
        return abst
    if q["answer_type"] == "interval":
        return interval_verdict(q, answer) == "correct"
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
    # a leading article is not part of the answer: "Harbour footpath" names
    # "the harbour footpath"
    golds = [re.sub(r"^(the|a|an) ", "", normalize(g)) for g in golds]
    return any(g and g in pred for g in golds)


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
    bounded = [q for q in questions if q["answer_type"] == "interval"]
    verdicts = [interval_verdict(q, answers.get(q["id"])) for q in bounded]
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
        # bounded dating: a single date where the deposits only bound one is
        # an invention of its own; abstaining is reported apart, not as wrong
        "invented_precision_rate": _rate(verdicts.count("invented_precision"), len(bounded)),
        "bounded_date": {"n": len(bounded), **{v: verdicts.count(v) for v in
                         ("correct", "invented_precision", "abstained", "wrong")}},
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
            "attribution_error_rate": final["attribution_error_rate"] if final else None,
            "alias_recall": final["alias_recall"] if final else None,
            "alias_precision": final["alias_precision"] if final else None,
            "poison_rate": final.get("poison_rate") if final else None,
            "poison_qa": (qa.get("by_category", {}).get("poison", {}).get("accuracy")
                          if qa else None),
            "qa_accuracy": qa.get("accuracy") if qa else None,
            "invented_answers": qa.get("invented_answers") if qa else None,
            "invented_precision_rate": qa.get("invented_precision_rate") if qa else None,
            "context_hit_rate": qa.get("context_hit_rate") if qa else None,
            "write_metrics": "measured" if final else run.get("write_unavailable",
                                                             "not measured"),
        },
        "snapshots": snaps,
        "qa": qa,
    }
