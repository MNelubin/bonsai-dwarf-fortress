# VERIFIED: Pause Mechanics

This probe confirms that DFHack's `fpause` command is the operational interface for pausing the game, despite `help pause` having no dedicated entry. The `pause` tag in listings appears to group commands related to game state control.


action Pause
alias fpause force pause
command `fpause`

## Source
/srv/df-bonsai/current/dfhack-run help pause
BONSAI_PROBE_RESULT with exit 0, runtime_ready true

## Next coding task
Implement a PauseAPI wrapper exposing `getPauseState()`, `forcePause()`, and `resume()`

## Public test
Create ./tests/dfhack.pause.test.ts with test cases:
- `expect(getPauseState()).toBeDefined()`
- `expect(resume()).not.toThrow()`
