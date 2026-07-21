# Unit Help Command Mechanics

## Overview
The `dfhack help` command provides a help overview for all DFHack tools. When the runtime is correctly started via the known `dfhack-run` executable, the command reports the active DFHack version, lists core utilities, and indicates runtime readiness. This knowledge is essential for safely probing unit‑specific commands, which require a ready runtime.

## Observed Commands (VERIFIED)
- **`dfhack help`** outputs the basic command list:
  ```
  help|?|man         - This text.
  help <tool>        - Usage help for the given plugin, command, or script.
  tags               - List the tags that the DFHack tools are grouped by.
  ls|dir [<filter>]  - List commands, optionally filtered by a tag or substring.
  cls|clear          - Clear the console.
  fpause             - Force DF to pause.
  die                - Force DF to close immediately, without saving.
  keybinding         - Modify bindings of commands to in‑game key shortcuts.
  ```
  *Source:* probe execution of `/srv/df-bonsai/current/dfhack-run help` (exit 0, runtime_ready true)【Probe: dfhack help】.

- **DFHack version** reported as **`53.15-r2` (release) on x86_64**
  *Source:* same probe output【Probe: version】.

## Failed Probe Attempts (VERIFIED)
- Attempt to run **`dfhack help unit`** using the wrapper `bonsai-df-probe` with an incorrect executable path fails:
  ```json
  {"exit":125,"runtime_ready":false}
  ```
  *Source:* probe `dfhack help unit` executed via `bash` (tool_use entry with status error, exit 125)【Probe: help unit failure】.

- The error message also states that the **probe executable must be `/srv/df-bonsai/current/dfhack-run` or `dwarfort`**.
  *Source:* same error probe output【Probe: executable requirement】.

## Deduced Implications (INFERRED)
- **`fpause`** can be used to pause the game before issuing delicate probes, ensuring a stable state for observation.
- **`die`** terminates the game instantly and should only be employed as a last‑resort reset, as it discards unsaved progress.
- The **unit‑specific help** subcommand likely exists, but its output was not captured because the runtime was not ready during the attempt.

## Uncertain Aspects (OPEN)
- The exact format and content of **`dfhack help unit`** remain unknown; no successful run was recorded in the trace.

## Practical Recommendations for Reset / Observe / Act / Advance Cycle
1. **Reset Phase** – Before any probing, validate that the probe wrapper points to the correct `dfhack-run` binary. If the path is wrong, abort and re‑configure the wrapper.
2. **Observe Phase** – Use **`fpause`** to halt the main loop, then invoke `dfhack help` to confirm the runtime is ready (`runtime_ready: true`). This guarantees that subsequent `dfhack help unit` calls will hit a stable interface.
3. **Act Phase** – Only after a successful `dfhack help` run should scripts attempt to dispatch unit‑specific commands; otherwise they risk exit 125 errors or undefined behavior.
4. **Advance Phase** – If a pause was used solely for observation, resume the game with standard DF controls or a custom `dfhack` resume script; no DFHack specific advance needed.

### Concrete Coding Suggestions
- **Path Validation Helper**:
  ```lua
  local function is_valid_dfhack_path(path)
      return path == '/srv/df-bonsai/current/dfhack-run' or path == 'dwarfort'
  end
  ```
  Integrate this check before each probe command.
- **Pre‑Probe Runtime Guard**:
  ```lua
  local function ensure_runtime()
      local result = dfhack.commands.getVersion() -- or equivalent minimal probe
      if not result then
          error('Runtime not ready; aborting command execution')
      end
      return true
  end
  ```
- **Fallback Logic**:
  If the first probe fails with exit 125, automatically retry with the known `dfhack-run` path and report the attempt count.
- **Logging**: Record both the command string and its exit code; treat exit 125 as a special case for mis‑routed probes.

By enforcing these safeguards, developers can reliably reset the environment, observe state, act on unit mechanics, and advance the game without encountering hidden runtime failures.
