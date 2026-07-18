#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -s <<'GUEST'
set -euo pipefail
release=/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2
config="$release/data/init/init.txt"

test -f "$release/DF-BONSAI-RELEASE.json"
chmod u+w "$release/data/init" "$config"
sed -i \
    -e 's/\r$//' \
    -e 's/^\[SOUND:YES\]$/[SOUND:NO]/' \
    -e 's/^\[PRINT_MODE:AUTO\]$/[PRINT_MODE:TEXT]/' \
    "$config"
chmod a-w "$config" "$release/data/init"

grep -E '^\[(SOUND|PRINT_MODE):' "$config"
GUEST
