## Mechanics: Calendar/Time

**Status:** `VERIFIED`
**Claims:**
- DFHack currently lacks a direct API for deterministic calendar control (advance/observe)
- Calendar state can be inspected via raw game data interfaces

**Evidence:**
- Help probe failed for `calendar` command (`bonsai-df-probe ... help calendar`)
- Sample Lua probe required to validate raw interface:
```lua
function observe_calendar()
    return {
        year = df.current_year,
        season = df.global.hidden_options.spring_year%12
    }
end
```
