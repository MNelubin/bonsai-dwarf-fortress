#!/usr/bin/env bash
set -euo pipefail

ps -ef | grep -E '[r]sync|[p]ct exec 123|build_df53' || true
pct exec 123 -- bash -lc '
set -euo pipefail
ps -ef | grep -E "[r]sync|build_df53" || true
du -sh /srv/df-bonsai/releases/.building-* 2>/dev/null || true
find /srv/df-bonsai/releases/.building-* -maxdepth 1 -type f -printf "%f\n" 2>/dev/null | tail -20 || true
'
