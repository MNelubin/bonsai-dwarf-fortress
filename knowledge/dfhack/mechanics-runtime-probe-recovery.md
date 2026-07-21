# Runtime Probe Recovery and Budget Exhaustion

This note documents the mechanics of runtime readiness verification, probe execution via `bonsai-df-probe`, and the conditions leading to harness budget exhaustion in the DF-Bonsai environment.

## Target Versions
- **Dwarf Fortress**: 53.15 (Steam Build 23622201)
- **DFHack**: 53.15-r2 (release)

## Runtime Readiness Verification

The system verifies runtime readiness before executing probes. The state is captured in JSON metadata within probe results.

### Observed State Fields [VERIFIED]
Based on the `runtime_readiness` event and `BONSAI_PROBE_RESULT` output:
- **`ready`**: Boolean indicating if DFHack is responsive. Value: `true`.
- **`started`**: Boolean indicating if a fortress simulation has begun. Value: `false` (Title Screen/Menu state).
- **`attempts`**: Integer count of readiness checks. Value: `1`.
- **`runtime_ready`**: Top-level flag in probe result. Value: `true`.

### Probe Command Structure [VERIFIED]
The probe utility is located at `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe`. It wraps the DFHack runner.
- **Runner Path**: `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run`
- **Timeout**: Configurable via `--timeout` (e.g., 30 seconds).
- **Execution**: The probe executes commands like `help` to verify connectivity.

## Harness Budget and Exhaustion Mechanics

The research trace demonstrates two distinct phases of budget exhaustion, highlighting the constraints on tool usage during automated probing.

### Phase 1: OpenCode Discovery [VERIFIED]
- **Phase Name**: `opencode`
- **Tool Profile**: `general`
- **Max Tool Uses**: 16
- **Exhaustion Reason**: `probe_deadline`
- **Observation**: The harness terminated after discovering file structures (`game_runner`, `bridge`, `tests`) but before completing deeper analysis. The deadline constraint prevented further tool calls despite available budget.

### Phase 2: Live Game Probe Recovery [VERIFIED]
- **Phase Name**: `live_game_probe_recovery`
- **Tool Profile**: `implementation_only`
- **Max Tool Uses**: 1
- **Exhaustion Reason**: `tool_budget`
- **Observation**: The harness was strictly limited to a single tool use. It successfully executed one probe (`bonsai-df-probe ... help`) which returned success (`exit: 0`, `timed_out: false`). Immediately after this single successful call, the budget was exhausted.

## Implications for Reset/Observe/Act/Advance

1. **Readiness Check is Fast**: The readiness check completes in ~8ms (`duration_seconds": 0.008`). This suggests that `bonsai-df-probe` can be used as a lightweight health check without significant latency overhead.
2. **State Stability**: The runtime remained stable across phases. The `started: false` state persisted, indicating no simulation advancement occurred during the probe recovery phase.
3. **Budget Constraints are Hard Limits**: Agents must prioritize critical verification steps (like connectivity) in early phases if budget is tight (`tool_budget` exhaustion). Complex discovery tasks may fail due to `probe_deadline` even if tool count remains.

## Coding Recommendations

1. **Probe Wrapper Usage**: Always use `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe` for DFHack interactions to ensure proper timeout handling and result parsing.
2. **Check `runtime_ready`**: Before issuing complex commands, verify the `runtime_ready` flag in the probe result JSON. If `false`, retry or handle the error state.
3. **Budget Awareness**: In `implementation_only` profiles with low tool budgets (e.g., 1), execute only the most critical verification command (e.g., `help` or a specific status check) to confirm connectivity before assuming success.
4. **Path Resolution**: Use the release-specific path `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run` for direct DFHack execution if bypassing the probe wrapper is necessary (not recommended due to lack of timeout handling).

## Uncertainties [OPEN]
- The exact threshold for `probe_deadline` vs `tool_budget` exhaustion in mixed scenarios is not fully characterized.
- Whether `started: false` prevents certain job-related probes from returning valid data is unverified in this trace.
