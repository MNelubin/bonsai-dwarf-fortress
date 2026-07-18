#!/usr/bin/env bash
set -euo pipefail

ctid=124
template=/var/lib/vz/template/cache/debian-13-standard_13.6-1_amd64.tar.zst

echo '=== identity and capacity ==='
hostname
pvesh get /cluster/nextid
free -h
df -h / /var/lib/docker
pvesm status | sed -n '1,20p'

echo '=== CT 124 prerequisites ==='
if [[ -e "/etc/pve/lxc/$ctid.conf" ]]; then
    echo 'CT124_EXISTS'
    pct config "$ctid"
else
    echo 'CT124_ABSENT'
fi
stat -c '%n %s bytes %y' "$template"
if ping -c 1 -W 1 192.168.10.124 >/dev/null 2>&1; then
    echo 'IP_192.168.10.124_RESPONDS'
else
    echo 'IP_192.168.10.124_NO_RESPONSE'
fi
ip neigh show 192.168.10.124 || true

echo '=== PostgreSQL CT 109 ==='
pct status 109
pct exec 109 -- bash -s <<'GUEST'
set -euo pipefail
systemctl is-active postgresql
ss -H -lntp | grep ':5432' || true
runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -Atqc "SELECT version(); SHOW listen_addresses; SHOW port;"
echo 'databases:'
runuser -u postgres -- psql -X -Atqc "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname;"
echo 'roles:'
runuser -u postgres -- psql -X -Atqc "SELECT rolname FROM pg_roles ORDER BY rolname;"
echo 'hba rules:'
runuser -u postgres -- psql -X -Atqc "SELECT type,database,user_name,address,auth_method FROM pg_hba_file_rules ORDER BY line_number;"
GUEST
