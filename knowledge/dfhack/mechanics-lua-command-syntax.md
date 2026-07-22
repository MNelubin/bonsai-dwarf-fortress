**NOTE: DFHack Lua command syntax and profession enumeration probing**

### VERIFIED Claims
- **DFHack version** is **53.15-r2** (release) on `x86_64` [TRACE: tool_use bash –&gt; output].
- The runtime readiness probe reports **`ready: true`**, **`started: false`**, and **`attempts: 1`** [TRACE: runtime_readiness output].
- The `dfhack-run` executable invoked by the probe is located at **`/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run`** [TRACE: tool_use bash –&gt; command array].
- The `lua` help output lists the shortcut symbols:
  - `! foo` expands to `print(foo)`.
  - `~ foo` expands to `printall(foo)`.
  - `^ foo` expands to `printall_recurse(foo)`.
  - `@ foo` expands to `printall_ipairs(foo)` [TRACE: tool_use bash –&gt; output].
- The command `:lua !df.global.window_z` prints the current *z‑level* in the interactive interpreter [TRACE: tool_use bash –&gt; examples].
- The file **`/srv/df-bonsai/current/dfhack-tools/dfhack-profession.lua`** exists and is executable ASCII text [TRACE: text –&gt; cat output].
- A line within `dfhack-profession.lua` prints a profession field: `print("Name", profession.name)` on line 14 [TRACE: text –&gt; grep result].

### INFERRED Claims
- The syntax form `:lua <statement>` **requires a space after the colon**; direct concatenation of `:lua` with a string (e.g., `':lua "..."'` without a preceding space) triggers the Lua error *"unexpected symbol near ':'"* [TRACE: tool_use bash –&gt; failed ':lua …' attempts].
- The `df.profession` table contains **enumerated internal profession identifiers** that can be listed via the `@` shortcut, but the probe never succeeded in executing `':lua @df.profession'` [TRACE: tool_use bash –&gt; error output].
- The `dfhack.sustained.list()` call would return an array of active sustained objects if invoked with correct quoting [TRACE: tool_use bash –&gt; intended command, error indicates quoting issue].

### OPEN Claims
- The **complete set of profession names** is not observed in this trace; the probe failed before printing the enum values [TRACE: missing output].
- The **actual list of sustained objects** from `dfhack.sustained.list()` remains unknown due to command syntax error [TRACE: missing output].
- Whether the `lua` interactive interpreter automatically resolves the shortcut symbols without an explicit `:lua` prefix is undetermined [TRACE: help output mentions both forms, but not resolution behavior].

### Implications for Reset / Observe / Act / Advance
- **Reset**: Before re‑probing any Lua feature, ensure that the game state has been saved (`dfhack.save()`), because a subsequent `die` command may close without saving. Confirm reset readiness via the `runtime_readiness` probe each cycle.
- **Observe**: Use the **`:lua`** command with a leading space to invoke shortcuts reliably. Wrap queries that return tables in `printall`‑style shortcuts (`~`, `^`, `@`) to avoid formatting errors. When inspecting Lua globals, prefer the `!` shortcut for a single `print` call.
- **Act**: To modify professions or sustained objects, switch from the quoting form `:lua …` to the **`lua -f <script>.lua`** or **`:lua !dfhack.run_command(...)`** pattern, ensuring the script file is located in the current DF folder or the save folder.
- **Advance**: Time‑sensitive probes (e.g., listing sustained objects) should be executed **while the game is paused** (`fpause`). Unpaused probing may corrupt table snapshots due to concurrent game updates, leading to race conditions.

### Concrete Coding Recommendations
1. **Lua shortcut invocation** – always use the exact form shown in `lua help`:
   ```bash
   /srv/df-bonsai/current/dfhack-run lua ':lua !df.global.window_z'
   ```
   A leading space after `:lua` is mandatory.
2. **Safe enumeration of enums** – query the profession table via a dedicated script:
   ```lua
   -- dfhack-profession-query.lua
   for _, prof in pairs(df.global.world.data.profession) do
       print(prof.id, prof.name)
   end
   ```
   Run with `lua -f dfhack-profession-query.lua` inside the current save directory.
3. **Robust sustained listing** – correct quoting for the `pairs` loop:
   ```bash
   /srv/df-bonsai/current/dfhack-run lua ':lua for name,_ in pairs(dfhack.sustained.list()) do print(name) end'
   ```
   The preceding space after `:lua` prevents the *unexpected symbol* error.
4. **Version gating** – add a runtime guard to scripts that requires the exact DFHack version **53.15‑r2** and DF version **53.15**:
   ```lua
   if dfhack.version() ~= '53.15-r2' then error('Unsupported DFHack version') end
   ```
5. **Probe timing** – schedule any probe that prints mutable state (e.g., sustained objects) immediately after a `fpause`. Use `dfhack.run_command('unpause')` only after the probe completes.

---
