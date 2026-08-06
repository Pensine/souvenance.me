#!/usr/bin/env bash
# Pensine — préparation de la scission repo public (§11 du document fondateur).
#
# Copie le contenu PUBLIABLE du repo vers un dossier cible, puis vérifie
# qu'aucun motif privé n'a fuité. Le script ne crée PAS de repo git et ne
# pousse rien : il prépare un dossier, c'est tout. La publication reste un
# acte humain (cf. marketing/CHECKLIST-publication.md, non exportée).
#
# Usage : scripts/export_public.sh /chemin/vers/dossier-cible
set -euo pipefail

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERREUR:\033[0m %s\n' "$*"; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"
[ -n "$TARGET" ] || fail "usage : scripts/export_public.sh /chemin/vers/dossier-cible"
if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  fail "la cible ${TARGET} existe et n'est pas vide — choisissez un dossier neuf"
fi
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

# -- Liste blanche : tout le repo SAUF le privé --------------------------------
# Exclusions (ne partent JAMAIS) :
#   - DOCUMENT_FONDATEUR.md            (la vie privée du propriétaire)
#   - persona/* sauf persona/README.md (l'identité narrative)
#   - constitution.yaml                (personnalisée à l'installation)
#   - marketing/CHECKLIST-publication.md, marketing/ANNUAIRES-MCP.md
#   - états locaux : .git, .env, .venv, caches
say "Copie vers ${TARGET} (liste blanche)"
# (ordre important : l'include README passe avant l'exclude persona/*)
rsync -a \
  --exclude='/DOCUMENT_FONDATEUR.md' \
  --exclude='/constitution.yaml' \
  --include='/persona/README.md' \
  --exclude='/persona/*' \
  --exclude='/marketing/CHECKLIST-publication.md' \
  --exclude='/marketing/ANNUAIRES-MCP.md' \
  --exclude='/.git' \
  --exclude='/.claude' \
  --exclude='/.env' \
  --exclude='/.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='/.pytest_cache' \
  --exclude='*.egg-info' \
  "$REPO_DIR/" "$TARGET/"

# -- Grep anti-fuite : le garde-fou, pas une formalité -------------------------
# Un seul motif trouvé dans la copie = échec du script.
# (motifs assemblés par concaténation pour que ce script, lui-même exporté,
#  ne déclenche pas sa propre alarme)
PATTERNS='nico''las|angou''geard|cd''74|mar''ine|dous''sard|fav''erges|mont''agn|nogu''era|coach''leo'
say "Contrôle anti-fuite (motifs : ${PATTERNS})"
LEAKS=$(grep -rniE "$PATTERNS" "$TARGET" || true)
if [ -n "$LEAKS" ]; then
  printf '%s\n' "$LEAKS"
  rm -rf "$TARGET"   # la copie fautive ne survit pas au contrôle
  fail "motifs privés trouvés dans la copie (ci-dessus) — copie détruite : nettoyez la source avant de réessayer"
fi

say "Export propre : ${TARGET}"
say "Rien n'a été poussé nulle part. La suite (repo, licence, publication) est un acte humain."
