#!/usr/bin/env bash
# Sauvegarde Pensine — formats éternels, lisibles dans 30 ans sans le kit.
# À croner quotidiennement ; copiez ensuite BACKUP_DIR hors du VPS (restic/rclone).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
set -a; . ./.env; set +a

BACKUP_DIR="${PENSINE_BACKUP_DIR:-/var/backups/pensine}"
STAMP=$(date -u +%Y-%m-%d)
mkdir -p "$BACKUP_DIR"

# 1. La base — SQL brut (le log d'events est la source de vérité)
docker compose exec -T db pg_dump -U pensine pensine | gzip \
  > "$BACKUP_DIR/pensine-${STAMP}.sql.gz"

# 2. Les médias — les fichiers originaux, tels quels
rsync -a --delete "$PENSINE_MEDIA_ROOT/" "$BACKUP_DIR/media/"

# 3. Le persona — déjà versionné dans Git (ce repo)

# Rotation : 30 jours de dumps SQL
find "$BACKUP_DIR" -name 'pensine-*.sql.gz' -mtime +30 -delete

# 4. Hors site, chiffré (optionnel) : restic vers B2/S3/SFTP
#    Configurer dans .env : RESTIC_REPOSITORY + RESTIC_PASSWORD (+ clés B2/S3)
if [ -n "${RESTIC_REPOSITORY:-}" ] && command -v restic >/dev/null; then
  restic backup "$BACKUP_DIR" --tag pensine --quiet
  restic forget --tag pensine --keep-daily 14 --keep-weekly 12 \
    --keep-yearly 30 --prune --quiet
  echo "Copie hors site restic OK : $RESTIC_REPOSITORY"
fi

echo "Sauvegarde OK : $BACKUP_DIR (dump ${STAMP} + médias synchronisés)"
