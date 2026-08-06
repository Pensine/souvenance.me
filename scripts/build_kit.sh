#!/usr/bin/env bash
# Souvenance — fabrique le repo public ET le ZIP du kit payant.
# L'emballage, pas le secret : le moteur est le même que le repo public MIT ;
# l'acheteur paie le prêt-à-poser et soutient le projet.
#
# Usage : scripts/build_kit.sh <version>   (ex. scripts/build_kit.sh v0.2.0)
# Produit : dist/souvenance-kit-<version>.zip
set -euo pipefail

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERREUR:\033[0m %s\n' "$*"; exit 1; }

VERSION="${1:-}"
[ -n "$VERSION" ] || fail "usage : scripts/build_kit.sh <version>"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORG="Pensine"                # compte GitHub public
BRAND="Souvenance"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

say "Export public (avec grep anti-fuite bloquant)"
"$REPO_DIR/scripts/export_public.sh" "$STAGE/souvenance" >/dev/null

say "Habillage marque (le code garde son nom interne pensine)"
cd "$STAGE/souvenance"
mv marketing/README-public.md README.md
mv marketing/README-public.fr.md README.fr.md
python3 - <<PY
import re
for p in ["README.md", "README.fr.md"]:
    s = open(p, encoding="utf-8").read()
    s = re.sub(r"\bPensine\b", "$BRAND", s)
    open(p, "w", encoding="utf-8").write(s)
for p in ["README.md", "marketing/site/llms.txt",
          "marketing/site/deploy/README.md", "marketing/site/index.html"]:
    s = open(p, encoding="utf-8").read()
    s = s.replace("github.com/YOUR_ORG/pensine", "github.com/$ORG/souvenance.me")
    s = s.replace("YOUR_ORG", "$ORG")
    open(p, "w", encoding="utf-8").write(s)
s = open("README.md", encoding="utf-8").read()
old = "🇫🇷 [Version française](README.fr.md)"
s = s.replace(old, old + " · *engine codename: \`pensine\` "
                   "(paths, config prefix \`PENSINE_*\`, module name)*")
open("README.md", "w", encoding="utf-8").write(s)
PY
cat > LICENSE <<'EOF'
MIT License

Copyright (c) 2026 souvenance.me

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF

say "START-HERE + VERSION (spécifiques au kit)"
cat > START-HERE.md <<'EOF'
# Souvenance kit — start here

Thank you for buying the kit. You now own your memory infrastructure.

**The 15-minute path** (support level 1 is your own AI):

1. Copy this folder to your VPS (or `git clone` the public repo).
2. Open it in Claude Code (or any coding agent) and say:
   > Install Souvenance by following docs/kit-installation.md. Ask me only
   > for the decisions the doc marks as mine.
3. The agent runs `install.sh`, wires HTTPS, and walks you through the
   claude.ai connector and the two iOS shortcuts (step-by-step in
   `docs/kit-installation.md`).
4. Start with the founding interview: say "run interview session 1" in your
   Claude project. That's what seeds the corpus.

**Everything is yours**: PostgreSQL on your server, original files kept
forever, SQL dump = full export, MIT license. If the AI layer ever breaks,
events keep accumulating — pause, never loss.

Questions? The docs are written to be pasted into an AI. That's the design.
EOF
echo "$VERSION" > VERSION

say "Archive"
mkdir -p "$REPO_DIR/dist"
rm -f "$REPO_DIR/dist/souvenance-kit-$VERSION.zip"
( cd "$STAGE" && zip -qr "$REPO_DIR/dist/souvenance-kit-$VERSION.zip" souvenance )
say "Kit : dist/souvenance-kit-$VERSION.zip ($(du -h "$REPO_DIR/dist/souvenance-kit-$VERSION.zip" | cut -f1))"
