# Forgetting for real: crypto-shredding

The `events` log is append-only: an SQL trigger refuses every update
and every delete. That is what makes it possible to re-consolidate everything
tomorrow with a better model. But a right to be forgotten that leaves the text
in the log is no such right.

**Principle.** With `PENSINE_SHRED=1`, every new deposit is sealed
(AES-256-GCM) under the key of its **scope**: by default one scope per deposit,
or one scope per subject (`sujet` at deposit time, `forget.py --sujet`). The keys
live in `PENSINE_KEYS_DIR`, outside the database, hence outside SQL dumps.
Forgetting a scope means:

1. purging everything derived from it: memories (and their embeddings), links,
   graph edges, relationship states, entities left orphaned, milestones,
   proposals, the nights' raw candidates, the media file and its transcript;
2. memories that mixed this deposit with others are deleted, and those other
   deposits are queued for consolidation again: the memories will be **recomputed**
   without the forgotten one;
3. destroying the key. The log row stays, intact and unreadable.

```bash
python3 scripts/forget.py --event 1234
```

The flag is **off by default**. When it is off, nothing changes: same
payloads, same hashes. Migration `014_shred.sql` only adds a table
(with no key and no label) and an index.

## Threats covered

- Reading a forgotten deposit back from the live database, or from an SQL dump
  taken **after** or **before** the forgetting, once the key is destroyed everywhere.
- Confirming a guess about a forgotten deposit through its hash: the
  deduplication hash of a sealed deposit is an HMAC under the scope key, meaningless without it.
- Guessing a forgotten subject from its name: a subject scope's identifier is
  a digest; the audit only keeps counts, never a reason.

## What is NOT covered

- **Deposits made before** the flag was turned on: they are in plaintext and cannot be
  forgotten this way (the command refuses and says so).
- **Backups already taken.** Memories, transcripts and media are in
  plaintext in the database and in `media/`: a dump or snapshot taken before the
  forgetting contains them until it expires. Hence the bound below.
- **Copies of keys.** A key is only destroyed once its last copy
  has expired (30 days at most, see below). Physical erasure: on an SSD,
  overwriting is not guaranteed; the guarantee comes from managing the copies.
- **What a remote model saw** during a consolidation.
- **Media files themselves are not encrypted**: they are deleted when
  forgotten, but remain in plaintext on disk until then.
- A few fields read directly in SQL (`payload->>'filename'` in the
  cards, `payload->>'vendor'` in the import mirror) are empty for a
  sealed deposit.

## Effect on consolidation and backups

- Consolidation reads deposits in plaintext (`db.unconsolidated_events` opens
  the sealed ones); a forgotten deposit is marked as examined and never comes back.
- Re-consolidating a whole life remains possible for everything that was not forgotten:
  that is the contract, not a regression.

## Backups: a forgetting is complete within one year at most

`scripts/backup.sh` applies two separate schedules.

**The database and media** — local dumps for 30 days; off-site (restic),
14 daily, 3 months of weekly, **12 months of monthly, never more**.
Something forgotten today disappears from the last backup that contained it
within one year at the latest. Durations are counted from the latest
snapshot: if backups stop, nothing is deleted.

**The keys** (only with `PENSINE_SHRED=1`) — a daily archive in
`PENSINE_KEYS_BACKUP_DIR`, outside `PENSINE_BACKUP_DIR`; off-site, a
restic snapshot tagged `pensine-cles`, in a separate repository if
`RESTIC_KEYS_REPOSITORY` is set (whoever steals the dumps must not find
the keys next to them). Retention: **30 days, with the most recent copy always
kept**. A key destroyed by a forgetting therefore no longer exists anywhere after
30 days.

> **A key lost without a copy means the deposits in its scope are lost for
> good.** Nobody can read them again: not you, not a better model
> tomorrow, not the author of this software. The encryption that makes forgetting real
> makes loss real too. Keep the key backup off the
> machine, and check a full restore (`scripts/restore_test.sh`)
> before turning the flag on.

With the flag off, `backup.sh` touches no key: only the off-site
retention changes for existing installations.
