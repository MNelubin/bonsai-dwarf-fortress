# Mechanics: Pause and Advancement

## VERIFIED Discoveries
- **Command `fpause` exists** – it appears in the default help output from DFHack.
  *Source:* `dfhack-run help` response (command `/srv/df-bonsai/current/dfhack-run help` executed via `bonsai-df-probe --timeout 30`).\n- **No help entry for `advance`** – querying `help advance` returned a red error "No help entry found for \"advance\"".
  *Source:* Probe output for `bonsai-df-probe ... dfhack-run help advance`.{\n  \"command\": ["/srv/df-bonsai/current/dfhack-run", "help", "advance"],\n  \"exit\": 0,\n  \"output\": "No help entry found for \"advance\""
}\n- **DFHack version confirmed** – version string "53.15-r2 (release) on x86_64" observed in help output.
  *Source:* Same `help` probe.

## INFERRED Understanding
- **`fpause` is likely the sole DFHack pause primitive** – absence of other pause‑related entries in `tags` output suggests no additional tool is provided under the `dfhack` tag for pausing.
  *Source:* `dfhack-run tags` probe (list of tags does not include a distinct pause tag).{\n  \"command\": ["/srv/df-bonsai/current/dfhack-run", "tags"],\n  \"exit\": 0,\n  \"tags\": ["adventure","animals","armok",...,\n            "dfhack","fort","fps",...,\n            "units","workorders"]
}\n- **Game state at pause time is reported as `runtime.started = false`** – the probing of `help` commands returned `started: false`, indicating the Fort is not running when DFHack is invoked.
  *Source:* Runtime object from first probe (runtime.started = false, runtime_attempts = 1).

## OPEN Questions
- **How to resume a paused fortress** – no DFHack command is documented for resuming; the help output lacks any `resume` or `unpause` entry, and the tags list does not provide a hint.
- **Whether `advance` is implemented as a Lua function rather than a CLI command** – absence in help does not guarantee non‑existence; probing Lua environment is required.

## Implications for Reset / Observe / Act / Advance
- **Reset:** The absence of a documented resume command means a reset sequence must explicitly start the fort (`bridge.start_game()`) after a pause.
- **Observe:** While paused, `dfhack-run` can still be used to query static data (e.g., list of units, map tiles) without affecting the simulation.
- **Act:** `fpause` provides a deterministic point to inject custom state changes; however, any act that depends on subsequent game ticks must wait for a resume or full reset.
- **Advance:** No built‑in `advance` CLI tool exists; time progression must be handled by the core DF engine once the game is resumed, or via custom scripts that call the underlying advance routine (if exposed).

## Concrete Coding Recommendations
1. **Create a minimal pause wrapper** in `/srv/df-bonsai/current/scripts/bridge/pause.lua`:
```lua
-- bridge.pause.lua v0.1.0
function bridge.pause_game()
    fpause()
    return true
end
```
2. **Add a placeholder resume function** and expose it as a DFHack command for future probing:
```lua
function bridge.resume_game()
    -- TODO: find appropriate internal call to unpause
    return false
end
```
3. **Implement unit tests** in `tests/unit/bridge/pause-test.lua` that assert:
   - `bridge.pause_game()` returns true and the fortress state transitions to `started = false`.
   - Current lack of a resume function yields false (track as OPEN).
4. **Probe the Lua namespace** for an advance primitive (`dfhack.run?("advance")` or similar) to resolve the OPEN question on time advancement.
5. **Document the missing resume and advance commands** in the knowledge bundle (as OPEN) and flag them for future investigation.
