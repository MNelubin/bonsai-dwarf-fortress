#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends libsdl2-2.0-0 libsdl2-image-2.0-0
ldd /srv/df-bonsai/staging/df-steam/dwarfort | grep "not found" && exit 1 || true
echo "Dwarf Fortress runtime dependencies resolved."
'
