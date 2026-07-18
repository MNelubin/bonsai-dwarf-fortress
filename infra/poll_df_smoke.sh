#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
echo "=== processes ==="
ps -ef | grep -E "[r]sync.*[.]smoke|[d]warfort|[d]fhack|[s]moke_and_promote" || true
echo "=== smoke log ==="
latest="$(find /srv/df-bonsai/logs -maxdepth 1 -type f -name "smoke-df-53.15-steam-23622201_dfhack-53.15-r2-*.log" ! -name "*.game" ! -name "*.rpc" -printf "%T@ %p\n" | sort -nr | head -1 | cut -d" " -f2-)"
if [[ -n "$latest" ]]; then
    echo "$latest"
    tail -100 "$latest"
    [[ -f "$latest.game" ]] && { echo "=== game log ==="; tail -80 "$latest.game"; }
    [[ -f "$latest.rpc" ]] && { echo "=== rpc log ==="; cat "$latest.rpc"; }
fi
echo "=== current ==="
readlink -f /srv/df-bonsai/current 2>/dev/null || true
'
