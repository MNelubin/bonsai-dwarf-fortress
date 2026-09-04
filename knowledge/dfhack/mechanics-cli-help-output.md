# CLI Help Output Mechanics

This note records the observed behavior of the `help` command executed via DFHack's runtime interface for version **53.15** of Dwarf Fortress paired with DFHack **53.15-r2**.

## Runtime Readiness Probe

- **Claim:** The runtime probe reported `runtime_ready:true` and `started:false`.
  - **[VERIFIED]** Source: `BONSAI_PROBE_RESULT` (runtime readiness probe output).
- **Claim:** `attempts` field was `1`.
  - **[VERIFIED]** Source: same probe output.

## DFHack Version Confirmation
- **Claim:** DFHack reports version `53.15-r2 (release)` on `x86_64`.
  - **[VERIFIED]** Source: help command output (`Here are some basic commands... DFHack version 53.15-r2`).

## Command List Captured
The `help` command printed a fixed set of core commands and their descriptions:

```text
help|?|man         - This text.
help <tool>        - Usage help for the given plugin, command, or script.
tags               - List the tags that the DFHack tools are grouped by.
ls|dir [<filter>]  - List commands, optionally filtered by a tag or substring.
                     Optional parameters:
                       --notags: skip printing tags for each command.
                       --dev:  include commands intended for developers and modders.
cls|clear          - Clear the console.
fpause             - Force DF to pause.
keybinding         - Modify bindings of commands to in-game key shortcuts.
```

- **Claim:** The command list shows the presence of control primitives (`fpause`, `keybinding`, `cls`).
  - **[VERIFIED]** Source: help output.
- **Claim:** No `reset` or `advance` command appears in the base list, implying they are provided by external plugins (e.g., `bridge-primitives`).
  - **[INFERRED]** Source: absence from help output combined with known plugin ecosystem.

## Directory Structure Checks

- **Claim:** Attempt to list `/srv/df-bonsai/current/dfhack/` returned "Not a directory".
  - **[VERIFIED]** Source: Bash tool use output (`/srv/df-bonsai/current/dfhack/: cannot open ... (Not a directory)`).
- **Claim:** The actual DFHack runtime resides in `/srv/df-bonsai/current/dfhack-run`.
  - **[VERIFIED]** Source: probe command path and subsequent `ls` output showing `dfhack-run` under the current directory.

## Implications for Reset / Observe / Act / Advance

1. **Reset / Observe** – Since the DFHack runtime is not a normal directory, custom scripts must target the `dfhack-run` binary or its symlink to issue a reset. Direct file‑system resets on non‑existent `dfhack/` directories will fail (observed).
2. **Act** – Commands such as `fpause`, `keybinding`, and `cls` are available without extra loading, enabling immediate programmatic control of the game loop and UI.
3. **Advance** – Advancement primitives are not part of the core `help` listing; they depend on `bridge-primitives` or similar plugins. Any automation that needs tick advancement must first load that plugin, which the current runtime does not confirm.
4. **Probe Recovery** – The readiness probe already includes the `help` command in its command list verification, providing a reliable sanity check before further probing.

## Concrete Coding Recommendations

- **Probe Invocation:** Always prefix DFHack commands with the full path to `dfhack-run` (e.g., `/srv/df-bonsai/current/dfhack-run help`) to avoid reliance on environment variable resolution.
- **Reset Routine:** Use `dfhack-run reset` (or the appropriate bridge command) after confirming the runtime directory structure; guard against "Not a directory" errors by checking `dfhack/` existence first.
- **Advance Integration:** Load `bridge-primitives` before invoking any `advance` or `set-time` functions; verify with `dfhack-run ls bridge-primitives` that the plugin is registered.
- **Observability Stub:** Capture the exact `help` output in a JSON field (`runtime.output`) to detect future changes in command set without re‑parsing console logs.
- **Error Handling:** For any Bash tool that attempts to access `dfhack/`, explicitly catch `Not a directory` (`2>err && grep -q 'Not a directory' err`) and fallback to the known `dfhack-run` path.
- **Documentation Sync:** When updating the knowledge index, add the new note under the **DFHack & Environment** section to keep the command‑level mechanics discoverable.

*All observations are derived directly from the bounded trace; where the trace does not provide evidence, the claim is marked **OPEN** or **INFERRED**.*
