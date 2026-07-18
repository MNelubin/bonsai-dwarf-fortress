#!/usr/bin/env bash
set -euo pipefail

echo '=== CT 115 ==='
pct status 115
pct exec 115 -- bash -s <<'GUEST'
set -euo pipefail
systemctl is-active headscale 2>/dev/null || true
config=""
for candidate in /etc/headscale/config.yaml /etc/headscale/config.yml; do
    [[ -f "$candidate" ]] && config="$candidate" && break
done
echo "config=$config"
if [[ -n "$config" ]]; then
    grep -n -E "^(policy:|[[:space:]]+path:|server_url:|listen_addr:)" "$config" || true
    policy="$(awk '
        /^policy:/ {in_policy=1; next}
        in_policy && /^[^[:space:]]/ {in_policy=0}
        in_policy && /^[[:space:]]+path:/ {sub(/^[[:space:]]*path:[[:space:]]*/, ""); gsub(/[\"'\'']/, ""); print; exit}
    ' "$config")"
    if [[ -n "$policy" && -f "$policy" ]]; then
        echo "policy_file=$policy"
        jq -c '{tagOwners:(.tagOwners // .tag_owners // null), grants:(.grants // null), acls:(.acls // null), ssh:(.ssh // null)}' "$policy" 2>/dev/null || sed -n "1,220p" "$policy"
    else
        echo 'policy_file=(not configured or not found)'
    fi
fi
echo '=== nodes near bonsai allocation ==='
headscale nodes list 2>/dev/null | sed -n "1,80p" || true
GUEST
