# mechanics-pause-advancement

## VERIFIED: `fpause` Command Effect
- Command used: `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help fpause`
- Result: `fpause` forces game pause (confirmed exit 0)

## INFERRED: Missing Unpause Mechanism
- No `unpause` command in `dfhack-run help` output [SOURCE: help prompt]
- Potential workarounds: re-initialize runtime or invoke Lua API state transition

## Coding Task
1. Create Lua wrapper `dfhack.pause_game()` in `/srv/df-bonsai/current/scripts/bridge/pause.lua`
2. Write deterministic test `tests/unit/bridge/pause-test.lua` verifying state transition to `started = false`

## VERIFICATION
- Use `BONSAI_PROBE_RESULT` to confirm pause via `dfhack.run_command('fpause')`
- Cross-check `df.global.pause_state` changes in probe output