#!/usr/bin/env bash
# Pensine — installation sur VPS (Debian/Ubuntu). Idempotent : relançable.
# Le support de niveau 1 est votre IA : collez ce repo dans votre agent de code et
# dites « installe » — le README contient le nécessaire ; le guide
# pas-à-pas illustré est fourni avec le kit.
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
fail() { printf '\033[1;31mERREUR:\033[0m %s\n' "$*"; exit 1; }

# -- Prérequis -----------------------------------------------------------------
command -v python3 >/dev/null || fail "python3 requis (>= 3.11)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || fail "Python >= 3.11 requis (trouvé : $(python3 --version))"
command -v docker >/dev/null || fail "docker requis (https://docs.docker.com/engine/install/)"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 requis"
command -v openssl >/dev/null || fail "openssl requis"
if ! command -v ffmpeg >/dev/null; then
  if [ "$WITH_LOCAL" = 1 ]; then
    fail "ffmpeg requis avec --with-local (WhisperX décode l'audio par ffmpeg) : apt install ffmpeg"
  fi
  say "ffmpeg absent — audio/vidéos non traités tant qu'il manque (apt install ffmpeg)"
fi
command -v claude >/dev/null || say "claude CLI absent — installez Claude Code (npm i -g @anthropic-ai/claude-code) ou utilisez PENSINE_LLM_BACKEND=api"

# -- .env ----------------------------------------------------------------------
# Port Postgres côté hôte : surchargez si 5432 est déjà pris (autre Postgres) —
# ex. PENSINE_DB_PORT=5433 ./install.sh
DB_PORT="${PENSINE_DB_PORT:-5432}"
if [ ! -f .env ]; then
  say "Génération de .env (secrets aléatoires)"
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
  say "→ Éditez .env : PENSINE_OWNER_NAME (votre prénom) et PENSINE_PUBLIC_BASE_URL (votre domaine)"
else
  say ".env existe déjà — conservé"
fi

# -- Base ----------------------------------------------------------------------
# Conflit de port : si le port hôte est occupé par autre chose que notre
# conteneur (ex. le Postgres d'un autre service), on s'arrête proprement.
DB_PORT=$(grep '^PENSINE_DB_PORT=' .env | cut -d= -f2)
DB_PORT="${DB_PORT:-5432}"
if ! docker compose --env-file .env ps db 2>/dev/null | grep -q "127.0.0.1:${DB_PORT}"; then
  if (exec 3<>"/dev/tcp/127.0.0.1/${DB_PORT}") 2>/dev/null; then
    exec 3>&- 3<&- || true
    fail "le port ${DB_PORT} est déjà occupé — relancez avec PENSINE_DB_PORT=5433 ./install.sh (ou éditez PENSINE_DB_PORT et PENSINE_DATABASE_URL dans .env)"
  fi
fi
say "PostgreSQL + pgvector (docker compose, port hôte ${DB_PORT})"
docker compose --env-file .env up -d db
say "Attente de la base…"
for i in $(seq 1 30); do
  docker compose exec -T db pg_isready -U pensine >/dev/null 2>&1 && break
  sleep 1
done
docker compose exec -T db pg_isready -U pensine >/dev/null 2>&1 || fail "la base ne répond pas"

# -- Python --------------------------------------------------------------------
say "Environnement Python (.venv)"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
if [ "$WITH_LOCAL" = 1 ]; then
  # Sur un serveur sans GPU, torch/torchvision/torchaudio doivent venir du
  # même index CPU — un panachage PyPI/CPU casse transformers à l'import
  # (« operator torchvision::nms does not exist »).
  if ! command -v nvidia-smi >/dev/null; then
    say "PyTorch CPU (index dédié — évite les builds CUDA inutiles et dépareillés)"
    # Génération 2.8 : la dernière dont torchaudio garde l'API AudioMetaData
    # qu'exigent pyannote 3.x et donc WhisperX. Trio cohérent, même index.
    ./.venv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu \
      "torch==2.8.*" "torchvision==0.23.*" "torchaudio==2.8.*"
  fi
  ./.venv/bin/pip install -q -e ".[local,embeddings,dev]"
else
  ./.venv/bin/pip install -q -e ".[dev]"
  say "(briques locales non installées : relancez avec --with-local pour WhisperX/Docling/BGE-M3)"
fi

# -- Migrations ----------------------------------------------------------------
say "Migrations de schéma"
set -a; . ./.env; set +a
./.venv/bin/python scripts/migrate.py 2>/dev/null || python3 scripts/migrate.py

# -- Stockage média ------------------------------------------------------------
MEDIA_ROOT=$(grep '^PENSINE_MEDIA_ROOT=' .env | cut -d= -f2)
say "Stockage média : ${MEDIA_ROOT}"
sudo mkdir -p "$MEDIA_ROOT" && sudo chown "$(whoami)" "$MEDIA_ROOT"

# -- Vérification --------------------------------------------------------------
say "Vérification (tests unitaires + chargement serveur)"
set -a; . ./.env; set +a
./.venv/bin/python -m pytest tests/ -q
./.venv/bin/python - <<'EOF'
import asyncio
from pensine.mcp_server import mcp
from pensine.api import app
tools = asyncio.run(mcp.list_tools())
assert {t.name for t in tools} >= {"daily_log", "recall", "get_persona", "curate", "log"}
print("Serveur MCP : OK —", len(tools), "outils")
EOF

# -- Services ------------------------------------------------------------------
if command -v systemctl >/dev/null; then
  say "Unités systemd (deploy/systemd/) — installation"
  for unit in pensine-api pensine-mcp; do
    sed "s|__PENSINE_DIR__|${PENSINE_DIR}|g" "deploy/systemd/${unit}.service" \
      | sudo tee "/etc/systemd/system/${unit}.service" >/dev/null
  done
  sudo systemctl daemon-reload
  sudo systemctl enable --now pensine-api pensine-mcp
  say "Services actifs : pensine-api (:8300), pensine-mcp (:8400)"
else
  say "systemd absent — lancez manuellement uvicorn pensine.api:app (:8300) et python -m pensine.mcp_server (:8400)"
fi

say "Cron de consolidation — ajoutez à votre crontab (crontab -e) :"
sed "s|/opt/pensine|${PENSINE_DIR}|g; s|/usr/bin/python3|${PENSINE_DIR}/.venv/bin/python|g" crontab.example

say "Installation terminée. Étapes suivantes : README §Quick start (reverse proxy, MCP, raccourcis)"
