## Pause State Observation

### VERIFIED
The `dfhack.isPaused()` API is confirmed via probe `dfhack-run help is-paused`.

### INFERRED
`dfhack.run('fpause')` toggles pause state deterministically.

### OPEN
Direct observation of paused entities (workers, animals) requires further probes.
