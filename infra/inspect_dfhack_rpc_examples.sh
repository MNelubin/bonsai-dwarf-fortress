#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
p=/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2
grep -R -n -m40 -E "dfhack-run|RPC server|remote.*server" "$p/hack/docs/docs" 2>/dev/null | head -100 || true
echo "=== init scripts ==="
find "$p" -maxdepth 3 -type f \( -name "*init*" -o -name "*.example" \) -printf "%P\n" | sort | head -100
'
