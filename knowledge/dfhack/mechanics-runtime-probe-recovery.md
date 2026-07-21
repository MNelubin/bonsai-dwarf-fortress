# Runtime Probe Recovery and Budget Exhaustion

## Scope

This note documents the observed behavior of the `bonsai-df-probe` wrapper during runtime recovery phases, specifically focusing on successful command execution versus budget exhaustion scenarios. It applies to Dwarf Fortress 53.15 and DFHack 53.15-r2.

## Successful Probe Execution [VERIFIED]

During the `live_game_probe_recovery` phase, a bounded probe was executed using the trusted wrapper. The command successfully returned structured metadata indicating runtime readiness.

**Command:**
```bash
/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help
```

**Observed Result (`BONSAI_PROBE_RESULT`):**
- **Exit Status:** `0`
- **Timed Out:** `false`
- **Duration:** `0.009` seconds
- **Runtime Ready:** `true`
- **Runtime State:**
  - `ready`: `true`
  - `started`: `false`
  - `attempts`: `1`

**Implication:** The wrapper correctly isolates the process, executes the command within the timeout, and returns a JSON payload confirming the DFHack runtime is responsive and ready for further commands. The low duration (9ms) suggests the runtime was already initialized or started very quickly.

## Budget Exhaustion Scenarios [VERIFIED]

The trace reveals two distinct instances where harness phases terminated due to resource constraints rather than logical completion:

1. **`opencode` Phase:**
   - **Reason:** `probe_deadline`
   - **Max Tool Uses:** 16
   - **Context:** The agent attempted to read existing knowledge and inspect the runtime but exhausted its tool use budget before completing a full probe cycle or writing new knowledge.

2. **`live_game_probe_recovery` Phase:**
   - **Reason:** `tool_budget`
   - **Max Tool Uses:** 1
   - **Context:** After successfully executing one probe (`help`), the phase terminated immediately because the tool budget was exhausted after that single use.

**Implication:** Autonomous agents operating in this environment are strictly constrained by tool-use budgets. A successful probe does not guarantee subsequent actions can be taken in the same phase if the budget is low (e.g., 1 tool use). Phases must be designed to prioritize critical state verification within the first few tool calls.

## Design Implications for Reset/Observe/Act/Advance

- **Observe:** The `BONSAI_PROBE_RESULT` JSON structure is the primary source of truth for runtime health. Agents should parse this JSON to determine if `runtime_ready` is true before attempting state queries.
- **Act:** Commands like `help` are safe, low-cost probes. More complex Lua injections require careful budget management as they may consume multiple tool uses or risk timeouts.
- **Advance:** Time advancement commands (`advance`, `tick`) should only be issued after confirming `runtime_ready: true` via a probe result.
- **Reset:** If a probe times out or fails with a non-zero exit, the runtime may be in an inconsistent state. The wrapper's SIGKILL mechanism ensures cleanup, but subsequent phases must re-verify readiness.

## Coding Recommendations

1. **Parse Probe Results:** Always parse the `BONSAI_PROBE_RESULT` JSON from stdout to check `exit`, `timed_out`, and `runtime_ready`. Do not rely solely on exit code 0.
2. **Budget Awareness:** Design probe sequences to fit within expected tool budgets. If a phase has a budget of 1, it can only perform one action (e.g., verify readiness). Subsequent actions must be deferred to later phases.
3. **Timeout Handling:** Use the `--timeout` flag appropriately. For simple commands like `help`, a short timeout is sufficient. For complex state queries, increase timeout but monitor for `timed_out: true` in results.
4. **Error Recovery:** If a probe fails, do not assume the runtime is dead. Re-attempt with a fresh probe in a new phase or after a reset command if available.

## Open Questions

- What is the minimum tool budget required to perform a full state query (e.g., read unit list) and act upon it? [OPEN]
- How does the runtime handle concurrent probes from different phases? [OPEN]
