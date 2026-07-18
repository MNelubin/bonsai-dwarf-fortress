#!/usr/bin/env bash
set -euo pipefail

ctid=123

pct status "$ctid"
pct exec "$ctid" -- dpkg --audit
pct exec "$ctid" -- bash -lc "apt-get -s upgrade | grep -E '^0 upgraded, 0 newly installed, 0 to remove'"
pct exec "$ctid" -- systemctl is-active ssh
pct exec "$ctid" -- locale
pct exec "$ctid" -- runuser -u steam -- env HOME=/srv/steam /opt/steamcmd/steamcmd.sh +quit
pct exec "$ctid" -- stat -c '%U:%G %a %n' /opt/steamcmd /srv/steam /srv/df-bonsai
pct exec "$ctid" -- df -h /srv/df-bonsai
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader
