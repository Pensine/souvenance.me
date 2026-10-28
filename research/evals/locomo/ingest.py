#!/usr/bin/env python3
"""LoCoMo ingestion → event log, one throwaway database per conversation.

1 event = 1 dated session, payload {"transcript": …} — the `messages` key
would trigger consolidation's _slim compressor (4,000-character budget);
with `transcript`, the full text goes into the prompt.

Usage: ingest.py --conv 1   |   ingest.py --all
"""

import argparse

import common


def reset(conv: int) -> None:
    """Drop the conversation's database: a run starts again from a blank page.

    Needed because `recall` and consolidation leave traces
    (marks, reinforced links, memories) — without a reset, two successive runs
    do not measure the same thing, and a run interrupted halfway keeps
    the memories already written.
    """
    import psycopg

    name = f"locomo_c{conv}"
    with psycopg.connect(common.db_url(conv, "locomo"), autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    print(f"conv {conv}: database {name} dropped")


def ingest(conv: int, data: list[dict]) -> None:
    common.ensure_db(conv)
    common.use_conv(conv)
    from pensine import db

    sample = data[conv - 1]
    a, b = common.speakers(sample)
    written = skipped = 0
    with db.connection() as conn:
        for n, dt, turns in common.sessions(sample):
            payload = {
                "benchmark": "locomo",
                "sample_id": sample["sample_id"],
                "session": n,
                "speakers": [a, b],
                "transcript": common.session_transcript(turns),
            }
            if db.append_event(conn, source="locomo", kind="session",
                               occurred_at=dt, payload=payload):
                written += 1
            else:
                skipped += 1  # already ingested (hash dedup) — safe to re-run
        conn.commit()
    print(f"conv {conv} ({sample['sample_id']}, {a} & {b}): "
          f"{written} sessions ingested, {skipped} already present")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--conv", type=int, choices=range(1, 11))
    g.add_argument("--all", action="store_true")
    ap.add_argument("--reset", action="store_true",
                    help="drop the database before ingesting (blank page)")
    args = ap.parse_args()

    data = common.load_dataset()
    for conv in (range(1, 11) if args.all else [args.conv]):
        if args.reset:
            reset(conv)
        ingest(conv, data)
        if args.reset:
            (common.RESULTS / f"conv{conv}.jsonl").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
