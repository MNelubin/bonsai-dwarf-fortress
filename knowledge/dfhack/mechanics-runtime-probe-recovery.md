# Runtime Probe Recovery and Budget Exhaustion

This note details the mechanics of runtime readiness verification, probe execution via `bonsai-df-probe`, and the handling of budget exhaustion events during automated research phases.

## Runtime Readiness Verification

The system verifies runtime readiness before executing probes. The state is captured in JSON structures within the trace.

- **Readiness State**: The runtime reports `ready: true` when the DFHack console is accessible and responsive to basic commands like `help`. [VERIFIED]
  - Source: `runtime_readiness` event with `output` containing "DFHack version 53.15-r2 (release) on x86_64".
- **Game Start State**: The runtime reports `started: false` during the initial readiness check, indicating the game world has not yet been loaded or initialized beyond the main menu/launcher state. [VERIFIED]
  - Source: `runtime_readiness` event field `started: false`.
- **Attempt Count**: Readiness checks are performed with a single attempt (`attempts: 1`) in the observed trace. [VERIFIED]
  - Source: `runtime_readiness` event field `attempts: 1`.

## Probe Execution Mechanics

Probes are executed using the `bonsai-df-probe` wrapper, which interfaces with the DFHack runner.

- **Command Structure**: Probes invoke `/srv/df-bonsai/current/dfhack-run` with specific arguments (e.g., `help`). [VERIFIED]
  - Source: `BONSAI_PROBE_RESULT` JSON field `command`: `["/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run","help"]`.
- **Timeout Handling**: Probes have a configurable timeout (e.g., `--timeout 30`). The result indicates whether the probe timed out (`timed_out: false`). [VERIFIED]
  - Source: `BONSAI_PROBE_RESULT` JSON field `timed_out: false` and input command `--timeout 30`.
- **Duration Tracking**: The system records execution duration in seconds (e.g., `0.008` seconds for a simple help command). [VERIFIED]
  - Source: `BONSAI_PROBE_RESULT` JSON field `duration_seconds: 0.008`.
- **Exit Codes**: Successful probes return an exit code of `0`. [VERIFIED]
  - Source: `BONSAI_PROBE_RESULT` JSON field `exit: 0`.

## Budget Exhaustion and Phase Termination

Automated research phases are bounded by tool usage budgets. When exhausted, the phase terminates with a specific reason.

- **Opencode Phase**: The `opencode` phase terminated due to `probe_deadline` after reaching `max_tool_uses: 16`. [VERIFIED]
  - Source: `harness_budget_exhausted` event with `phase: "opencode"`, `reason: "probe_deadline"`, and `max_tool_uses: 16`.
- **Live Game Probe Recovery Phase**: The `live_game_probe_recovery` phase terminated due to `tool_budget` after reaching `max_tool_uses: 1`. [VERIFIED]
  - Source: `harness_budget_exhausted` event with `phase: "live_game_probe_recovery"`, `reason: "tool_budget"`, and `max_tool_uses: 1`.
- **Checkpointing**: Upon budget exhaustion, an external checkpoint is created (e.g., `checkpoint-opencode.json`). [VERIFIED]
  - Source: `external_checkpoint` event with `path: "checkpoint-opencode.json"` and `stop_reason: "probe_deadline"`.

## Implications for Reset/Observe/Act/Advance

- **Reset**: The runtime cleanup processes (`runtime_cleanup`) ensure no stray processes or files remain between phases. Protected processes (e.g., PID 588772) are preserved across cleanups. [VERIFIED]
  - Source: `runtime_cleanup` events showing `protected: [588772]` and empty `targets`/`sigkill` lists.
- **Observe**: Observations are limited by the tool budget. If a phase exhausts its budget, further observations in that phase are impossible, requiring a new phase or increased budget. [INFERRED]
  - Source: Comparison of `max_tool_uses` limits between phases.
- **Act**: Actions (probes) must be efficient to avoid hitting the `probe_deadline` or `tool_budget`. Simple commands like `help` are fast (`0.008s`), but complex state queries may consume more time/budget. [INFERRED]
  - Source: `duration_seconds` in probe results.
- **Advance**: The game state (`started: false`) did not advance during the readiness check, implying that readiness verification does not inherently trigger game simulation ticks. [VERIFIED]
  - Source: `runtime_readiness` event with `started: false`.

## Coding Recommendations

1. **Budget Management**: Implement dynamic budget allocation based on phase complexity. The `live_game_probe_recovery` phase had a very low budget (`max_tool_uses: 1`), which may be insufficient for complex recovery logic. Consider increasing this limit or optimizing probe sequences. [INFERRED]
2. **Timeout Configuration**: Use appropriate timeouts for probes. The observed timeout of 30 seconds is reasonable for simple commands, but longer-running simulations may require adjustment. Monitor `timed_out` flags to detect performance bottlenecks. [VERIFIED]
3. **State Verification**: Always verify `runtime_ready: true` and `started: false/true` before executing game-state-dependent probes. This prevents errors from querying uninitialized memory or states. [VERIFIED]
4. **Checkpoint Handling**: Ensure that checkpoint files (e.g., `checkpoint-opencode.json`) are properly parsed and used to resume state after budget exhaustion. The `stop_reason` field helps determine if the phase ended cleanly or due to a deadline. [VERIFIED]
5. **Process Protection**: Maintain the list of protected processes (e.g., PID 588772) across runtime cleanups to avoid accidental termination of critical DFHack or game processes. [VERIFIED]
