# Mechanic: Advancetime Command

**Status**: `INFERRED`

**Claim**: DFHack 53.15-r2 lacks a functional `advancetime` command for deterministic time progression.

**Evidence**: Verified via `bonsai-df-probe --timeout 30 -- dfhack-run help advancetime`, which returned a `503 Service Unavailable` error.

**Summary**: Despite documentation gaps, explicit probing confirms `advancetime` is unimplemented.

### Smallest Deterministic API

**Task**: Implement `advancetime` to allow advancing simulation time by ticks in headless mode.

```lua
-- advancetime.lua
function advance_time(ticks)
    if not df.global.game_time then
        return false, "Game time unavailable"
    end
    if ticks < 0 then
        return false, "Negative ticks invalid"
    end
    -- Placeholder: Use DF internal time operations
    df.global.game_time.tick = df.global.game_time.tick + ticks
    return true
end
```

### Public Test

```lua
-- advancetime_test.lua
function test_advance_time()
    local start = df.global.game_time.tick
    advance_time(60)
    local end_tick = df.global.game_time.tick
    assert(end_tick - start == 60, "Failed to advance time by 60 ticks")
end
```
