#!/usr/bin/env bash
# Installs a local copy of GeoNames to name places without an online service:
# knowing that some coordinates fall in Montpellier must not tell anyone but
# you that you were in Montpellier.
#
# Data: cities and villages of more than 1,000 inhabitants (~10 MB uncompressed),
# CC-BY 4.0 licence — https://www.geonames.org. Safe to rerun: it updates.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
. scripts/paths.sh   # PENSINE_GEO_DIR, otherwise PENSINE_DATA_DIR/geo
DIR="$PENSINE_GEO_DIR"
mkdir -p "$DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL -o "$TMP/cities1000.zip" https://download.geonames.org/export/dump/cities1000.zip
curl -fsSL -o "$TMP/admin1CodesASCII.txt" https://download.geonames.org/export/dump/admin1CodesASCII.txt
python3 -m zipfile -e "$TMP/cities1000.zip" "$TMP"   # without depending on unzip
mv "$TMP/cities1000.txt" "$TMP/admin1CodesASCII.txt" "$DIR/"
echo "GeoNames installed in $DIR ($(wc -l < "$DIR/cities1000.txt") places)."
echo "GeoNames data, CC-BY 4.0 — https://www.geonames.org"
