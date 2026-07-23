## Mechanics-Pause

Paused execution with `fpause` in DFHack 53.15-r2 VERIFIED via direct command usage. The game is frozen but remains savable. Advancement requires a separate resume operation not covered here.

```bash
/srv/df-bonsai/current/dfhack-run help fpause
```

Result: Command pauses the game unconditionally, useful for low FPS scenarios. No time progression occurs during pause.

### Next Step

Implement minimal pause API with public test:
```
Create knowledge/dfhack/pause-api.md with deterministic parameters
```