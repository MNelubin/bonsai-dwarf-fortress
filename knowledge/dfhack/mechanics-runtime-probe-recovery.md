# Runtime Probe Recovery and Budget Exhaustion

This note documents the mechanics of runtime readiness verification, probe execution via `bonsai-df-probe`, and the handling of budget exhaustion during harness phases. It synthesizes observations from the `opencode` and `live_game_probe_recovery` phases.

## 1. Runtime Readiness Verification

The system verifies runtime readiness before executing probes. This is tracked in the `runtime_readiness` event type.

- **VERIFIED**: The `ensure_runtime_ready` phase sets `ready: true` when the DFHack CLI responds to basic commands.
  - *Source*: `runtime_readiness` event with `phase: "ensure_runtime_ready"`, `ready: true`, `attempts: 1`.
- **VERIFIED**: The runtime is considered ready even if the game simulation has not started (`started: false`).
  - *Source*: Same event shows `started: false` alongside `ready: true`.
- **VERIFIED**: The DFHack version identified during readiness checks is `53.15-r2 (release)` on `x86_64`.
  - *Source*: Output string in `runtime_readiness` event: `"DFHack version 53.15-r2 (release) on x86_64"`.

## 2. Probe Execution Mechanics

Probes are executed using the `bonsai-df-probe` wrapper, which encapsulates DFHack commands and returns structured results.

- **VERIFIED**: The probe command structure is `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout <seconds> -- <dfhack-run-path> <command>`.
  - *Source*: `tool_use` event with `callID: "call_j37tc6t9"`, input command: `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help`.
- **VERIFIED**: Successful probes return a `BONSAI_PROBE_RESULT` JSON block appended to the stdout output.
  - *Source*: Output of `call_j37tc6t9` contains `BONSAI_PROBE_RESULT {"exit":0,"timed_out":false,...}`.
- **VERIFIED**: The `BONSAI_PROBE_RESULT` includes metadata such as `duration_seconds`, `command` array, and a nested `runtime` object mirroring the readiness state.
  - *Source*: Same output shows `"duration_seconds":0.007` and `"runtime":{"ready":true,"started":false,...}`.
- **VERIFIED**: The underlying DFHack binary path used in probes is `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run`.
  - *Source*: `BONSAI_PROBE_RESULT` command array: `["/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run","help"]`.

## 3. Harness Phases and Budget Exhaustion

The harness operates in distinct phases, each with tool usage budgets. Exhaustion of these budgets terminates the phase.

- **VERIFIED**: The `opencode` phase uses a `general` tool profile and can exhaust its budget due to a `probe_deadline`.
  - *Source*: `harness_budget_exhausted` event with `phase: "opencode"`, `reason: "probe_deadline"`, `max_tool_uses: 16`.
- **VERIFIED**: The `live_game_probe_recovery` phase uses an `implementation_only` tool profile and can exhaust its budget due to `tool_budget` limits.
  - *Source*: `harness_budget_exhausted` event with `phase: "live_game_probe_recovery"`, `reason: "tool_budget"`, `max_tool_uses: 1`.
- **VERIFIED**: Runtime cleanup occurs before and after each phase, protecting specific processes (e.g., PID `588772`).
  - *Source*: `runtime_cleanup` events with `protected: [588772]` in both phases.

## 4. Implications for Reset/Observe/Act/Advance

- **Reset**: The runtime readiness check (`ensure_runtime_ready`) is a prerequisite for observation. If `ready` is false, probes may fail or return stale data. The system retries up to the configured attempts (observed: 1).
- **Observe**: Probes must be wrapped in `bonsai-df-probe` to capture structured results. Direct bash execution of DFHack commands does not yield the `BONSAI_PROBE_RESULT` metadata.
- **Act**: Actions that modify game state should verify runtime readiness first. The `started: false` flag indicates the game simulation is not active, which may affect state-dependent actions.
- **Advance**: Time advancement commands (e.g., `advance`) are not observed in this trace. However, the `fpause` command is available for forcing pauses, suggesting time control is possible via DFHack CLI.

## 5. Coding Recommendations

1. **Always Use Probe Wrapper**: When executing DFHack commands programmatically, use `bonsai-df-probe` to ensure structured output and timeout handling. Parse the `BONSAI_PROBE_RESULT` JSON for reliable status codes.
2. **Check Runtime State**: Before issuing game-state-dependent commands, verify `runtime.ready` is true. If `runtime.started` is false, avoid commands that require an active simulation.
3. **Handle Budget Exhaustion**: Implement retry logic or fallback strategies when `harness_budget_exhausted` events occur. Distinguish between `probe_deadline` (time-based) and `tool_budget` (count-based) failures.
4. **Protect Critical Processes**: Ensure that runtime cleanup scripts do not terminate protected processes (e.g., PID `588772`). Verify the `protected` list in `runtime_cleanup` events before issuing kill signals.
5. **Version Awareness**: Hardcode or dynamically detect DFHack version (`53.15-r2`) to ensure compatibility with command syntax and output formats.
