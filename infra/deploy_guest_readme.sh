#!/usr/bin/env bash
set -euo pipefail

source_file=/root/df-bonsai-README.md
trap 'rm -f -- "$source_file"' EXIT
pct push 123 "$source_file" /srv/df-bonsai/README.md --perms 0644
pct exec 123 -- bash -lc '
set -euo pipefail
df-bonsai-status
echo "=== README ==="
sed -n "1,160p" /srv/df-bonsai/README.md
'
