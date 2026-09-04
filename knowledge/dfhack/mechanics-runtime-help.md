# Runtime Help Command Overview

## Observations
**<VERIFIED>** DFHack reports version **53.15-r2 (release)** running on **x86_64** platform. *(Source: `dfhack-run help` output, probe command `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help`)*
**<VERIFIED>** Runtime readiness probe indicates `ready = true`, `started = false`, `attempts = 1`. *(Source: runtime readiness JSON in the trace)*
**<VERIFIED>** The `help` command output lists the following built‑in DFHack commands: `help|?|man`, `help <tool>`, `tags`, `ls|dir [<filter>]`, `cls|clear`, `fpause`, `die`, `keybinding`. *(Source: same `help` output)*
**<VERIFIED>** The `ls|dir` command accepts optional flags `--notags` and `--dev`. *(Source: description in `help` output)*
**<VERIFIED>** Probe execution of the help command completed with `exit = 0`, `duration_seconds = 0.007`, and no timeout. *(Source: BONSAI_PROBE_RESULT JSON)*
**<VERIFIED>** The `glob` tool invocation failed for pattern `**/*.md` in `/srv/df-bonsai-current/knowledge/dfhack`. *(Source: tool_use entry with status `error`)*
**<INFERRED>** The duplicate entries in the `find` command output suggest that `-print` and `-printf` are invoked redundantly, likely due to a custom `find` implementation used by the bonsai environment.
**<INFERRED>** The presence of many markdown files under `knowledge/dfhack` indicates a documentation‑centric workflow, which can be leveraged for static analysis of plugin APIs.
**<OPEN>** No evidence was gathered about the effect of calling `fpause` on a running world; the help text only describes its purpose.
**<OPEN>** The relationship between `keybinding` and the in‑game UI state change is not probed; only the command signature is listed.

## Implications for Reset / Observe / Act / Advance
1. **Reset** – Re‑initialising the game should include a fresh probe of `runtime_ready` to avoid invoking commands when the runtime is still loading.
2. **Observe** – The `help` probe is a lightweight, zero‑side‑effect observation; it can be used early in a boot‑sequence to validate DFHack version and available tools.
3. **Act** – Commands such as `fpause` or `keybinding` require explicit confirmation of game state; they should be guarded by a readiness check.
4. **Advance** – Time advancement commands (`advance`) are not examined here; ensure they are placed after confirming `started = true`.

### Concrete Coding Recommendations
- **Probe First** – Before any DFHack interaction, run the builtin readiness probe (e.g., `dfhack-run help`) and assert `runtime_ready == true`.
- **Version Guard** – Compare the `DFHack version` string against the required `53.15-r2`; abort if mismatch.
- **Error‑Safe File Scans** – Replace the failed `glob` usage with a direct `find` invocation (`find dfhack -type f -name '*.md'`) to collect documentation files.
- **Document Command Flags** – Extend the help command parsing to capture flag specifications (`--notags`, `--dev`) for downstream tooling that builds command wrappers.
- **Track Command Side‑Effects** – Mark commands like `fpause` as `POTENTIAL_SIDE_EFFECT` in your actuator registry until a dedicated probe verifies their impact.
- **Avoid Assumed State** – Do not assume `started == true` after a pause; re‑probe the `runtime` object after each `fpause`/`unpause` cycle.
---
