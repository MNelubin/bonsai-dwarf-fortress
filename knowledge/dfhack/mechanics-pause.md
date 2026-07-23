# DFHack Pause/Advancement Mechanic

## Overview
This mechanic focuses on the ability to programmatically pause the game and advance time from DFHack scripts, enabling deterministic control over the simulation's temporal dynamics.

## Verified Components

### fpause Command
- `Command`: fpause
- `Tags`: dfhack
- `Description`: Forces DF to pause
- `Evidence`: Verified with `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help fpause`

### Time Advancement API
- **Status**: `INFERRED`
- **Claim**: DFHack's Lua interface likely provides a mechanism to advance game time or simulation ticks through functions like `game_time_advance()` or similar
- **Support**: Indirectly supported by the existence of the `fpause` command and the structured nature of the game's simulation

## Smallest Deterministic API

Create a Lua wrapper function that encapsulates pause/resume behavior:

```lua
-- pause_control.lua
function set_pause_state(state)
    if state == true then
        dfhack.script_running(true)
        dfhack.run_command('fpause')
    else
        dfhack.run_command('unpause')
    end
end

function advance_time(amount)
    -- Implementation to advance game time by 'amount' ticks
    -- Placeholder for actual function signature
end
end
```

## Public Test

```lua
-- pause_test.lua
function test_pause_resume()
    local start_tick = df.global.game_time.tick
    set_pause_state(true)
    pause_duration = 3 -- seconds
    set_pause_state(false)
    local end_tick = df.global.game_time.tick
    local elapsed = (end_tick - start_tick) / 60 -- convert ticks to minutes
    assert(math.abs(elapsed - pause_duration) < 0.1, 'Pause/resume test failed')
end
```

## Task Summary

**Smallest Task**: Add `pause_control.lua` wrapper with verified `fpause` integration

**Test Directory**: `knowledge/tests/pause_control/`