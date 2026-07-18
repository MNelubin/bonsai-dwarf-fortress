#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
chmod o+x /srv/df-bonsai /srv/df-bonsai/state
stat -c "%A %a %U:%G %n" /srv/df-bonsai /srv/df-bonsai/state
'
