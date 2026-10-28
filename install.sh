#!/usr/bin/env bash
# Pensine — VPS installation (Debian/Ubuntu). Idempotent: safe to rerun.
# Level-1 support is your AI: paste this repo into your coding agent and
# say "install" — the README has what it needs; the illustrated
# step-by-step guide ships with the kit.
set -euo pipefail

PENSINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PENSINE_DIR"

WITH_LOCAL=0
for arg in "$@"; do
  case "$arg" in
    --with-local) WITH_LOCAL=1 ;;   # BGE-M3 + WhisperX + Docling + Pillow (lourd)
    *) echo "usage: ./install.sh [--with-local]"; exit 1 ;;
  esac
done

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$*"; exit 1; }

# -- Prerequisites -----------------------------------------------------------------
command -v python3 >/dev/null || fail "python3 required (>= 3.11)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || fail "Python >= 3.11 required (found: $(python3 --version))"
command -v docker >/dev/null || fail "docker required (https://docs.docker.com/engine/install/)"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 required"
command -v openssl >/dev/null || fail "openssl required"
if ! command -v ffmpeg >/dev/null; then
  if [ "$WITH_LOCAL" = 1 ]; then
    fail "ffmpeg required with --with-local (WhisperX decodes audio through ffmpeg): apt install ffmpeg"
  fi
  say "ffmpeg missing — audio/video not processed until it is installed (apt install ffmpeg)"
fi
command -v claude >/dev/null || say "claude CLI missing — install Claude Code (npm i -g @anthropic-ai/claude-code) or use PENSINE_LLM_BACKEND=api"

# -- .env ----------------------------------------------------------------------
# Postgres port on the host: override if 5432 is already taken (another Postgres) —
# e.g. PENSINE_DB_PORT=5433 ./install.sh
DB_PORT="${PENSINE_DB_PORT:-5432}"
if [ ! -f .env ]; then
  say "Generating .env (random secrets)"
  PG_PW=$(openssl rand -hex 24)
  cat > .env <<EOF
POSTGRES_PASSWORD=${PG_PW}
PENSINE_DB_PORT=${DB_PORT}
PENSINE_OWNER_NAME=
PENSINE_DATABASE_URL=postgresql://pensine:${PG_PW}@127.0.0.1:${DB_PORT}/pensine
PENSINE_MEDIA_ROOT=/var/lib/pensine/media
PENSINE_DEPOSIT_TOKEN=$(openssl rand -hex 32)
PENSINE_MEDIA_LINK_SECRET=$(openssl rand -hex 32)
PENSINE_MEDIA_LINK_TTL_S=900
PENSINE_PUBLIC_BASE_URL=
PENSINE_EMBEDDINGS=1
PENSINE_LLM_BACKEND=claude-cli
PENSINE_MCP_TRANSPORT=streamable-http
PENSINE_CALENDAR_ICS_URLS=
PENSINE_WEBAPP_PASSWORD=$(openssl rand -hex 12)
EOF
  chmod 600 .env
  say "→ Edit .env: PENSINE_OWNER_NAME (your first name) and PENSINE_PUBLIC_BASE_URL (your domain)"
else
  say ".env already exists — kept"
fi

# -- Database ----------------------------------------------------------------------
# Port conflict: if the host port is taken by something other than our
# container (e.g. another service's Postgres), stop cleanly.
DB_PORT=$(grep '^PENSINE_DB_PORT=' .env | cut -d= -f2)
DB_PORT="${DB_PORT:-5432}"
if ! docker compose --env-file .env ps db 2>/dev/null | grep -q "127.0.0.1:${DB_PORT}"; then
  if (exec 3<>"/dev/tcp/127.0.0.1/${DB_PORT}") 2>/dev/null; then
    exec 3>&- 3<&- || true
    fail "port ${DB_PORT} is already in use — rerun with PENSINE_DB_PORT=5433 ./install.sh (or edit PENSINE_DB_PORT and PENSINE_DATABASE_URL in .env)"
  fi
fi
say "PostgreSQL + pgvector (docker compose, host port ${DB_PORT})"
docker compose --env-file .env up -d db
say "Waiting for the database…"
for i in $(seq 1 30); do
  docker compose exec -T db pg_isready -U pensine >/dev/null 2>&1 && break
  sleep 1
done
docker compose exec -T db pg_isready -U pensine >/dev/null 2>&1 || fail "the database is not responding"

# -- Python --------------------------------------------------------------------
say "Python environment (.venv)"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
if [ "$WITH_LOCAL" = 1 ]; then
  # On a server without a GPU, torch/torchvision/torchaudio must come from the
  # same CPU index — mixing PyPI/CPU breaks transformers at import
  # ("operator torchvision::nms does not exist").
  if ! command -v nvidia-smi >/dev/null; then
    say "PyTorch CPU (dedicated index — avoids useless, mismatched CUDA builds)"
    # Generation 2.8: the last one where torchaudio keeps the AudioMetaData API
    # required by pyannote 3.x and therefore WhisperX. Consistent trio, same index.
    ./.venv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu \
      "torch==2.8.*" "torchvision==0.23.*" "torchaudio==2.8.*"
  fi
  ./.venv/bin/pip install -q -e ".[local,embeddings,dev]"
else
  ./.venv/bin/pip install -q -e ".[dev]"
  say "(local components not installed: rerun with --with-local for WhisperX/Docling/BGE-M3)"
fi

# -- Migrations ----------------------------------------------------------------
say "Schema migrations"
set -a; . ./.env; set +a
./.venv/bin/python scripts/migrate.py 2>/dev/null || python3 scripts/migrate.py

# -- Data folders -------------------------------------------------------
# Media, GeoNames, backups, cron logs: resolved by
# pensine/config.py (explicit variables, otherwise PENSINE_DATA_DIR/…), created
# and handed over to the user who will run the services and cron.
. scripts/paths.sh
for d in "$PENSINE_MEDIA_ROOT" "$PENSINE_GEO_DIR" "$PENSINE_BACKUP_DIR" "$PENSINE_LOG_DIR"; do
  say "Folder: ${d}"
  if mkdir -p "$d" 2>/dev/null && [ -w "$d" ]; then :; else
    sudo mkdir -p "$d" && sudo chown "$(whoami)" "$d"
  fi
done

# -- Verification --------------------------------------------------------------
say "Verification (unit tests + server load)"
set -a; . ./.env; set +a
./.venv/bin/python -m pytest tests/ -q
./.venv/bin/python - <<'EOF'
import asyncio
from pensine.mcp_server import mcp
from pensine.api import app
tools = asyncio.run(mcp.list_tools())
assert {t.name for t in tools} >= {"daily_log", "recall", "get_persona", "curate", "log"}
print("MCP server: OK —", len(tools), "tools")
EOF

# -- Services ------------------------------------------------------------------
if command -v systemctl >/dev/null; then
  say "systemd units (deploy/systemd/) — installing"
  for unit in pensine-api pensine-mcp; do
    sed "s|__PENSINE_DIR__|${PENSINE_DIR}|g" "deploy/systemd/${unit}.service" \
      | sudo tee "/etc/systemd/system/${unit}.service" >/dev/null
  done
  sudo systemctl daemon-reload
  sudo systemctl enable pensine-api pensine-mcp
  # restart rather than `enable --now`: an already-active service would keep
  # the old code after an update
  sudo systemctl restart pensine-api pensine-mcp
  say "Active services: pensine-api (:8300), pensine-mcp (:8400)"
else
  say "systemd missing — run uvicorn pensine.api:app (:8300) and python -m pensine.mcp_server (:8400) manually"
fi

say "Consolidation cron — add to your crontab (crontab -e):"
sed "s|/opt/pensine|${PENSINE_DIR}|g; s|/usr/bin/python3|${PENSINE_DIR}/.venv/bin/python|g; s|/var/log/pensine|${PENSINE_LOG_DIR}|g" crontab.example

say "Installation complete. Next steps: README §Quick start (reverse proxy, MCP, shortcuts)"
