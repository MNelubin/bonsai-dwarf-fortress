# GitLab CI and deployment

The DF project deliberately does not deploy through the Proxmox host. GitLab Runner polls GitLab
from inside each target container:

- CT123 has an unprotected `bonsai-test` runner and a protected `bonsai-lab-deploy` runner.
- CT124 has only the protected `bonsai-control-deploy` runner.
- `main` is protected. Deployment jobs run only for `main` after every test suite and Ruff pass.
  MyPy gates the complete lab package and the typed control modules; the three legacy psycopg-heavy
  control modules remain test-gated until their row-factory annotations are repaired.
- The old instance runner `pve-host-shell` is not selected by this pipeline.

CT123 has no general Internet egress. Tests therefore use the root-owned `/opt/bonsai-ci/venv`, seeded
from the trusted runtime dependency set during runner bootstrap. Deployments are offline too: each one
clones the locally pinned dependency venv and reinstalls only the checked-out package with `--no-deps`.

Each deployment creates an immutable release named by the 40-character Git commit, switches `current`
atomically, restarts the affected services, and rolls the
symlink back when a health check fails. The lab deploy also installs the versioned DFHack Lua scripts.
The DF runtime itself is checked but is not restarted merely because Python control code changed.

Proxmox is used only for the one-time runner/network bootstrap. Routine tests, deployments, rollback,
and service checks happen inside CT123 and CT124 and contain no `pct`, SSH, or host-root step.
