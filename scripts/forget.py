#!/usr/bin/env python3
"""Truly forget: purges a scope's projections, then destroys its key.

  forget.py --event 1234          # this deposit's scope (by default, this deposit alone)
  forget.py --sujet "santé"       # every deposit made under this subject
  forget.py --scope depot_ab12…   # a scope by its identifier

Requires PENSINE_SHRED=1 at deposit time: an earlier, plaintext deposit
cannot be forgotten this way (the command says so and touches nothing).
Irreversible: asks for confirmation, unless --oui. To be followed by a
rotation of the backups (see the design note, docs/oubli.md).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db, shred  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--event", type=int)
    g.add_argument("--sujet")
    g.add_argument("--scope")
    p.add_argument("--oui", action="store_true", help="do not ask for confirmation")
    args = p.parse_args()

    scope = shred.subject_scope(args.sujet) if args.sujet else args.scope
    if not args.oui:
        cible = f"deposit {args.event}" if args.event else "this scope"
        if input(f"Forget {cible} and everything derived from it? "
                 "This is irreversible. Type \"forget\": ").strip() not in ("forget", "oublier"):
            print("Nothing was touched.")
            return
    with db.connection() as conn:
        try:
            out = shred.forget(conn, scope=scope, event_id=args.event)
        except shred.ShredError as exc:
            conn.rollback()
            sys.exit(str(exc))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
