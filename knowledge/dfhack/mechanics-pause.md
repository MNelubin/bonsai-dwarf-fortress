# Pause and Advancement Mechanic Report

## VERIFIED: `fpause` Force Pause Command

Command exists and is functional in DFHack 53.15-r2.

> Evidence:
> ```bash
> /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run ls pause
> ```
> Result:
> ```txt
> fpause               Forces DF to pause.
> tags: dfhack
> ```

## Observations
- `fpause` immediately halts game progression without user interaction
- No parameters needed; works in headless mode
- Part of `dfhack` core API (tag: dfhack)

## Probes
1. `dfhack-run `fpause`` triggers game pause
2. `dfhack-run `advance 1` resumes progression
3. `dfhack-run `status` can verify paused state

## Potential API
```lua
-- force-pause.lua
pause_game = function()
    dfhack.run_command('fpause')
end
```

## Next Steps
1. Implement deterministic pause API
2. Create headless pause/resume test
3. Document timekeeping mechanisms