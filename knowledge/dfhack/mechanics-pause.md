## Pause/State Observation

### VERIFIED
`fpause` - Forces DF to pause. This is useful when your FPS drops below 1 and you lose control of the game.

### INFERRED
`dfhack.isPaused()` - Suggested API for checking pause state

### OPEN
Unified API for deterministic job progression needs further probes.

#### Probe evidence:
- `dfhack-run help fpause` confirms forced pause functionality
- `dfhack-run help is-paused` not yet verified

#### Next steps:
1. Add pause_game API to bridge with deterministic state
2. Implement Pause assertion test halting time progression