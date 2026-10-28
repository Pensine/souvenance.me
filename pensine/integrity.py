"""Measuring integrity: the memory invents nothing, and proves it.

Three indicators, all computed in code, publishable without revealing
anything about a life (counts, never content):

  A. INVENTION RATE AT WRITE TIME — share of the candidate memories that a
     night of consolidation proposed and that the evidence cascade
     (pensine/evidence.py) rejected or flagged. This is what the model would
     have written without a filter and that could not be verified.
  B. SUPPORT RATE — share of the kept memories whose cited excerpts really
     support the content. Deterministic check first; optional reread by a
     model, disabled by default.
  C. RECALL / INVENTION FRONTIER — the same night replayed under several
     filter severities: what each notch of caution costs in lost memories,
     and what it avoids in kept inventions.

Each proportion carries its sample size N and a 95% Wilson interval:
"0% over 5 nights" is not "0%".

The JSON keys of the report (`taux_invention_ecriture`, `ic95`, `soutenue`…)
and the French stopword list used for stemming are kept as is.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from . import evidence, modality

Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> dict:
    """Proportion k/n and its Wilson interval (good even at k = 0 or small n)."""
    if n <= 0:
        return {"k": k, "n": n, "p": None, "ic95": [None, None]}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": k, "n": n, "p": round(p, 4),
            "ic95": [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]}


# ---------------------------------------------------------------- A. invention

def _night_counts(detail: dict) -> dict:
    """Counts for a night from the logged evidence.verify report.

    Reports predating the instrumentation have neither `candidates` nor
    `issues`: we reconstruct the sample size, and can only count a lower bound
    of the flagged ones (those reread and judged supported are
    indistinguishable from the verified ones)."""
    d = detail or {}
    g = lambda k: int(d.get(k) or 0)  # noqa: E731
    if "issues" in d:
        caught = g("rejetees") - g("non_soutenues") + g("signalees")
        return {"candidates": g("candidates"), "rejetees": g("rejetees"),
                "signalees": g("signalees"), "detectees": caught, "exact": True,
                "issues": d.get("issues") or {}}
    n = g("verifiees") + g("corrigees") + g("partielles") + g("a_verifier") + g("rejetees")
    low = g("rejetees") + g("a_verifier") + g("corrigees") + g("partielles")
    return {"candidates": n, "rejetees": g("rejetees"),
            "signalees": g("a_verifier") + g("corrigees") + g("partielles"),
            "detectees": low, "exact": False, "issues": {}}


def invention_at_write(audit_rows: list[dict]) -> dict:
    """Indicator A over the `evidence` reports of the audit log (one row per night)."""
    nights, issues = [], {}
    tot = {"candidates": 0, "rejetees": 0, "signalees": 0, "detectees": 0}
    exact = True
    for r in audit_rows:
        detail = r.get("detail")
        if isinstance(detail, str):
            detail = json.loads(detail)
        c = _night_counts(detail)
        if not c["candidates"]:
            continue
        exact &= c["exact"]
        for k in tot:
            tot[k] += c[k]
        for k, v in c["issues"].items():
            issues[k] = issues.get(k, 0) + v
        at = r.get("at")
        nights.append({"nuit": at.date().isoformat() if isinstance(at, datetime) else str(at)[:10],
                       "candidates": c["candidates"], "detectees": c["detectees"],
                       "exact": c["exact"]})
    n = tot["candidates"]
    rates = [x["detectees"] / x["candidates"] for x in nights]
    return {
        "definition": "candidates rejected or flagged by the evidence cascade / "
                      "candidates proposed by consolidation",
        "nuits": len(nights), "exact": exact,
        "taux_invention_ecriture": wilson(tot["detectees"], n),
        "taux_rejet": wilson(tot["rejetees"], n),
        "taux_signalement": wilson(tot["signalees"], n),
        "par_nuit": {"min": round(min(rates), 4) if rates else None,
                     "max": round(max(rates), 4) if rates else None},
        "issues": issues, "detail_nuits": nights,
    }


# ------------------------------------------------------------------ B. support

_STOP = {"avec", "dans", "pour", "mais", "sans", "sous", "chez", "vers", "elle", "elles",
         "nous", "vous", "leur", "leurs", "cette", "celle", "celui", "ceux", "comme",
         "plus", "tres", "tout", "tous", "toute", "toutes", "être", "etre", "avoir",
         "fait", "faire", "dont", "quand", "aussi", "encore", "deja", "entre", "apres",
         "avant", "depuis", "pendant", "qu'il", "qu'elle", "that", "this", "with",
         "from", "have", "they", "their", "were", "been", "about", "veut", "souhaite",
         "personne", "utilisateur"}

SEUIL_RECOUVREMENT = 0.34


def _stems(text: str) -> set[str]:
    """Content words, truncated to 5 letters: "reparler", "reparlera" and
    "reparlé" meet without a dictionary."""
    return {w[:5] for w in evidence.normalize(text).replace("'", " ").split()
            if len(w) >= 4 and w not in _STOP and not w.isdigit()}


def support_check(memory: dict, sources: list[dict], owner: str = "") -> dict:
    """Deterministic check of a kept memory against its excerpts.

    S1 excerpts found: each cited excerpt is still in the deposit
       (detects a source that was erased or has since been retranscribed);
    S2 details covered: each number and proper noun of the content appears in
       the cited EXCERPTS — stricter than tier 2, which searches the whole
       deposit (a common word at the start of a sentence is not a proper noun);
    S3 overlap: at least a third of the content's content-words are found in
       the excerpts (a paraphrase passes, an addition does not);
    S4 modality: the excerpt is not conditional, future, hypothetical, a wish,
       a negation, a question, or hearsay about what the memory asserts as
       fact (pensine/modality.py).
    Supported = S1 and S2 and S3 and S4."""
    ev = memory.get("evidence") or {}
    if isinstance(ev, str):
        ev = json.loads(ev)
    cites = [c for c in ev.get("citations") or [] if isinstance(c, str)]
    text = "\n".join(evidence.source_text(e) for e in sources)
    s1 = bool(cites) and bool(text) and all(evidence.quote_found(c, text) for c in cites)
    cited = "\n".join(cites)
    ignore = evidence._dates_ignore(sources, owner)
    missing = evidence.unsupported_details(memory.get("content", ""), cited,
                                           ignore) if cites else []
    content = _stems(memory.get("content", ""))
    overlap = (len(content & _stems(cited)) / len(content)) if content else 1.0
    modes = modality.mismatches(memory.get("content", ""), cites) if cites else []
    s2, s3, s4 = not missing, overlap >= SEUIL_RECOUVREMENT, not modes
    return {"s1_extraits": s1, "s2_details": s2, "s3_recouvrement": s3,
            "s4_modalite": s4, "recouvrement": round(overlap, 3),
            "soutenue": s1 and s2 and s3 and s4, "manquants": missing[:6], "modes": modes}


def _count_modes(checks) -> dict:
    out: dict = {}
    for c in checks:
        for m in c.get("modes") or []:
            out[m] = out.get(m, 0) + 1
    return out


def support_rate(memories: list[dict], sources_by_id: dict[int, dict], owner: str = "",
                 *, ask=None, extract_json=None, max_modele: int = 50) -> dict:
    """Indicator B. `memories`: active memories (with `evidence` and
    `source_event_ids`). Those written before cited evidence existed are
    counted separately: they have nothing to verify, it is not a failure."""
    checked = []
    without = forgotten = 0
    for m in memories:
        ev = m.get("evidence")
        if not ev:
            without += 1
            continue
        srcs = [sources_by_id[i] for i in (m.get("source_event_ids") or []) if i in sources_by_id]
        if not srcs:
            forgotten += 1  # unreadable (forgotten) sources: nothing to check
            continue
        checked.append((m, support_check(m, srcs, owner)))
    n = len(checked)
    out = {
        "definition": "kept memories whose cited excerpts support the content "
                      "(S1 excerpts found ∧ S2 details in the excerpts ∧ "
                      f"S3 overlap ≥ {SEUIL_RECOUVREMENT} ∧ S4 modality kept)",
        "taux_soutien": wilson(sum(c["soutenue"] for _, c in checked), n),
        "s1_extraits": wilson(sum(c["s1_extraits"] for _, c in checked), n),
        "s2_details": wilson(sum(c["s2_details"] for _, c in checked), n),
        "s3_recouvrement": wilson(sum(c["s3_recouvrement"] for _, c in checked), n),
        "s4_modalite": wilson(sum(c["s4_modalite"] for _, c in checked), n),
        "modes_en_defaut": _count_modes(c for _, c in checked),
        "sans_preuve_anterieures": without, "sources_illisibles": forgotten,
        "par_statut": {},
    }
    for m, c in checked:
        st = (m["evidence"] if isinstance(m["evidence"], dict)
              else json.loads(m["evidence"])).get("statut", "?")
        b = out["par_statut"].setdefault(st, [0, 0])
        b[0] += c["soutenue"]
        b[1] += 1
    out["par_statut"] = {k: wilson(*v) for k, v in out["par_statut"].items()}
    if ask and extract_json:
        verdicts = []
        for m, _ in checked[:max_modele]:
            ev = m["evidence"] if isinstance(m["evidence"], dict) else json.loads(m["evidence"])
            v = evidence.relecture(m, ev.get("citations") or [], ask, extract_json)
            if v:
                verdicts.append(v["verdict"])
        out["modele"] = {"relues": len(verdicts),
                         "taux_soutien": wilson(verdicts.count("soutenue"), len(verdicts)),
                         "partielles": verdicts.count("partielle"),
                         "non_soutenues": verdicts.count("non_soutenue")}
    return out


# ---------------------------------------------------------------- C. frontier

def frontier(nights: list[dict], *, owner: str = "", severities=evidence.SEVERITES,
             ask=None, extract_json=None) -> dict:
    """Indicator C. Each night: {"night", "events", "candidates"}; a
    candidate may carry `_verdict` (fidele | approximative | inventee, from an
    external judge: research/evals/frugal/judge.py). With labels, we plot the
    true trade-off — recall of the faithful ones against kept inventions.
    Without labels, kept invention is approximated by the deterministic
    support failure (indicator B) of the kept memories."""
    labelled = any(c.get("_verdict") for n in nights for c in n.get("candidates") or [])
    points = []
    for sev in severities:
        kept_n = total = fid_tot = fid_kept = inv_kept = unsup = 0
        for night in nights:
            cands = [c for c in night.get("candidates") or []
                     if isinstance(c, dict) and c.get("content")]
            for i, c in enumerate(cands):
                c.setdefault("_rang", i)
            kept, _ = evidence.verify(cands, night.get("events") or [], owner=owner,
                                      ask=ask, extract_json=extract_json, severity=sev)
            total += len(cands)
            kept_n += len(kept)
            ranks = {k["_rang"] for k in kept}
            by_id = {e["id"]: e for e in night.get("events") or [] if "id" in e}
            for k in kept:
                srcs = [by_id[i] for i in k.get("source_event_ids") or [] if i in by_id] \
                    or list(by_id.values())
                unsup += not support_check(k, srcs, owner)["soutenue"]
            if labelled:
                for c in cands:
                    v = c.get("_verdict")
                    fid_tot += v == "fidele"
                    if c["_rang"] in ranks:
                        fid_kept += v == "fidele"
                        inv_kept += v == "inventee"
        pt = {"severite": sev, "gardees": wilson(kept_n, total),
              "non_soutenues_gardees": wilson(unsup, kept_n)}
        if labelled:
            pt["rappel_fideles"] = wilson(fid_kept, fid_tot)
            pt["inventions_gardees"] = wilson(inv_kept, kept_n)
        points.append(pt)
    return {"definition": "same night replayed under each filter severity: share of "
                          "candidates kept (recall) against share of the kept ones that are invented",
            "nuits": len(nights), "etiquetee": labelled, "points": points}


def palier2(nights: list[dict], *, owner: str = "") -> dict:
    """Tier 2 alone (numbers and proper nouns absent from the deposit), crossed
    with a judge's verdict: a faithful one flagged is a false alarm (useless
    reread), an invented one flagged is a catch. Independent of the cited
    excerpts, hence applicable to benches predating cited evidence."""
    by = {}
    for night in nights:
        evs = night.get("events") or []
        by_id = {e["id"]: e for e in evs if "id" in e}
        ignore = evidence._dates_ignore(evs, owner)
        for c in night.get("candidates") or []:
            v = c.get("_verdict")
            if not v or not c.get("content"):
                continue
            srcs = [by_id[i] for i in c.get("source_event_ids") or [] if i in by_id] or evs
            text = "\n".join(evidence.source_text(e) for e in srcs)
            b = by.setdefault(v, [0, 0])
            b[0] += bool(evidence.unsupported_details(c["content"], text, ignore))
            b[1] += 1
    return {"definition": "share of candidates flagged by tier 2, by judge verdict",
            "par_verdict": {k: wilson(*v) for k, v in sorted(by.items())}}


def nights_from_bench(dataset: dict, run: dict | None, verdicts: list | None = None) -> list[dict]:
    """Assemble replayable nights from the frugal bench: dataset.json
    (deposits), run.py output (candidates) and, optionally, the list of the
    judge's verdicts for this model (labels, aligned by rank)."""
    events = {b["night"]: b["events"] for b in dataset.get("batches") or []}
    if run is None:  # the reference memories (production), judged as a control
        run = {"results": [{"night": b["night"], "memories": b.get("reference")}
                           for b in dataset.get("batches") or []]}
    labels = {v["night"]: ((v.get("verdict") or {}).get("candidates") or [])
              for v in verdicts or []}
    out = []
    for r in run.get("results") or []:
        if not r.get("memories") or r["night"] not in events:
            continue
        lab = labels.get(r["night"], [])
        cands = [{**m, **({"_verdict": lab[i].get("verdict")} if i < len(lab) else {})}
                 for i, m in enumerate(r["memories"])]
        out.append({"night": r["night"], "events": events[r["night"]], "candidates": cands})
    return out


# ------------------------------------------- C on a real database: the journal

def record_candidates(conn, candidates: list[dict], trace: list[str],
                      events: list[dict]) -> int:
    """Keep a night's raw candidates (before the cascade), for the frontier on
    a real database. Sealed in layers under the key of each of their deposits
    when those are sealed (pensine/shred.py): forgetting a deposit makes them
    unreadable, and forget() purges them. Without a valid source, the
    candidate is sealed under all the night's scopes.

    Never breaks a night: table missing (migration 014 not applied) or
    retention at 0, nothing is written."""
    from . import config, shred
    days = config.CANDIDATES_RETENTION_DAYS
    if days <= 0 or not candidates:
        return 0
    batch = sorted({e["id"] for e in events if "id" in e})
    scopes = {e["id"]: e.get("scope") for e in events if "id" in e}
    try:
        with conn.transaction():  # savepoint: a failure here does not take the night down
            conn.execute("DELETE FROM night_candidates WHERE night_at < now() - %s * INTERVAL '1 day'",
                         (days,))
            for i, c in enumerate(candidates):
                if not isinstance(c, dict):
                    continue
                src = sorted({int(x) for x in c.get("source_event_ids") or []
                              if str(x).isdigit() and int(x) in scopes})
                layer = [scopes[x] for x in (src or batch) if scopes.get(x)]
                payload = shred.seal_layers(c, layer) if layer else c
                conn.execute(
                    "INSERT INTO night_candidates (batch_event_ids, source_event_ids, issue, "
                    "payload) VALUES (%s, %s, %s, %s)",
                    (batch, src, trace[i] if i < len(trace) else None,
                     json.dumps(payload, ensure_ascii=False, default=str)))
    except Exception as exc:  # noqa: BLE001 — measurement must never break sleep
        from . import db
        db.audit(conn, "consolidation", "candidates_journal_skipped",
                 {"error": type(exc).__name__})
        return 0
    return len(candidates)


def nights_from_db(conn) -> list[dict]:
    """Replayable nights from the candidates journal. Forgotten candidates
    (a destroyed key) are ignored; the deposits are reread in clear, as
    consolidation saw them."""
    from . import db, shred
    rows = conn.execute(
        "SELECT night_at, batch_event_ids, payload FROM night_candidates "
        "ORDER BY night_at, id").fetchall()
    nights: dict = {}
    for r in rows:
        c = shred.open_layers(r["payload"])
        if c is None:
            continue
        key = (r["night_at"], tuple(r["batch_event_ids"]))
        nights.setdefault(key, []).append(c)
    out = []
    for (at, batch), cands in nights.items():
        events = []
        for e in db.source_events(conn, list(batch)):
            if e.get("forgotten"):
                continue
            events.append({**e, "media_transcript": e.get("transcript"),
                           "media_description": e.get("description")})
        out.append({"night": at.isoformat() if hasattr(at, "isoformat") else str(at),
                    "events": events, "candidates": cands})
    return out


# ------------------------------------------------------------------- rendering

def _pct(w: dict) -> str:
    if w.get("p") is None:
        return f"— (N = {w['n']})"
    lo, hi = w["ic95"]
    return f"{100 * w['p']:.1f} % [{100 * lo:.1f} – {100 * hi:.1f}] ({w['k']}/{w['n']})"


def render_markdown(report: dict) -> str:
    lines = ["# Integrity report", "",
             f"Generated on {report.get('genere_le', '?')}. Proportions: value, "
             "95% Wilson interval, sample size.", ""]
    a = report.get("invention")
    if a:
        lines += ["## A. Invention rate at write time", "", f"*{a['definition']}.*", "",
                  f"- Nights: **{a['nuits']}**"
                  + ("" if a["exact"] else " (old reports: lower bound)"),
                  f"- Invention detected: **{_pct(a['taux_invention_ecriture'])}**",
                  f"- of which rejected: {_pct(a['taux_rejet'])}",
                  f"- of which flagged (tier 2): {_pct(a['taux_signalement'])}"]
        if a["par_nuit"]["min"] is not None:
            lines.append(f"- Range per night: {100 * a['par_nuit']['min']:.0f} % – "
                         f"{100 * a['par_nuit']['max']:.0f} %")
        if a["issues"]:
            lines.append("- Outcomes: " + ", ".join(f"{k} {v}" for k, v in
                                                   sorted(a["issues"].items())))
        lines.append("")
    b = report.get("soutien")
    if b:
        lines += ["## B. Support rate", "", f"*{b['definition']}.*", "",
                  f"- Supported (deterministic): **{_pct(b['taux_soutien'])}**",
                  f"- S1 excerpts found: {_pct(b['s1_extraits'])}",
                  f"- S2 details in the excerpts: {_pct(b['s2_details'])}",
                  f"- S3 overlap: {_pct(b['s3_recouvrement'])}",
                  f"- S4 modality kept: {_pct(b['s4_modalite'])}"
                  + (" — at fault: " + ", ".join(f"{k} {v}" for k, v in
                                                    sorted(b["modes_en_defaut"].items()))
                     if b.get("modes_en_defaut") else ""),
                  f"- Not measured: {b['sans_preuve_anterieures']} memories predating "
                  f"cited evidence, {b['sources_illisibles']} with forgotten sources"]
        for st, w in sorted(b["par_statut"].items()):
            lines.append(f"  - status `{st}`: {_pct(w)}")
        if b.get("modele"):
            lines.append(f"- Model reread ({b['modele']['relues']} reread): "
                         f"{_pct(b['modele']['taux_soutien'])}")
        lines.append("")
    p2 = report.get("palier2")
    if p2:
        lines += ["## Tier 2 alone, by judge verdict", "", f"*{p2['definition']}.*", "",
                  "| Verdict | Flagged |", "|---|---|"]
        lines += [f"| {k} | {_pct(w)} |" for k, w in p2["par_verdict"].items()]
        lines.append("")
    c = report.get("frontiere")
    if c:
        lines += ["## C. Recall / invention frontier", "", f"*{c['definition']}.*", "",
                  f"{c['nuits']} night(s), "
                  + ("labelled by a judge." if c["etiquetee"] else
                     "no labels: invention is approximated by the support failure."),
                  ""]
        if c["etiquetee"]:
            lines += ["| Severity | Kept | Recall of the faithful | Kept inventions |",
                      "|---|---|---|---|"]
            for p in c["points"]:
                lines.append(f"| {p['severite']} | {_pct(p['gardees'])} | "
                             f"{_pct(p['rappel_fideles'])} | {_pct(p['inventions_gardees'])} |")
        else:
            lines += ["| Severity | Kept | Unsupported among the kept |", "|---|---|---|"]
            for p in c["points"]:
                lines.append(f"| {p['severite']} | {_pct(p['gardees'])} | "
                             f"{_pct(p['non_soutenues_gardees'])} |")
        lines.append("")
    return "\n".join(lines)
