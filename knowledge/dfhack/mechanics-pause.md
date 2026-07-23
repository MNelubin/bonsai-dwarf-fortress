# Pause state API Proposal

## Discovery Summary

This note documents the verified DFHack `pause` subsystem capability based on live game probes:

- `dfhack-run help fpause`: Confirmed the `fpause` command exists and can force DF to pause when framedrop exceeds 1 FPS.
- Direct Lua probe confirmed DFHack exposes pause state via `dfhack.isPaused()`.

## Proposed API

Lua function: `dfhack.isPaused() -> boolean`

This command will return true when DF is paused, and false when unpaused. The function is deterministic when called after `fpause` has been executed or when time advancement has occurred.

## Public Test Specification

Test `pause-state.lua`:
```lua
-- Pause state test
-- Verifies `dfhack.isPaused()` correctly reflects game state
-- Run after executing `fpause` in-game
"assert(dfhack.isPaused() == true, 'Game should be paused after fpause')"
-- Run after executing `advancetime` in-game
"assert(dfhack.isPaused() == false, 'Game should resume after time advancement')"
```