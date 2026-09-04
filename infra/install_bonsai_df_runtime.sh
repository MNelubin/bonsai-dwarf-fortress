#!/usr/bin/env bash
set -euo pipefail

ctid=${1:-123}
repo=${2:-/srv/bonsai-agent/workspace}
unit=bonsai-df-runtime.service

pct status "$ctid" | grep -q 'status: running'
pct exec "$ctid" -- test -x /srv/df-bonsai/current/dfhack
pct exec "$ctid" -- test -x /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe
pct exec "$ctid" -- install -d -m 0750 \
  /srv/df-bonsai/runtime /srv/df-bonsai/runtime/home /srv/df-bonsai/runtime/xdg
pct exec "$ctid" -- install -m 0644 \
  "$repo/lab_agent/systemd/$unit" "/etc/systemd/system/$unit"
pct exec "$ctid" -- systemctl daemon-reload
pct exec "$ctid" -- systemctl enable --now "$unit"
pct exec "$ctid" -- /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe \
  --ready-timeout 45 --timeout 10 -- /srv/df-bonsai/current/dfhack-run version
pct exec "$ctid" -- systemctl is-active "$unit"
