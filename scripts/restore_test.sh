#!/usr/bin/env bash
# Full restore test, on a DISPOSABLE database — never on the real one.
#
# Replays what would have to be done after losing the machine: a fresh
# database (temporary pgvector container), the latest dump, the media, the
# forgetting keys; then checks that everything can be read back
# (scripts/restore_check.py) and produces the integrity report. Everything is
# destroyed at the end.
#
# Usage:
#   scripts/restore_test.sh                       # latest local backups
#   scripts/restore_test.sh --dump F.sql.gz --media DIR --keys cles-….tar.gz
#   scripts/restore_test.sh --restic              # first `restic restore latest`
#
# Run it BEFORE enabling PENSINE_SHRED=1, then after every backup change.
# A non-zero exit code = a restore would lose something. Prerequisites: docker,
# and restic for --restic.
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -f ./.env ]; then set -a; . ./.env; set +a; fi
. scripts/paths.sh

DUMP="" MEDIA="" KEYS="" FROM_RESTIC=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dump) DUMP="$2"; shift 2 ;;
    --media) MEDIA="$2"; shift 2 ;;
    --keys) KEYS="$2"; shift 2 ;;
    --restic) FROM_RESTIC=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

WORK=$(mktemp -d "${TMPDIR:-/tmp}/pensine-restauration.XXXXXX")
NAME="pensine-restauration-$$"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  case "$WORK" in */pensine-restauration.*) rm -rf -- "$WORK" ;; esac
}
trap cleanup EXIT

if [ "$FROM_RESTIC" = 1 ]; then
  restic restore latest --tag pensine --target "$WORK/restic" --quiet
  BK=$(find "$WORK/restic" -type d -name "$(basename "$PENSINE_BACKUP_DIR")" | head -1)
  DUMP=${DUMP:-$(ls -1t "$BK"/pensine-*.sql.gz | head -1)}
  MEDIA=${MEDIA:-$BK/media}
  if [ "${PENSINE_SHRED:-0}" = "1" ]; then
    RESTIC_REPOSITORY="${RESTIC_KEYS_REPOSITORY:-$RESTIC_REPOSITORY}" \
      RESTIC_PASSWORD="${RESTIC_KEYS_PASSWORD:-$RESTIC_PASSWORD}" \
      restic restore latest --tag pensine-cles --target "$WORK/restic-cles" --quiet
    KEYS=${KEYS:-$(find "$WORK/restic-cles" -name 'cles-*.tar.gz' | sort | tail -1)}
  fi
fi
DUMP=${DUMP:-$(ls -1t "$PENSINE_BACKUP_DIR"/pensine-*.sql.gz 2>/dev/null | head -1)}
MEDIA=${MEDIA:-$PENSINE_BACKUP_DIR/media}
if [ -z "$KEYS" ] && [ "${PENSINE_SHRED:-0}" = "1" ]; then
  KEYS=$(ls -1t "$PENSINE_KEYS_BACKUP_DIR"/cles-*.tar.gz 2>/dev/null | head -1 || true)
fi
[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "no dump found" >&2; exit 1; }
echo "dump  : $DUMP"
echo "media : $MEDIA"
echo "keys  : ${KEYS:-(none — flag off or no key backup)}"

mkdir -p "$WORK/keys" "$WORK/media"
if [ -n "$KEYS" ]; then tar -C "$WORK/keys" -xzf "$KEYS"; fi
if [ -d "$MEDIA" ]; then cp -R "$MEDIA/." "$WORK/media/"; fi

# a fresh database, like the compose one, on a free loopback port
docker run -d --name "$NAME" -e POSTGRES_USER=pensine -e POSTGRES_PASSWORD=restauration \
  -e POSTGRES_DB=pensine -p 127.0.0.1::5432 pgvector/pgvector:pg17 >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -U pensine -d pensine >/dev/null 2>&1 && break; sleep 1
done
sleep 2
PORT=$(docker port "$NAME" 5432/tcp | head -1 | sed 's/.*://')
URL="postgresql://pensine:restauration@127.0.0.1:${PORT}/pensine"

gunzip -c "$DUMP" | docker exec -i "$NAME" psql -q -v ON_ERROR_STOP=1 -U pensine -d pensine \
  >/dev/null
# an old backup is brought up to date the way the real database would be
PENSINE_DATABASE_URL="$URL" "$PENSINE_PY" scripts/migrate.py

STATUS=0
PENSINE_DATABASE_URL="$URL" PENSINE_KEYS_DIR="$WORK/keys" PENSINE_MEDIA_ROOT="$WORK/media" \
  "$PENSINE_PY" scripts/restore_check.py || STATUS=$?
PENSINE_DATABASE_URL="$URL" PENSINE_KEYS_DIR="$WORK/keys" PENSINE_MEDIA_ROOT="$WORK/media" \
  "$PENSINE_PY" scripts/integrity_report.py --out "$WORK/rapport" >/dev/null \
  && echo "integrity report: produced on the restored database"

if [ "$STATUS" = 0 ]; then echo "RESTORE OK"; else echo "RESTORE FAILED" >&2; fi
exit "$STATUS"
