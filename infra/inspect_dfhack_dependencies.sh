#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
ldd /srv/df-bonsai/staging/dfhack/53.15-r2/payload/hack/libdfhack.so || true
'
