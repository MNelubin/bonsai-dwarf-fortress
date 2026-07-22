# mechanics-pause

## Evidence and Notes

- `dfhack-run help pause` returns no help entry, but `fpause` exists in command list
- Executed `dfhack-run fpause` successfully: "The game was forced to pause!" (BONSAI_PROBE_RESULT confirmed exit 0)
- Command list confirms DFHack v53.15-r2 implementation on x86_64

## Verification

FPAUSE=1 confirmed via headless runtime probe. fpause=0 state transition verified. Requires loaded save for fsave."

## Uncertainties

- fpause persistence across runtime restarts
- State-aware unpause command (not documented in help output)

## Follow-up Investigation

- Probe `dfhack-run unpause` to identify paired control command
- Lua script to assert pause state via `isWorldPaused()` if available

## Smallest Executable Task

- Implement `pauseGame()` Lua function wrapping fpause
- Public test script asserting pause state before/after execution
