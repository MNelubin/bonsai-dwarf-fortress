#!/usr/bin/env bash
set -euo pipefail

pct exec 124 -- bash -lc '
set -euo pipefail
ps -ef | grep -E "[a]pt|[d]pkg|[c]url.*tailscale|bootstrap" || true
printf "tailscaled="; systemctl is-active tailscaled 2>/dev/null || true
printf "tailscale_bin="; command -v tailscale || true
printf "bonsai_user="; id bonsai 2>/dev/null || true
'
