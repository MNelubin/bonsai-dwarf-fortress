# Map Tile Query Mechanic

## Observation Summary
- **DFHack version**: VERIFIED – reported as `53.15-r2 (release)` in the output of `dfhack-run help lua` (source: output of `dfhack-run help lua`).
- **Runtime readiness**: VERIFIED – `runtime_readiness` reported `ready: true` (source: `runtime_readiness` output).
- **Existence of the `lua` command**: VERIFIED – appears with tags `dfhack | dev` (source: `dfhack-run help lua` output).
- **`tags` command output**: VERIFIED – list of tags includes `dfhack`; `advmap` is **not** present (source: output of `dfhack-run tags`).
- **Shell wrapper script `dfhack-run` content**: VERIFIED – 8 lines, line 6 exports `LD_LIBRARY_PATH` (source: `read` of `/srv/df-bonsai/current/dfhack-run`).
- **Attempt to read `df.global.time`**: INFERRED – the command `lua "print(df.global.time)"` returned `Cannot read field global.time: not found`, suggesting the field is unavailable in the current state (source: probe output).
- **Map tile query mechanic (`df.global.map.tiles[<x>,<y>,<z>]`)**: OPEN – the trace does not contain a direct probe (`dfhack-run help map` or successful query). It is only mentioned in a prior note, so its actual implementation remains unverified.

## Implications for Reset / Observe / Act / Advance
- **Reset**: To enable map tile queries ensure the game is loaded (not paused) and `df.global.map` is initialized. A reset of the runtime (e.g., `fpause` followed by `continue`) may be required before probing map tiles.
- **Observe**: The `lua` command can be used with the shortcut `!` to evaluate arbitrary expressions once the relevant tables exist (e.g., `:lua !df.global.map.tiles[0,0,0]` if verified). Current observations show `df.global.time` is inaccessible, indicating the probe must target a field that exists in the current runtime state.
- **Act**: Implementing a new DFHack plugin that exposes a safe wrapper around tile queries will not disturb existing job or unit systems. The wrapper should reference the `df.global.map.tiles` table after confirming it is non‑nil.
- **Advance**: The `fpause` command allows deterministic stepping while debugging tile logic. Use `advance` only after confirming the map state is stable.

## Smallest Coding Task
1. **Create a Lua function** `getTileState(x, y, z)` that safely returns a string representation of the tile type and flags:
   ```lua
   function getTileState(x, y, z)
     local tile = rawget(df.global.map, "tiles") and df.global.map.tiles[x, y, z]
     if not tile then return "nil" end
     return string.format("type=%s, flags=%s", tostring(tile.type), table.concat(tile.flags, ","))
   end
   ```
2. **Add** the function to a new DFHack plugin file at `knowledge/dfhack/test-map-tiles.lua`.
3. **Expose** it via a DFHack command, e.g. `map_tile <x> <y> <z>`, which calls `getTileState`.
4. **Test** deterministically by running:
   ```bash
   dfhack-run lua knowledge/dfhack/test-map-tiles.lua 0 0 0
   ```
   Expect output like `type=Floor, flags=...` for a known floor tile at the origin.

## Recommendations
- **Probe validation**: Future probes should explicitly attempt the map tile query to move the `df.global.map.tiles` claim from **OPEN** to **VERIFIED** or **INFERRED**.
- **Error handling**: The wrapper should treat `nil` tiles as "outside world bounds" rather than throwing errors.
- **Documentation**: Once verified, update the `dfhack/mechanics-map-tiles.md` note with the successful probe output and add a bullet to the Knowledge Index.
