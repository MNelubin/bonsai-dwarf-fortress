#!/usr/bin/env bash
set -euo pipefail

ctid=123
snapshot='df53-dfhack5315r2-20260718'
was_running=0

if pct status "$ctid" | grep -q 'status: running'; then
    was_running=1
fi

cleanup() {
    rc=$?
    if [[ $was_running -eq 1 ]] && ! pct status "$ctid" | grep -q 'status: running'; then
        pct start "$ctid" || true
    fi
    exit "$rc"
}
trap cleanup EXIT

if pct listsnapshot "$ctid" | awk '{print $2}' | grep -Fxq "$snapshot"; then
    echo "Snapshot already exists: $snapshot"
else
    if [[ $was_running -eq 1 ]]; then
        pct shutdown "$ctid" --timeout 90
    fi
    pct snapshot "$ctid" "$snapshot" \
        --description 'Validated headless Dwarf Fortress 53.15 + DFHack 53.15-r2; current symlink promoted'
    echo "Created snapshot: $snapshot"
fi

if [[ $was_running -eq 1 ]]; then
    pct start "$ctid"
    for _ in $(seq 1 30); do
        pct exec "$ctid" -- true >/dev/null 2>&1 && break
        sleep 1
    done
fi

pct status "$ctid"
pct listsnapshot "$ctid"
pct exec "$ctid" -- bash -lc '
set -euo pipefail
readlink -f /srv/df-bonsai/current
cat /srv/df-bonsai/current/DF-BONSAI-RELEASE.json
pgrep -a dwarfort || true
'

trap - EXIT
