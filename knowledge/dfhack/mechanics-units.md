## Unit Mechanic Insights (DFHack 53.15-r2)

### VERIFIED Claims

- **Claim**: The `lua` command supports shortcut syntax `:lua !unit.id` to print the current selected unit's ID.
  **Source**: Probe output line `":lua !unit.id"   Print out the id of the currently selected unit.`

- **Claim**: Shortcut characters `!`, `~`, `^`, `@` map to specific Lua printing actions (`print`, `printall`, `printall_recurse`, `printall_ipairs` respectively).
  **Source**: Probe output section describing shortcuts:
  `'! foo' => 'print(foo)'`, `'~ foo' => 'printall(foo)'`, `'^ foo' => 'printall_recurse(foo)'`, `'@ foo' => 'printall_ipairs(foo)'`.

- **Claim**: The `lua` command is tagged with `dfhack` and `dev`, indicating it is a core DFHack tool.
  **Source**: Probe output header `Tags: dfhack | dev`.

- **Claim**: DFHack runtime was ready (`runtime_ready": true`) and the game had not started (`started": false`) when the probe executed.
  **Source**: Runtime readiness object in trace:
  `{"ready": true, "started": false, "attempts": 1, ...}`.

### INFERRED Claims

- **Claim**: By using `:lua !unit.id` scripts can directly query unit IDs, enabling rapid observation of unit state without fully writing Lua.
  **Source**: Inferred from the VERIFIED shortcut behavior.

- **Claim**: The shortcut forms allow inspection of toggleable flags (`:lua ~item.flags`) and profession enums (`:lua @df.profession`), providing a lightweight way to capture game fields for later analysis.
  **Source**: Inferred from provided shortcut examples.

### OPEN Claims

- **Claim**: Whether unit shortcut queries (`!unit.id`) function on a running (non‑paused) fortress is unknown without additional probes.
  **Source**: No probe result observed for this scenario; status remains **OPEN**.

## Implications for Reset / Observe / Act / Advance

1. **Reset** – Since the runtime was paused (not started), a reset can be performed safely via DFHack commands before any gameplay state is loaded, ensuring a clean context for subsequent probes.
2. **Observe** – The `:lua !unit.id` shortcut provides a low‑overhead method to capture the unit ID during observation phases, facilitating targeted data collection for unit‑specific analyses.
3. **Act** – Knowing the unit ID enables writing Lua scripts that issue actions on that exact entity (e.g., `:lua df.units aktualize(unit.id)`).
4. **Advance** – After confirming stable unit IDs, teams can advance the game with `advancetime` while periodically re‑checking IDs via the shortcut to validate persistence of mechanic state.

## Concrete Coding Recommendations

- **Create a reusable Lua wrapper** named `unit_inspect.lua` that runs `:lua !unit.id` and logs the output to a local file, using the DFHack API to ensure the game is paused before execution.
- **Implement a probe script** that first calls `fpause`, then runs the wrapper, and finally records the timestamped unit ID for downstream correlation.
- **Document uncertainty**: In any analysis pipeline, flag data derived from `!unit.id` with `OPEN` until a probe confirming operation on an active simulation is recorded.
- **Version guard**: Insert a version check at the top of the wrapper to enforce compatibility with DFHack 53.15-r2, e.g.:
  ```lua
  if dfhack.version() ~= '53.15-r2' then
      print('Unsupported DFHack version') return
  end
  ```
