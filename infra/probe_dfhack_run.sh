#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -uo pipefail
i="$(find /srv/df-bonsai/state/instances -maxdepth 1 -type d -name ".smoke-df-53.15-*" -printf "%T@ %p\n" | sort -nr | head -1 | cut -d" " -f2-)"
cd "$i" || exit 1
echo "=== root client ==="
DFHACK_PORT=5500 ./dfhack-run help 2>&1; echo "rc=$?"
echo "=== dfbot client ==="
runuser -u dfbot -- env DFHACK_PORT=5500 ./dfhack-run help 2>&1; echo "rc=$?"
echo "=== strace dfbot client ==="
runuser -u dfbot -- strace -f -o /tmp/dfhack-run.strace env DFHACK_PORT=5500 ./dfhack-run help >/tmp/dfhack-run.out 2>&1; echo "rc=$?"
tail -50 /tmp/dfhack-run.strace
cat /tmp/dfhack-run.out
'
