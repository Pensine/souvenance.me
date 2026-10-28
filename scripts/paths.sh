# Data folders resolved by pensine/config.py (a single rule):
# PENSINE_DATA_DIR, PENSINE_MEDIA_ROOT, PENSINE_GEO_DIR, PENSINE_BACKUP_DIR,
# PENSINE_LOG_DIR, PENSINE_KEYS_DIR, PENSINE_KEYS_BACKUP_DIR. To be sourced from the repo root: . scripts/paths.sh
if [ -n "${PENSINE_PY:-}" ]; then :   # interpreter imposed by the caller
elif [ -x ./.venv/bin/python ]; then PENSINE_PY=./.venv/bin/python; else PENSINE_PY=python3; fi
eval "$(PYTHONPATH=. "$PENSINE_PY" -m pensine.config)"
export PENSINE_DATA_DIR PENSINE_MEDIA_ROOT PENSINE_GEO_DIR PENSINE_BACKUP_DIR PENSINE_LOG_DIR \
  PENSINE_KEYS_DIR PENSINE_KEYS_BACKUP_DIR
