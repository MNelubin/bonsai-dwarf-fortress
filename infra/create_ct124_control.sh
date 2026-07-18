#!/usr/bin/env bash
set -euo pipefail

ctid=124
template_name='debian-13-standard_13.6-1_amd64.tar.zst'
template_ref="local:vztmpl/${template_name}"
template_path="/var/lib/vz/template/cache/${template_name}"
public_key_path='/tmp/codex_ed25519.pub'
config_path="/etc/pve/lxc/${ctid}.conf"

cleanup() {
    rm -f -- "$public_key_path"
}
trap cleanup EXIT

if [[ -e "$config_path" ]]; then
    echo "Refusing to continue: $config_path already exists" >&2
    exit 1
fi
if [[ ! -s "$template_path" ]]; then
    echo "Refusing to continue: template missing: $template_path" >&2
    exit 1
fi
if [[ ! -s "$public_key_path" ]]; then
    echo "Refusing to continue: public key missing: $public_key_path" >&2
    exit 1
fi
if ping -c 1 -W 1 192.168.10.124 >/dev/null 2>&1; then
    echo 'Refusing to continue: 192.168.10.124 responds to ping' >&2
    exit 1
fi

pct create "$ctid" "$template_ref" \
    --arch amd64 \
    --hostname bonsai-control \
    --ostype debian \
    --unprivileged 1 \
    --cores 4 \
    --memory 8192 \
    --swap 2048 \
    --rootfs trash:500 \
    --net0 'name=eth0,bridge=vmbr1,tag=10,firewall=1,ip=192.168.10.124/24,gw=192.168.10.1,type=veth' \
    --ssh-public-keys "$public_key_path" \
    --timezone Europe/Moscow \
    --onboot 1 \
    --start 0

pct set "$ctid" --description 'Trusted control plane for Bonsai Dwarf Fortress; no agent root, GPU, Docker, nesting, or host mounts'

echo '=== created config ==='
pct config "$ctid"
echo '=== status ==='
pct status "$ctid"

mount_path="/var/lib/lxc/$ctid/rootfs"
pct mount "$ctid" >/dev/null
trap 'pct unmount 124 >/dev/null 2>&1 || true; cleanup' EXIT

echo '=== offline guest verification ==='
grep -E '^(PRETTY_NAME|VERSION_CODENAME)=' "$mount_path/etc/os-release"
test -s "$mount_path/root/.ssh/authorized_keys"
ssh-keygen -lf "$mount_path/root/.ssh/authorized_keys"
if grep -Eq '^(features:|lxc[.]apparmor[.]profile:|mp[0-9]+:|dev[0-9]+:)' "$config_path"; then
    echo 'Unexpected elevated feature, AppArmor override, mount point, or device found' >&2
    exit 1
fi

pct unmount "$ctid"
trap cleanup EXIT
