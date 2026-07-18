#!/usr/bin/env bash
set -euo pipefail

echo '=== host network ==='
hostname
ip -br -4 addr
echo '=== host listeners of interest ==='
ss -H -lntp | grep -E ':(80|443|3000|8080|11434)([[:space:]]|$)' || true
echo '=== docker services of interest ==='
docker ps --format '{{.Names}}|{{.Image}}|{{.Ports}}' | grep -Ei 'ollama|open-webui|caddy|postgres|tailscale|headscale' || true
echo '=== ollama service ==='
curl -fsS --max-time 5 http://127.0.0.1:11434/api/version || true
echo
curl -fsS --max-time 10 http://127.0.0.1:11434/api/tags \
  | jq -r '.models[]? | [.name, .details.parameter_size, .details.quantization_level, (.size|tostring)] | @tsv' || true
echo '=== tailscale/headscale host view ==='
command -v tailscale || true
tailscale ip -4 2>/dev/null || true
tailscale status 2>/dev/null | sed -n '1,30p' || true
echo '=== CT 123 network and reachability ==='
pct exec 123 -- bash -lc '
set -euo pipefail
hostname
ip -br -4 addr
ip route
printf "tailscale="; command -v tailscale || true
for endpoint in \
  http://192.168.0.2:11434/api/version \
  http://100.64.0.1:11434/api/version; do
    printf "%s -> " "$endpoint"
    curl -fsS --max-time 5 "$endpoint" || echo unavailable
    echo
done
for target in 192.168.0.109:5432 192.168.0.114:80 192.168.0.115:8080; do
    host="${target%:*}"
    port="${target#*:}"
    if timeout 3 bash -c "</dev/tcp/$host/$port" 2>/dev/null; then
        echo "$target reachable"
    else
        echo "$target unavailable"
    fi
done
'
echo '=== current capacity ==='
free -h
df -h / /var/lib/docker
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits 2>/dev/null || true
