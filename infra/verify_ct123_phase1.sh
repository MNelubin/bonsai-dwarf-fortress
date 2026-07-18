#!/usr/bin/env bash
set -euo pipefail

ctid=123
rootfs_path="/var/lib/lxc/${ctid}/rootfs"
mounted=0

cleanup() {
    if [[ "$mounted" -eq 1 ]]; then
        pct unmount "$ctid" >/dev/null
    fi
}
trap cleanup EXIT

pct status "$ctid"
pct config "$ctid"
pvesm list trash --vmid "$ctid"

pct mount "$ctid" >/dev/null
mounted=1

grep -E '^(PRETTY_NAME|VERSION_ID)=' "$rootfs_path/etc/os-release"
ssh-keygen -lf "$rootfs_path/root/.ssh/authorized_keys"

pct unmount "$ctid" >/dev/null
mounted=0

pct status "$ctid"

if grep -Eq '^(features:|lxc\.apparmor\.profile:|mp[0-9]+:|dev[0-9]+:)' "/etc/pve/lxc/${ctid}.conf"; then
    echo 'Unexpected elevated feature, AppArmor override, mount point, or device found' >&2
    exit 1
fi

echo 'Offline verification passed'
