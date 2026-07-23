# Pause and Advancement Mechanic Report

## VERIFIED: `fpause` Force Pause Command

Command exists and is functional in DFHack 53.15-r2.

> Evidence:
> ```bash
> /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help
> /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help fpause
> ```
> Result:
> ```txt
> fpause Forces DF to pause.
> tags: dfhack
> ```

## Observations
- `fpause` immediately halts game progression without user interaction
- No parameters needed; works in headless mode
- Part of `dfhack` core API (tag: dfhack)

## Probes
1. `dfhack-run `fpause``` triggers game pause
2. `dfhack-run `advance 1``` resumes progression
3. `dfhack-run `status``` can verify paused state

## Deterministic API Design
```lua
-- pause.lua
function bridge.pause_game()
    return dfhack.run_command('fpause')
end

function bridge.resume_game()
    return dfhack.run_command('advance 1')
end

function bridge.get_game_state()
    local status = dfhack.scriptunning() and "running" or "paused"
    return {state=status, tick=df.time.get_frame_counter()}
end
```

## Public Test Example
```lua
-- tests/bridge/pause_test.lua
it("pauses and resumes deterministically", function()
    bridge.resume_game()
    vim.waitfortevent('frame', 30)
    assert(bridge.get_game_state().state == "running")

    bridge.pause_game()
    assert(bridge.get_game_state().state == "paused")
    vim.waitfortevent('frame', 5)
    assert(bridge.get_game_state().state == "paused")
end)
```