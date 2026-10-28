#!/usr/bin/env bash
# Pensine backup — eternal formats, readable in 30 years without the kit.
# Run it daily from cron; then copy BACKUP_DIR off the machine (restic/rclone).
set -euo pipefail
# A backup is the entire memory: nobody but the folder's owner should be able
# to read it, even on a shared machine.
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -f ./.env ]; then set -a; . ./.env; set +a; fi
. scripts/paths.sh

BACKUP_DIR="$PENSINE_BACKUP_DIR"
STAMP=$(date -u +%Y-%m-%d)
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# 1. The database — raw SQL (the event log is the source of truth).
# From the host: through the db container. From a container (full Docker
# install, no docker client): pg_dump directly against the database.
if command -v docker >/dev/null && [ -n "$(docker compose ps -q db 2>/dev/null)" ]; then
  docker compose exec -T db pg_dump -U pensine pensine | gzip \
    > "$BACKUP_DIR/pensine-${STAMP}.sql.gz"
else
  pg_dump "$PENSINE_DATABASE_URL" | gzip > "$BACKUP_DIR/pensine-${STAMP}.sql.gz"
fi

# 2. The media — the original files, as they are
mkdir -p "$PENSINE_MEDIA_ROOT"
rsync -a --delete "$PENSINE_MEDIA_ROOT/" "$BACKUP_DIR/media/"

# 3. The persona — already versioned in Git (this repo)

# Rotation: 30 days of SQL dumps
find "$BACKUP_DIR" -name 'pensine-*.sql.gz' -mtime +30 -delete

# 4. The forgetting keys (PENSINE_SHRED=1 only) — kept apart, and briefly.
#    A key lost without a copy = the deposits in its scope unreadable forever:
#    so we always keep a recent copy. But a copy kept for long would defeat
#    forgetting: 30 days, no more (docs/oubli.md).
if [ "${PENSINE_SHRED:-0}" = "1" ] && [ -d "$PENSINE_KEYS_DIR" ]; then
  mkdir -p "$PENSINE_KEYS_BACKUP_DIR"
  chmod 700 "$PENSINE_KEYS_BACKUP_DIR"
  tar -C "$PENSINE_KEYS_DIR" -czf "$PENSINE_KEYS_BACKUP_DIR/cles-${STAMP}.tar.gz.tmp" .
  mv "$PENSINE_KEYS_BACKUP_DIR/cles-${STAMP}.tar.gz.tmp" \
     "$PENSINE_KEYS_BACKUP_DIR/cles-${STAMP}.tar.gz"
  # 30 days, except the most recent one, kept no matter what
  ls -1t "$PENSINE_KEYS_BACKUP_DIR"/cles-*.tar.gz | tail -n +2 \
    | while read -r f; do find "$f" -mtime +30 -delete; done
fi

# 5. Off-site, encrypted (optional): restic to B2/S3/SFTP
#    Configure in .env: RESTIC_REPOSITORY + RESTIC_PASSWORD (+ B2/S3 keys)
#    Retention capped at 12 months: a forgetting (docs/oubli.md) is complete at
#    the latest a year later, when the last snapshot containing it expires.
#    Durations are relative to the latest snapshot: stopping the backups erases nothing.
if [ -n "${RESTIC_REPOSITORY:-}" ] && command -v restic >/dev/null; then
  restic backup "$BACKUP_DIR" --tag pensine --quiet
  restic forget --tag pensine --keep-within-daily 14d --keep-within-weekly 3m \
    --keep-within-monthly 12m --prune --quiet
  if [ "${PENSINE_SHRED:-0}" = "1" ] && [ -d "$PENSINE_KEYS_BACKUP_DIR" ]; then
    # a separate restic repo is advised (RESTIC_KEYS_REPOSITORY): whoever steals
    # the dumps must not find the keys next to them
    RESTIC_REPOSITORY="${RESTIC_KEYS_REPOSITORY:-$RESTIC_REPOSITORY}" \
      RESTIC_PASSWORD="${RESTIC_KEYS_PASSWORD:-$RESTIC_PASSWORD}" \
      restic backup "$PENSINE_KEYS_BACKUP_DIR" --tag pensine-cles --quiet
    RESTIC_REPOSITORY="${RESTIC_KEYS_REPOSITORY:-$RESTIC_REPOSITORY}" \
      RESTIC_PASSWORD="${RESTIC_KEYS_PASSWORD:-$RESTIC_PASSWORD}" \
      restic forget --tag pensine-cles --keep-within 30d --keep-last 1 --prune --quiet
  fi
  echo "Off-site restic copy OK: $RESTIC_REPOSITORY"
fi

echo "Backup OK: $BACKUP_DIR (dump ${STAMP} + media synced)"
