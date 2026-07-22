# Advancement Time Mechanics

## Discovery
[VERIFIED]: dfhack includes deterministic `advancetime` command for time manipulation in 53.15-r2.
    - Command: /srv/df-bonsai/current/dfhack-run help advancetime
    - Result: advancetime [args] - Advance time and simulate game state changes.

## Bounded Probe
[INFERRED]: State transitions tracked via known tick deltas.
    - Probe Command: /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run :lua df.global.time
    - Result: Returns current in-game tick count allowing precise state verification.

## Deterministic API Proposal
1. Write minimal Lua script `advancetime.lua` exposing `resetGame`, `stepClock`, `nextYear`
2. Add test to `tests/dfhack/advancetime_test.rb` using known tick delta