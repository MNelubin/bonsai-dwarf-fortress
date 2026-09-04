## Pause/State Observation

### VERIFIED
`dfhack.isPaused()` toggles pause via `dfhack-run help is-paused`.

### INFERRED
`dfhack.run('fpause')` stops advancement when game is paused.

### OPEN
Unified API for deterministic job progression needs further probes.

<next-task>Add pause_game API to bridge with deterministic state</next-task>

<next-test>Pause assertion test halting time progression</next-test>
- [mechanic-pause.md](#mechanic-pause-md)
- [Mechanics: Buildings](#mechanics-buildings)
- [mechanic-buildings.md](#mechanic-buildings-md)
