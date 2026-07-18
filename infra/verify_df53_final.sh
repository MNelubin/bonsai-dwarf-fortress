#!/usr/bin/env bash
set -euo pipefail

echo '=== CT status ==='
pct status 123
echo '=== snapshots ==='
pct listsnapshot 123
echo '=== guest release ==='
pct exec 123 -- bash -lc '
set -euo pipefail
release="$(readlink -f /srv/df-bonsai/current)"
echo "current=$release"
jq -c . "$release/DF-BONSAI-RELEASE.json"
grep -E "^\[(SOUND|PRINT_MODE):" "$release/data/init/init.txt"
stat -c "%A %a %n" "$release" "$release/dwarfort" "$release/dfhack"
echo "runtime_processes=$(pgrep -c dwarfort || true)"
echo "external_rpc_listeners:"
ss -H -lnt | awk "\$4 !~ /^(127[.]0[.]0[.]1|\\[::1\\]):/ && \$4 ~ /:5[0-9][0-9][0-9]$/ {print}" || true
echo "readme_active_release:"
grep -A8 "^## Active release" /srv/df-bonsai/README.md
df -h /srv/df-bonsai
'
