# Runtime Probe Recovery and Budget Exhaustion

This note documents the mechanics of runtime readiness verification, probe execution via `bonsai-df-probe`, and the handling of budget exhaustion during harness phases. It synthesizes observations from the `opencode` and `live_game_probe_recovery` phases.

## 1. Runtime Readiness Verification

The system verifies runtime readiness before executing probes. This is tracked in the `runtime_readiness` event type.

- **VERIFIED**: The runtime readiness check returns a structured object containing `ready`, `started`, and `attempts` fields.
  - Source: `runtime_readiness` event in trace.
  - Observation: `{"ready": true, "started": false, "attempts": 1}`.
- **VERIFIED**: The output of the readiness check includes the DFHack help text, confirming the CLI is responsive.
  - Source: `output` field in `runtime_readiness` event.
  - Content: Includes standard DFHack commands like `help`, `ls`, `fpause`, and version string `DFHack version 53.15-r2 (release) on x86_64`.

## 2. Probe Execution Mechanics

Probes are executed using the `bonsai-df-probe` wrapper script, which encapsulates the DFHack runner.

- **VERIFIED**: The probe command structure is `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout <seconds> -- <dfhack_runner_path> <command>`.
  - Source: `tool_use` event with `callID`: `call_94wcfwpi`.
  - Command: `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help`.
- **VERIFIED**: The probe result is appended to the stdout as a JSON object prefixed with `BONSAI_PROBE_RESULT`.
  - Source: `output` field in `tool_use` event `call_94wcfwpi`.
  - Structure: `{"exit":0, "timed_out":false, "duration_seconds":0.008, "command":[...], "runtime_ready":true, "runtime":{...}}`.
- **VERIFIED**: The `runtime` field within the probe result mirrors the readiness state observed in step 1.
  - Source: Nested `runtime` object in `BONSAI_PROBE_RESULT`.
  - Values: `{"ready":true, "started":false, "attempts":1}`.

## 3. Harness Phases and Budget Exhaustion

The harness operates in distinct phases, each with its own tool budget constraints.

- **VERIFIED**: The `opencode` phase has a maximum tool use limit of 16.
  - Source: `harness_budget_exhausted` event for phase `opencode`.
  - Reason: `probe_deadline`.
- **VERIFIED**: The `live_game_probe_recovery` phase has a maximum tool use limit of 1.
  - Source: `harness_budget_exhausted` event for phase `live_game_probe_recovery`.
  - Reason: `tool_budget`.
- **INFERRED**: Budget exhaustion stops the current phase, triggering an `external_checkpoint` if applicable.
  - Source: Sequence of events showing `harness_budget_exhausted` followed by `external_checkpoint` in `opencode` phase.

## 4. Implications for Reset/Observe/Act/Advance

- **Reset**: Runtime readiness is checked before each probe. If `ready` is false, the system may attempt recovery (implied by `attempts` field).
- **Observe**: Probes provide a snapshot of runtime state via `BONSAI_PROBE_RESULT`. The `duration_seconds` metric allows for performance monitoring.
- **Act**: Commands are passed through to DFHack. The `exit` code in the probe result indicates success (0) or failure.
- **Advance**: Time advancement is not directly observed in this trace, but the `started: false` state suggests the game simulation may not be actively running during these readiness checks.

## 5. Coding Recommendations

1. **Parse Probe Results**: Always parse the `BONSAI_PROBE_RESULT` JSON from stdout to extract exit codes and timing metrics. Do not rely solely on shell exit codes.
2. **Handle Budget Limits**: Design probe sequences to respect phase-specific tool budgets. The `live_game_probe_recovery` phase is particularly constrained (1 tool use).
3. **Verify Readiness**: Check the `runtime.ready` field in probe results before assuming DFHack commands will execute successfully.
4. **Timeout Management**: Use appropriate timeouts for probes. The trace shows a 30-second timeout for simple commands like `help`.

## References

- Trace Event: `runtime_readiness` (phase: `ensure_runtime_ready`)
- Trace Event: `tool_use` (callID: `call_94wcfwpi`, command: `bonsai-df-probe ... help`)
- Trace Event: `harness_budget_exhausted` (phase: `opencode`, reason: `probe_deadline`)
- Trace Event: `harness_budget_exhausted` (phase: `live_game_probe_recovery`, reason: `tool_budget`)
