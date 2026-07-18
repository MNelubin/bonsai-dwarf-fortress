#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
i="$(find /srv/df-bonsai/state/instances -maxdepth 1 -type d -name ".smoke-df-53.15-*" -printf "%T@ %p\n" | sort -nr | head -1 | cut -d" " -f2-)"
echo "instance=$i"
ss -lntp | grep -E ":5500([[:space:]]|$)" || true
find "$i" -maxdepth 2 -type f \( -name "*.log" -o -name "stderr*" -o -name "gamelog*" \) -printf "%T@ %p\n" | sort -nr | head -30
for f in "$i/stderr.log" "$i/gamelog.txt" "$i/dfhack.history"; do
    if [[ -f "$f" ]]; then
        echo "=== $f ==="
        tail -100 "$f"
    fi
done
echo "=== dfhack-run binary ==="
file "$i/hack/dfhack-run"
ldd "$i/hack/dfhack-run" | grep -E "not found|=>" || true
'
