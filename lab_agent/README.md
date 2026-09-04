# Bonsai lab agent

This service runs as root only inside the untrusted Dwarf Fortress LXC. It polls the trusted control API and starts OpenCode in non-interactive auto mode with `qwen3.6:27b-96k`. OpenCode supplies the mature read/grep/edit/write/bash tool loop; the wrapper supplies durable leases, fresh per-job clones, heartbeats, timeouts, artifact upload, and Git bundle packaging.

It has no PostgreSQL or GitHub credential. The parent wrapper holds only a capability-limited lab API token, removes sensitive variables before OpenCode starts, and treats the separate control LXC as the actual trust boundary. Every job runs in a fresh clone so a failed experiment cannot corrupt the baseline checkout. DF-specific tools can be added later as local MCP servers without changing the scheduler or harness.

The wrapper publishes an idle/running/error heartbeat with its model, harness version, current job,
and progress. It refuses jobs without a trusted `base_commit` and checks out that exact commit before
OpenCode starts, so a stale lab checkout cannot silently change the experiment baseline.
Before each job the wrapper fetches the public trusted `main` into a local remote-tracking ref and
then checks out the job's exact commit. The lab receives no GitHub credential.

Discovery and coding use separate prompts and promotion permissions. Discovery writes only the
source-tagged `knowledge/` library. Coding reads that library, writes implementation/docs plus public
tests, and cannot silently alter the knowledge base. A cycle with no commit is reported as rejected.

Before any LLM phase, the worker requires `bonsai-df-runtime.service` to be ready on the loopback
DFHack RPC endpoint. The `bonsai-df-probe` wrapper repeats that readiness check before every real
probe and starts the service on demand. The process reaper protects only the service's systemd cgroup
and still terminates leaked ad-hoc `dwarfort` processes.
