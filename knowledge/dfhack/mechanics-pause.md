# Frontmatter
```yaml
title: "Calendar Manipulation Via dpause"
category: mechanic
tags: pause time dpause
status: PROPOSED_VERIFIED
time: 7s
date: $(date +%F)
```

## Discovery of dpause Capability

- VERIFIED: The command `fpause` exists under `pause` tag (see [help pause probe](#probe))
- INFERRED: No built-in `time` command exists
- OPEN: Unclear what state transitions available

<!-- <details><summary>Probe #1 result</summary>

## probe 1: help pause

Command: help pause
Result: no help entry but `fpause` is listed under basic commands

<!-- </details> -->

<!-- <details><summary>Probe #2 result</summary>

## probe 2: help time

Command: help time
Result: no help entry found

<!-- </details> -->

<!-- <details><summary>Mechanic Mapping</summary>

## Pause Mechanic

- Command: `fpause`
- State Transition: Unknown (paused/reverted)
- Deterministic: Potentially via ticks or game state

<!-- </details> -->

## Next deterministic coding cycle

### Task

1. [ ] Add `pause` capability wrapper in `knowledge/scripts/dfhack/pause.lua`
2. [ ] Add public test in `knowledge/tests/pause.lua`
3. [ ] Run integration test with game state verification

### Script template

```lua
-- knowledge/scripts/dfhack/pause.lua
-- Smallest deterministic pause wrapper
local function dpause(isPaused)
    -- Implementation TBD
end

-- Export function
return { dpause = dpause }
```

### Test template

```lua
-- knowledge/tests/pause.lua
import 'knowledge/scripts/dfhack/pause.lua'
import '@test/test-utils'

describe('pause capability', function()
    it('should pause and resume game state', function()
        local originalState = captureState()
        dfhack.script.run('knowledge/scripts/dfhack/pause.lua')
        local pausedState = captureState()
        assert.not_same(pausedState, originalState)
    end)
end)
```