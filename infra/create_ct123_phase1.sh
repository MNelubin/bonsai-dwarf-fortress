#!/usr/bin/env bash
set -euo pipefail

ctid=123
template_name='debian-13-standard_13.6-1_amd64.tar.zst'
template_ref="local:vztmpl/${template_name}"
template_path="/var/lib/vz/template/cache/${template_name}"
public_key_path='/tmp/df-bonsai-codex-ed25519.pub'
config_path="/etc/pve/lxc/${ctid}.conf"

if [[ -e "$config_path" ]]; then
    echo "Refusing to continue: ${config_path} already exists" >&2
    exit 1
fi

if [[ ! -s "$template_path" ]]; then
    echo "Refusing to continue: template is missing: ${template_path}" >&2
    exit 1
fi

if [[ ! -s "$public_key_path" ]]; then
    echo "Refusing to continue: public key is missing: ${public_key_path}" >&2
    exit 1
fi

pct create "$ctid" "$template_ref" \
    --arch amd64 \
    --hostname df-bonsai \
    --ostype debian \
    --unprivileged 1 \
    --cores 16 \
    --memory 32768 \
    --swap 4096 \
    --rootfs trash:200 \
    --net0 'name=eth0,bridge=vmbr1,tag=10,firewall=1,ip=192.168.10.123/24,gw=192.168.10.1,type=veth' \
    --ssh-public-keys "$public_key_path" \
    --timezone Europe/Moscow \
    --onboot 0 \
    --start 0

pct config "$ctid"
pct status "$ctid"
