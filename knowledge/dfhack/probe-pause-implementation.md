# Mechanics: Pause & Advancement Implementation

## VERIFIED Discoveries
- **Command `fpause` exists and works** – confirmed via `bonsai-df-probe --timeout 30 -- dfhack-run help` output.
- **No DFHack CLI resume command** – `dfhack-run help resume` returns "No help entry found for \"resume\"" (source: same probe).

## INFERRED Understanding
- **`fpause` is the sole pause primitive** – absence in `tags` output suggests no additional pause tools (source: `bonsai-df-probe ... dfhack-run tags`).
- **Runtime readiness** – games are not running during probes (`runtime.started = false`) (source: probe runtime object).

## OPEN Questions
- **Resume mechanism** – unknown if internal DFHack method exists for resuming (verified via absent help entries).
- **Time advancement** – `advance` CLI command missing; possible Lua-only implementation.

## API & Test Design

### Proposed `bridge.pause_game()` API
```lua
-- bridge.pause.lua v0.1.0
function bridge.pause_game()
    fpause()
    return true
end
```

### Public Test (`tests/unit/bridge/pause-test.lua`)
```lua
local tests = require('dfhack.testing')
local bridge = require('scripts.bridge')

equals(tests.env, bridge.pause_game(), true, 'Pause command returns success')
```