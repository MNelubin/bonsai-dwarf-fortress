#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
p=/srv/df-bonsai/staging/dfhack/53.15-r2/payload
echo "=== dfhack launcher ==="
sed -n "1,180p" "$p/dfhack"
echo "=== dfhack-run launcher ==="
sed -n "1,160p" "$p/dfhack-run"
echo "=== headless docs references ==="
grep -R -n -m20 "DFHACK_HEADLESS" "$p/hack/docs" "$p/hack" 2>/dev/null | head -40 || true
'
