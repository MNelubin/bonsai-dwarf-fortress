#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
stage=/srv/df-bonsai/staging/df-steam
manifest="$stage/steamapps/appmanifest_975370.acf"

echo "Manifest summary:"
grep -E "\"(appid|name|buildid|installdir|StateFlags)\"" "$manifest"

echo "Top-level files:"
find "$stage" -maxdepth 2 -mindepth 1 -printf "%y %p\n" | sort | head -100

echo "Candidate executables:"
find "$stage" -maxdepth 3 -type f -perm /111 -print -exec file {} \;

echo "Version-like files:"
find "$stage" -maxdepth 4 -type f \( -iname "*version*" -o -iname "release*" \) -print | head -50

if [[ -x "$stage/dwarfort" ]]; then
    echo "dwarfort dependencies:"
    ldd "$stage/dwarfort" || true
fi
'
