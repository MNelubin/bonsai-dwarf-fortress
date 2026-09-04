# Date Mechanics (DFHack 53.15 / DFHack 53.15-r2)\n\n## Overview\nThis note records the observed DFHack interface for querying the game calendar and the current status of a dedicated `date` command.\n\n## Trace Assertions\n- **VERIFIED**: The DFHack runtime is ready for probing (`ready": true`).\n  - Source: `runtime_readiness` probe output, `started": false`, `attempts": 1` (path \`/srv/df-bonsai/current` in tool `bash` command).
- **VERIFIED**: DFHack version matches the required **53.15-r2**.\n  - Source: "DFHack version 53.15-r2 (release) on x86_64" from the same probe output.
- **VERIFIED**: The `help lua` probe returns the full help text for the `lua` command, including usage examples such as `:lua !df.global.year` to print the current year. \n  - Source: `bash` tool execution `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- dfhack-run help lua` (output captured, duration 0.016 s).
- **VERIFIED**: The `help date` probe yields **No help entry found for \"date\"**, indicating that a `date` tool is not presently defined in the DFHack command set.\n  - Source: `bash` tool execution `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- dfhack-run help date` (output captured, duration 0.009 s).
- **INFERRED**: To retrieve calendar information developers must invoke Lua directly, e.g., `:lua !df.global.year`. This suggests the absence of a higher‑level `date` command.\n  - Reasoning: The `lua` help explicitly documents the shortcut `!` for `print`, and the calendar fields (`df.global.year`, `df.global.month`, etc.) are accessible via that mechanism.
- **OPEN**: The actual value of `df.global.year` (i.e., the current in‑game year) is unknown pending an explicit probe. The suggested command to resolve it is:
  ```bash
  /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- dfhack-run lua !df.global.year
  ```
  This probe has not been executed yet, so the claim remains open.\n\n## Implications for Reset / Observe / Act / Advance\n1. **Reset**: Because no `date` command exists, resetting the calendar state must be performed via Lua scripts that modify `df.global.year` or related fields after a full game reset. This bypasses any high‑level reset tool.
2. **Observe**: Calendar observation must rely on the `lua` shortcut form; the probe `lua !df.global.year` can be added to the observe pipeline to retrieve the year without waiting for a custom tool.
3. **Act**: If an operation requires adjusting the calendar (e.g., advancing the year for testing), developers should write a Lua script that sets `df.global.year` and inject it via `:lua -f <script>`. No direct `date` command will trigger this action.
4. **Advance**: The `pause` and `advance` mechanisms remain unchanged, but any time‑based logic that depends on the game year must be supplemented with Lua checks to ensure the year state is as expected before advancing ticks.\n\n## Concrete Coding Recommendations\n- **Implement a `date` facade** in DFHack that forwards to a Lua snippet, e.g.:
  ```lua
  function command_date()
      print('Year: '..df.global.year '..' 'Month: '..df.global.time_...»
  end
  ```
  Register this command under the `dfhack` tag to satisfy the missing help entry.
- **Add automated verification** to the probe suite: execute `lua !df.global.year` at the start of each session and store the value in a persistent log. This will close the OPEN claim about the year value.
- **Document the Lua shortcut syntax** in the DFHack CLI guide, emphasizing that calendar queries can be performed with `!` (print) and `~` (printall) shortcuts to avoid the need for a dedicated `date` tool.\n- **Update the `help` index** to include the new `date` command, ensuring consistency with other mechanics‑focused notes.\n\n*All trace citations refer to the bounded research trace provided; no external or invented data are used.*
