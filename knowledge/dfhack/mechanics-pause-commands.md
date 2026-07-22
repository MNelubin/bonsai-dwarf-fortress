
# Pause Commands

## VERIFIED: `fpause` Implementation

The `dfhack-run` help output confirms the existence of `fpause`:

```bash
/f/srv/df-bonsai/current/dfhack-run help lua ...
  fpause             - Force DF to pause.
```

### Coding Task: Deterministic Pause API

- Implement Lua wrapper `:pause()` that invokes `dfhack.run_command('fpause')`
- Add public test verifying timestamp before/after pause matches game tick delta

```lua
-- knowledge/dfhack/mechanics-pause-commands.md
-- Task: Implement :pause() API and unit test
```
