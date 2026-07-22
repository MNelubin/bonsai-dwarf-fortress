# Mechanics: Advancement API

## Claim: DFHack exposes deterministic time advancement via `advancetime` command

<VERIFIED>
`/srv/df-bonsai/current/dfhack-run help advancetime`
```
advancetime [args] - Advance time and simulate game state changes.
  args: seconds | years | ticks | season | decade | century
  --skip-events
  --dry-run
```
</VERIFIED>

<INFERRED>
Command accepted in headless session, but needs runtime probing to verify save state consistency.
</INFERRED>

<OPEN>
How does advancement interact with queued construction jobs and calendar year boundaries?
</OPEN>

## Implementation path

1. Write minimal Lua script `advancetime.lua` exposing `resetGame`, `stepClock`, `nextYear`
2. Add test to `tests/dfhack/advancetime_test.rb` using known tick delta
