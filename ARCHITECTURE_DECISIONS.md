# Bonsai architecture decisions

## Accepted

### AD-001 — GitHub repository

- Name: `bonsai-dwarf-fortress`.
- Visibility: private.
- Account tier: GitHub Free.
- The lab agent receives no GitHub credential.
- Automatic publication targets only `agent/*` branches.
- Promotion to `main` is automatic only after trusted hard gates; every decision is recorded as a durable approval event and failed candidates are rejected automatically.
- Canonical refs are backed up daily as a local Git bundle.

Accepted by the user on 2026-07-18.

## Accepted and implemented

### AD-002 — Separate trusted control plane

- New unprivileged Debian 13 LXC, VMID 124, hostname `bonsai-control`.
- 4 vCPU, 8 GiB RAM, 2 GiB swap, expandable 500 GiB ZFS root disk.
- VLAN10 address `192.168.10.124/24`, gateway `192.168.10.1`.
- Autostart enabled.
- No nesting, Docker, GPU, host bind mounts, or host credentials.
- Host Headscale membership: `bonsai-control = 100.96.0.6`; dashboard binds only to that address.

### AD-003 — Durable storage

- Reuse PostgreSQL CT 109 with a dedicated database and roles.
- Only `bonsai-control` can reach PostgreSQL on port 5432.
- Large artifacts live on the control LXC filesystem with SHA-256 metadata in PostgreSQL.
- CT 123 has no direct database credential.

### AD-004 — Initial autonomy level

- Planning, editing, tests, short evaluation, commits, and `agent/*` pushes can run automatically.
- Promotion to `main` and baseline replacement are automatic only after protected-path, test, evaluation, regression, resource, and fast-forward gates pass.
