#!/usr/bin/env bash
set -euo pipefail

pct exec 123 -- bash -lc '
set -euo pipefail
echo "=== Release notes ==="
sed -n "1,60p" "/srv/df-bonsai/staging/df-steam/release notes.txt"
echo "=== DFHack markers ==="
grep -R -m5 -E "53[.]15|0[.]53[.]15" \
  /srv/df-bonsai/staging/dfhack/53.15-r2/payload/hack/news.rst \
  /srv/df-bonsai/staging/dfhack/53.15-r2/payload/hack/changelog.txt \
  /srv/df-bonsai/staging/dfhack/53.15-r2/payload/hack/symbols.xml \
  2>/dev/null || true
'
