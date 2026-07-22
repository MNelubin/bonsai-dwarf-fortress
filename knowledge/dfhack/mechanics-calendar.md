# Calendar/Time Bounded DFHack Exploration

**Command**: `lua` with `dfhack.run('lua')` interface

**Probed Verified Output**:

> ```bash
> /srv/df-bonsai/current/dfhack-run help lua
> ...
> :lua !df.global.window_z
> Print out the current z-level (as distinct from the displayed elevation).
> ...
> DFHack version 53.15-r2 (release) on x86_64
> ```

*Claim: The DFHack Lua interface provides access to game state fields via shortcuts (`!`, `~`, `^`, `@`)
and direct Lua queries.*  **VERIFIED** using `/opt/bonsai-probe .../dfhack-run help lua`.

**Link**: [Parent INDEX][index]

**Investigation Tasks**:

1. Probe timestamp formats via `:lua !calendar.last_turn` to verify turn-based time tracking.
2. Determine if `:lua !map.getTile(x, y, z)` returns tile metadata deterministically.
3. Extract flags/enums for weather, seasons, or celestial states from Lua documentation.

[index]: knowledge/INDEX.md
