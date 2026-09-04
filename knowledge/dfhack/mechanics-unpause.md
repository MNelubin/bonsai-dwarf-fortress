# mechanics-unpause

## Evidence and Notes

- `dfhack-run fpause` VERIFIED pauses game (BONSAI_PROBE_RESULT exit 0)
- `dfhack-run unpause` returns no matching command (BONSAI_PROBE_RESULT exit 1)
- `:lua isWorldPaused()` fails with shell syntax error (BONSAI_PROBE_RESULT exit 1)
- DFHack v53.15-r2 command list confirms lack of explicit unpause tag

## Uncertainties
- Exact mechanism to resume game
- State-aware unpause function in Lua API

## Smallest Executables

1. Implement `unpauseGame()` Lua wrapper:
```lua
function unpauseGame()
    dfhack.scriptShutdown()
end
```
2. Test script: `pause-unpause-test.lua`
```lua
-- Verify game is paused
assert(df.isWorldPaused())

-- Attempt to unpause
:lp unpauseGame()

-- Verify game is resumed
assert(not df.isWorldPaused())
```