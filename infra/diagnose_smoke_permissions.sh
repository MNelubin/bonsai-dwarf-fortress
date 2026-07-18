#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
i=/srv/df-bonsai/state/instances/.smoke-df-53.15-steam-23622201_dfhack-53.15-r2-3082
namei -l "$i/dfhack"
stat -c "%A %a %U:%G %n" /srv /srv/df-bonsai /srv/df-bonsai/state /srv/df-bonsai/state/instances "$i" "$i/dfhack"
runuser -u dfbot -- bash -lc "id; pwd; cd \"$i\" && pwd && test -x ./dfhack && echo executable" || true
'
