# Bonsai lab agent

This service runs as root only inside the untrusted Dwarf Fortress LXC. It polls the trusted control API and starts OpenCode in non-interactive auto mode with `qwen3.6:27b-64k`. OpenCode supplies the mature read/grep/edit/write/bash tool loop; the wrapper supplies durable leases, fresh per-job clones, heartbeats, timeouts, artifact upload, and Git bundle packaging. With quantized KV cache, the 64K Qwen3.6 profile remains fully resident on the 24 GiB RTX 3090 and leaves roughly 4 GiB free for the host's existing GPU services.

It has no PostgreSQL or GitHub credential. The parent wrapper holds only a capability-limited lab API token, removes sensitive variables before OpenCode starts, and treats the separate control LXC as the actual trust boundary. Every job runs in a fresh clone so a failed experiment cannot corrupt the baseline checkout. DF-specific tools can be added later as local MCP servers without changing the scheduler or harness.

The wrapper publishes an idle/running/error heartbeat with its model, harness version, current job,
and progress. It refuses jobs without a trusted `base_commit` and checks out that exact commit before
OpenCode starts, so a stale lab checkout cannot silently change the experiment baseline.
Before each job the wrapper fetches the public trusted `main` into a local remote-tracking ref and
then checks out the job's exact commit. The lab receives no GitHub credential.
