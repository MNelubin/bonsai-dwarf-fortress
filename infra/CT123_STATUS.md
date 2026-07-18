# CT 123 — df-bonsai

Created on 2026-07-18 on `PVE-Chert` as phase 1 of the Bonsai Dwarf Fortress project.

## Current state

- Status: `running`
- Autostart: disabled
- Guest OS: Debian GNU/Linux 13 (trixie)
- Template: `debian-13-standard_13.6-1_amd64.tar.zst`
- Type: unprivileged LXC
- CPU: 16 vCPU
- Memory: 32768 MiB
- Swap: 4096 MiB
- Root filesystem: `trash:subvol-123-disk-0`, 200 GiB
- Hostname: `df-bonsai`
- Time zone: `Europe/Moscow`
- Network: `vmbr1`, VLAN 10, `192.168.10.123/24`, gateway `192.168.10.1`
- Proxmox interface firewall flag: enabled; the cluster firewall itself was disabled at creation time
- SSH root key fingerprint: `SHA256:Ah+H1FAmcV0ioz3YyjIQNXQLwfhhsAvVOkHMvE2/Qp0`

## Isolation

The container was created without:

- nesting or keyctl;
- an AppArmor override;
- host bind mounts;
- additional storage mount points;
- device or GPU passthrough;
- Docker socket, Proxmox API credentials, or host secrets.

## Verification

Offline verification confirmed:

- the container remained stopped before and after verification;
- the root filesystem exists on ZFS with the expected 200 GiB size;
- `/etc/os-release` identifies Debian 13;
- the expected public SSH key is installed;
- no elevated LXC features, AppArmor override, mount points, or devices are present.

The temporary public-key copy on the Proxmox host was removed after verification.

## Approval boundary

Phase 2 was completed on 2026-07-18:

- the container is running;
- VLAN 10 DNS and outbound internet work through OPNsense;
- SSH is active; access from the Windows VM was verified through `root@192.168.0.2` as a jump host;
- Debian is fully updated;
- development and diagnostic packages are installed;
- SteamCMD is installed under `/opt/steamcmd` and runs as the dedicated `steam` user;
- Steam login was performed interactively; no password or Steam Guard code was placed in project files or command-line arguments;
- Dwarf Fortress Steam app `975370`, build `23622201`, version `53.15` is installed in staging;
- DFHack `53.15-r2` is downloaded and its archive SHA-256 is `294b788ab90c4d03f6f93ed30f16601d5f42567eae5528c6d93348c68b05f56c`;
- clean snapshot `base-debian13-steamcmd-20260718` exists;
- immutable release `df-53.15-steam-23622201_dfhack-53.15-r2` exists and `/srv/df-bonsai/current` points to it;
- headless mode uses `PRINT_MODE:TEXT` and disables sound;
- the game runs as the separate unprivileged `dfbot` account;
- smoke testing confirmed a live `dwarfort` process, DFHack build `53.15-r2`, and RPC bound only to `127.0.0.1:5500`;
- validated snapshot `df53-dfhack5315r2-20260718` exists;
- no persistent game service is enabled yet.

## Known integration note

The bundled `dfhack-run` client segfaulted when called during DFHack startup, although the game, DFHack injection, and loopback RPC listener remained healthy. The next phase should provide a controlled bridge/API and test command execution only after DFHack initialization is complete.
