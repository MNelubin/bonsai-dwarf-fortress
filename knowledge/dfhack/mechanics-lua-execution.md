# Mechanics - Lua Execution

## VERIFIED
- `fpause` command successfully forced game into paused state (from probe-1).
- DFHack provides interactive Lua interpreter via `lua` command (from help output).

## INFERRED
- Direct Lua execution shortcuts like `:lua @df.profession` are not recognized when called through `dfhack-run` (from probe-2).
- Shortcuts like `:lua` may only be available within the interactive interpreter session.

## OPEN
- Needs to determine if Lua statements can be executed non-interactively via script parameters.
- Required probe: Test `lua -s <script>` syntax with profession listing.

[Next task: Implement script argument test for Lua execution]
