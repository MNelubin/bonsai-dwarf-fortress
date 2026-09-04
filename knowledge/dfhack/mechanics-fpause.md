## ffpause Mechanic Note

VERIFIED "fpause": Forced pause command exists in DFHack runtime. Tested via `dfhack-run help fpause` confirms command usability.

API Suggestion: Implement `pauseGame()` and `unpauseGame()` deterministic controls for headless operation. Next probe: Lua API verification. Use `tests/mechanics-pause.test` for behavioral assertions.
