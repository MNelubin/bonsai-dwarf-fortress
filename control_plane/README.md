# Bonsai control plane

Trusted FastAPI dashboard, PostgreSQL-backed job leasing, append-only event ledger, and autonomous scheduler.

The dashboard shows worker liveness/model/version, exact trusted baseline commits, job timing and
progress, errors, results, downloadable artifacts, and the append-only event payloads. The
orchestrator will not schedule work until `current_baseline_commit` is set, and every automatic job
is pinned to that commit.

`bonsai-promoter` consumes candidate git bundles without executing their code in the trusted
container. It verifies ancestry, the path allowlist, diff hygiene, commit/file/size limits, forbids
symlinks and submodules, scans for credential patterns, statically parses changed Python and JSON,
requires public test/evaluator evidence, and only then fast-forwards GitHub and the trusted baseline.
This `bootstrap_static_v1` gate is deliberately identified in the ledger; gameplay score gates will
replace it after the deterministic bridge and evaluator exist.

The scheduler deliberately separates `discovery_cycle` from `coding_cycle`. Discovery can only
change the versioned `knowledge/` library and must maintain `knowledge/INDEX.md`; coding consumes
that library, cannot rewrite it, and must provide public tests. The deterministic cycle policy
bootstraps knowledge first, returns to discovery after an empty/failed coding attempt, and refreshes
knowledge after every three promoted coding changes. Its decision and reason are recorded in each
job payload and `job.queued` event.

The service binds to the control node's Headscale address `100.96.0.6:8080`, not to its VLAN10 address. The registered tailnet is `vpn.humaneconomy.ru`/`chert`.

The untrusted lab authenticates with a lab token and can lease/heartbeat/complete jobs. It never connects directly to PostgreSQL or GitHub.

Automatic promotion is permitted only for allowlisted code paths and only when unit, bridge, short, full, statistical, resource, and fast-forward gates all pass.
