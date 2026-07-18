#!/usr/bin/env bash
set -euo pipefail

ctid=123

if [[ "$(pct status "$ctid")" == 'status: stopped' ]]; then
    pct start "$ctid"
fi

for _attempt in $(seq 1 15); do
    if pct exec "$ctid" -- systemctl is-system-running --wait >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

pct status "$ctid"
pct exec "$ctid" -- hostnamectl
pct exec "$ctid" -- ip -brief address show eth0
pct exec "$ctid" -- ip route show
pct exec "$ctid" -- getent ahostsv4 deb.debian.org
pct exec "$ctid" -- bash -lc 'timeout 10 bash -c "</dev/tcp/deb.debian.org/80"'
pct exec "$ctid" -- systemctl is-enabled ssh
pct exec "$ctid" -- systemctl is-active ssh
