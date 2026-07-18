# Bonsai control plane

Trusted FastAPI dashboard, PostgreSQL-backed job leasing, append-only event ledger, and autonomous scheduler.

The dashboard shows worker liveness/model/version, exact trusted baseline commits, job timing and
progress, errors, results, downloadable artifacts, and the append-only event payloads. The
orchestrator will not schedule work until `current_baseline_commit` is set, and every automatic job
is pinned to that commit.

The service binds to the control node's Headscale address `100.96.0.6:8080`, not to its VLAN10 address. The registered tailnet is `vpn.humaneconomy.ru`/`chert`.

The untrusted lab authenticates with a lab token and can lease/heartbeat/complete jobs. It never connects directly to PostgreSQL or GitHub.

Automatic promotion is permitted only for allowlisted code paths and only when unit, bridge, short, full, statistical, resource, and fast-forward gates all pass.
