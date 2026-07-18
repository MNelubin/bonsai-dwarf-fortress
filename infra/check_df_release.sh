#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
release=/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2
ls -ld /srv/df-bonsai/releases "$release"
cat "$release/DF-BONSAI-RELEASE.json"
stat -c "%A %U:%G %n" "$release" "$release/dwarfort" "$release/dfhack" "$release/data/init/init.txt"
grep -E "^\[(SOUND|PRINT_MODE):" "$release/data/init/init.txt"
id dfbot
'
