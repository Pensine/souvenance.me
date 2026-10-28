#!/usr/bin/env python3
"""Consolidation + question answering on one LoCoMo conversation.

Two phases, both re-runnable (automatic resume after an interruption):
  1. consolidation in chronological batches — each batch simulates a night
     cycle dated just after its events (frozen clock); we deliberately skip
     forgetting_decay / links.decay / gist (their SQL `now()` would
     immediately wear down a corpus dated in the past);
  2. QA — each question goes through recall(), then the LLM backend answers
     with that context alone. Results as JSONL in results/.

Usage: run.py --conv 1 [--batch 6] [--depth source|summary]
               [--consolidate-only | --qa-only] [--max-batches N] [--limit N]
"""

import argparse
import json
import sys
from datetime import timedelta

import common

ANSWER_SYSTEM = (
    "You answer questions about past conversations between {a} and {b}, "
    "using ONLY the memory context provided (JSON from a memory engine). "
    "Reply with the shortest possible answer: a few words, a name, or a date. "
    "Write dates as '8 May 2023'. Do not explain. "
    "If the context does not contain the answer, reply exactly: No information"
)


def consolidate_phase(conv: int, batch: int, max_batches: int | None) -> None:
    import nightly
    from pensine import db, llm
    from pensine.governor import Governor

    governor = Governor()
    done_batches = total = 0
    with db.connection() as conn:
        while max_batches is None or done_batches < max_batches:
            events = db.unconsolidated_events(conn, limit=batch)
            if not events:
                print(f"conv {conv}: consolidation up to date ({total} memories this run)")
                return
            # The "night" after the batch's last event: {{TODAY}} and the
            # valid_from fallback fall within the corpus's time, not in 2026.
            common.freeze_time(max(e["occurred_at"] for e in events)
                               + timedelta(hours=8))
            try:
                r = nightly.consolidate(conn, governor, events)
            except llm.LLMUnavailable as exc:
                conn.commit()
                sys.exit(f"LLM unavailable ({exc}) — run again, resuming is "
                         "automatic (consolidated batches are marked).")
            conn.commit()
            done_batches += 1
            total += r["memories_written"]
            print(f"  batch {done_batches}: {len(events)} sessions → "
                  f"{r['memories_written']} memories, "
                  f"{r.get('relations_added', 0)} edges")
    print(f"conv {conv}: stopped at --max-batches={max_batches} ({total} memories)")


def qa_phase(conv: int, depth: str, limit: int | None) -> None:
    data = common.load_dataset()
    sample = data[conv - 1]
    a, b = common.speakers(sample)

    # The evaluation's "present": the day after the last session.
    corpus_end = max(dt for _, dt, _ in common.sessions(sample))
    common.freeze_time(corpus_end + timedelta(days=1))

    from pensine import llm
    from pensine.mcp_server import recall

    common.RESULTS.mkdir(exist_ok=True)
    out_path = common.RESULTS / f"conv{conv}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(line)["idx"]
                for line in out_path.read_text(encoding="utf-8").splitlines() if line}

    questions = sample["qa"][:limit] if limit else sample["qa"]
    system = ANSWER_SYSTEM.format(a=a, b=b)
    with out_path.open("a", encoding="utf-8") as f:
        for idx, q in enumerate(questions):
            if idx in done:
                continue
            context = recall(q["question"], depth=depth)
            try:
                prediction = llm.complete(
                    f"Memory context:\n{context}\n\nQuestion: {q['question']}",
                    system=system)
            except llm.LLMUnavailable as exc:
                sys.exit(f"LLM unavailable ({exc}) — run again, the {len(done)} "
                         "answers already written are kept.")
            f.write(json.dumps({
                "idx": idx,
                "conv": conv,
                "category": q["category"],
                "question": q["question"],
                "gold": q.get("answer", q.get("adversarial_answer")),
                "prediction": prediction.strip(),
                "evidence": q.get("evidence"),
                "depth": depth,
            }, ensure_ascii=False, default=str) + "\n")
            f.flush()
            done.add(idx)
            if len(done) % 20 == 0:
                print(f"  {len(done)}/{len(questions)} questions")
    print(f"conv {conv}: {len(done)} answers in {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conv", type=int, required=True, choices=range(1, 11))
    ap.add_argument("--batch", type=int, default=6,
                    help="sessions per consolidation cycle (default 6)")
    ap.add_argument("--depth", default="source", choices=["summary", "source"],
                    help="source: recall also returns the events (ISO dates) — "
                         "needed for absolute temporal questions")
    ap.add_argument("--consolidate-only", action="store_true")
    ap.add_argument("--qa-only", action="store_true")
    ap.add_argument("--max-batches", type=int, default=None,
                    help="smoke test: stop after N cycles")
    ap.add_argument("--limit", type=int, default=None,
                    help="smoke test: only ask the first N questions")
    args = ap.parse_args()

    common.use_conv(args.conv)
    common.check_backend()
    if not args.qa_only:
        consolidate_phase(args.conv, args.batch, args.max_batches)
    if not args.consolidate_only:
        qa_phase(args.conv, args.depth, args.limit)


if __name__ == "__main__":
    main()
