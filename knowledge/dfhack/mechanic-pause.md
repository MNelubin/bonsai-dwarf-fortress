## Mechanic-Pause.md

### Mechanic
Pause/State Observation subsystem in Dwarf Fortress

### Tags
gameplay

### Evidence
#### VERIFIED `dfhack.isPaused()`
```bash
/sopt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help pause
```
Output: `dfhack.isPaused() toggles pause via dfhack-run help is-paused`

#### INFERRED `dfhack.run("fpause")`
```bash
/sopt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help mod
```
Output: `fpause - Force DF to pause.`

#### OPEN Unified API for deterministic job progression requires further probes

### Next Step
Create a deterministic pause_game API that reliably pauses/resumes the game with state verification. Write a headless test asserting game pause state via wrapper probe.

Test: Verify `dfhack.isPaused()` returns true when paused, false when unpaused.
