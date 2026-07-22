## mechanics-pause.md

### Pause and Advancement

DFHack exposes in-game controls through commands like `fpause` (force pause). This provides deterministic time-stasis while preserving save integrity. Pause state is persistent but can hang the simulation in headless mode (requires SIGUSR1 resume).

VERIFIED `dfhack-run help` includes `fpause` in its command list.

Next step:

1. Create note linking from knowledge/INDEX.md
2. Bounded probe to verify `fpause` execution and resume behavior

<smallest-task>Probe: verify `dfhack-run fpause` pauses and resume via wrapper signal</smallest-task>
