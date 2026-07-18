#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
release_id=df-53.15-steam-23622201_dfhack-53.15-r2
echo "=== processes ==="
ps -ef | grep -E "[r]sync|[c]hmod -R|[b]uilding-$release_id" || true
echo "=== log ==="
tail -60 "/srv/df-bonsai/logs/build-$release_id.log" 2>/dev/null || true
echo "=== paths ==="
find /srv/df-bonsai/releases -maxdepth 1 -mindepth 1 -printf "%f\n" | sort
'
