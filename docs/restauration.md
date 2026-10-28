# Testing a full restore

A backup that has never been restored is a hypothesis. With
`PENSINE_SHRED=1` it is worse: a missing key makes deposits
unreadable for good (see docs/oubli.md). Run this test **before**
turning the flag on, then after every change to the backups.

```bash
scripts/restore_test.sh                 # latest local backups
scripts/restore_test.sh --restic        # from the off-site repository (restic restore latest)
scripts/restore_test.sh --dump F.sql.gz --media DIR --keys cles-YYYY-MM-DD.tar.gz
```

The script never touches the real database. It:

1. starts a **throwaway** database (container `pgvector/pgvector:pg17`, random
   port on 127.0.0.1);
2. loads the latest dump into it, then applies the migrations as the real database
   would;
3. extracts the keys and copies the media into a temporary folder;
4. checks (`scripts/restore_check.py`, counts only):
   - every sealed deposit opens, or belongs to a deliberately
     forgotten scope — otherwise it is **lost**, and the test fails;
   - every referenced media file exists;
   - the log still refuses an update (append-only);
   - the nights' raw candidates open;
5. produces the integrity report on the restored database;
6. destroys the container and the temporary folder.

A non-zero exit code means the restore would lose something.

## Before turning PENSINE_SHRED on for an existing installation

1. Create a **separate** restic repository for the keys (`restic init` to another
   destination, with its own password) and declare it in `.env`:
   `RESTIC_KEYS_REPOSITORY` and `RESTIC_KEYS_PASSWORD` (plus its credentials). Whoever steals the dumps must
   not find the keys next to them. Skip this step and the keys go into the
   dumps repository.
2. Take today's backup (`scripts/backup.sh`) with the new retention.
3. `scripts/restore_test.sh`: it must end with `RESTORE OK`.
4. Turn the flag on, deposit a test memo, run `backup.sh` again, then
   `scripts/restore_test.sh`: the deposit must appear in
   `depots_scelles.lisibles`.
5. Check the off-site copy of the keys: `scripts/restore_test.sh --restic`.

Requirements: docker; restic for `--restic`.
