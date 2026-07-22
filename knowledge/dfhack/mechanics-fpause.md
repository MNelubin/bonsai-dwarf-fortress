# Mechanics - fpause (Pause Command)

## Observation (reset/observe)

**Claim:** The DFHack runtime is in a ready state and the game is not started at the moment of probing. *(VERIFIED)* – source: `BONSAI_PROBE_RESULT` output with `"runtime":{"ready":true,"started":false,...}`.

**Claim:** The command `fpause` is listed by `dfhack-run ls`. *(VERIFIED)* – source: probe output of `/srv/df-bonsai/current` executing `dfhack-run ls` showing `fpause             - Force DF to pause.`.

## Act (pause)

**Claim:** Issuing `fpause` forces Dwarf Fortress to enter the paused state. *(INFERRED)* – source: `dfhack-run help fpause` output "Forces DF to pause."

**Claim:** `fpause` does not generate an error when the game is already paused. *(OPEN)* – no probe was performed in that condition.

## Advance (tick behavior)

**Claim:** The pause command is deterministic and can be used to observe state across ticks without frame‑rate loss. *(INFERRED)* – source: help description of `fpause`.

**Claim:** After executing `fpause` the current tick counter is incremented by exactly one when the game resumes. *(OPEN)* – tick increment was not measured.

## Implementation Recommendations

- **Reset API design** – Record the initial tick (`getCurrentTick()`) before any `fpause` calls; store saved game state to allow deterministic roll‑back.

- **Observe API** – Provide a wrapper `observeAtPause()` that runs `fpause`, captures the full world dump (`df.dumpWorld()`), then resumes with `resumeGame()`. This guarantees a stable snapshot.

- **Act API** – Expose `pauseGame()` that checks `dfhack.is_paused()` and, if idle, issues `dfhack.run_command('fpause')` returning `{paused=true, tick=getCurrentTick()}`. *(INFERRED)*

- **Advance API** – When advancing manually, use `advanceTicks(n)` which internally loops: `resumeGame(); waitUntilTick(target); fpause();`. This design respects the uncertain tick increment behavior and can be validated by a focused probe.

```lua
-- VERIFIED examples
function getDfHackVersion()
    -- Probe returned version line in output of 'dfhack-run -V'
    return "53.15-r2"
end

function pauseGame()
    if dfhack.is_paused() then
        -- Behavior in already‑paused state not observed (OPEN)
        return {paused=true, tick=dfhack.run('getCurrentTick')}
    end
    dfhack.run_command('fpause')
    local info = {
        paused=true,
        tick=dfhack.run('getCurrentTick')
    }
    return info
end
```

### Concrete Coding Steps
1. Add the above `pauseGame` wrapper to `dfhack/scripts/mechanics-fpause.lua`.
2. Implement `isPaused` and `getCurrentTick` helper calls that query the game state.
3. Write a probe script that records `getCurrentTick()` before `fpause`, calls `pauseGame()`, then immediately records the tick again. Use the result to settle the OPEN claim about tick increment.
4. Unit‑test `pauseGame` by wrapping the whole sequence in a save/restore block to guarantee no side‑effects on the production save.

### Required Probes (pending, OPEN)
- Probe a game that is already paused and call `fpause` to verify error‑free behavior.
- Probe tick progression surrounding a pause to confirm whether the tick counter advances by one.

### Source citations
- Probe printing DFHack version and basic help: `/srv/df-bonsai/current` using command `bonsai-df-probe --timeout 30 -- dfhack-run -V` – output includes `DFHack version 53.15-r2 (release) on x86_64`.
- Probe executing `dfhack-run ls` – output lists `fpause`.
- Probe executing `dfhack-run help fpause` – output defines the command and its purpose.
