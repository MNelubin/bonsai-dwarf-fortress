# Mechanics - Pause/FPAUSE

## VERIFIED
- `fpause` command successfully forced game into a paused state (BONSAI_PROBE_RESULT: exit=0).

## INFERRED
- `dfhack-run` does not support Lua shortcuts (`:lua`) when invoked directly with command arguments (BONSAI_PROBE_RESULT: exit=1).

## OPEN
- Needs determination if `dfhack-run FPAUSE` can pause a loaded save without launching the game loop.
- Required probe: Run `dfhack-run FPAUSE` in a headful session and verify pause effect on save file.

[Next task: Probe non-headless `FPAUSE` execution]
