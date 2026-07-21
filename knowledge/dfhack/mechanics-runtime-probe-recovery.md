# Runtime Probe Recovery and Budget Exhaustion

This note details the observed behavior of runtime readiness checks, probe execution via `bonsai-df-probe`, and harness budget exhaustion events in Dwarf Fortress 53.15 with DFHack 53.15-r2.

## Runtime Readiness Verification

The system verifies runtime readiness before executing game logic probes. The trace indicates a successful readiness check during the `ensure_runtime_ready` phase.

- **Status**: Ready (`true`) [VERIFIED]
- **Game Started**: False (`false`) [VERIFIED]
- **Attempts**: 1 [VERIFIED]
- **Source Command Output**: The DFHack help text is returned, confirming the CLI is responsive. The output explicitly states: `DFHack version 53.15-r2 (release) on x86_64` [VERIFIED].

## Probe Execution and Result Structure

Probes are executed using the `bonsai-df-probe` wrapper tool. The trace shows a successful probe execution during the `live_game_probe_recovery` phase.

- **Command Executed**: `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help` [VERIFIED]
- **Exit Code**: 0 [VERIFIED]
- **Timeout Status**: `false` [VERIFIED]
- **Duration**: 0.008 seconds [VERIFIED]
- **Runtime Ready Flag**: `true` [VERIFIED]

The probe result includes a structured JSON payload (`BONSAI_PROBE_RESULT`) embedded in the stdout, which mirrors the runtime state:
```json
{
  "exit": 0,
  "timed_out": false,
  "duration_seconds": 0.008,
  "command": ["/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run", "help"],
  "runtime_ready": true,
  "runtime": {
    "ready": true,
    "started": false,
    "attempts": 1,
    "output": "...",
    "required": true
  }
}
```
This structure allows the harness to programmatically verify both the success of the command and the underlying runtime state [VERIFIED].

## Harness Budget Exhaustion

The trace records two instances of budget exhaustion, indicating limits on tool usage or time within specific phases.

1. **Opencode Phase**:
   - **Reason**: `phase_timeout` [VERIFIED]
   - **Max Tool Uses**: 16 [VERIFIED]
   - **Checkpoint**: `checkpoint-opencode.json` created with no changed paths [VERIFIED].

2. **Live Game Probe Recovery Phase**:
   - **Reason**: `tool_budget` [VERIFIED]
   - **Max Tool Uses**: 1 [VERIFIED]
   - This suggests a strict limit on the number of tools that can be invoked during recovery probes, likely to prevent infinite loops or excessive resource consumption during error handling [INFERRED].

## Implications for Reset/Observe/Act/Advance

- **Reset**: The `runtime_cleanup` steps show no processes were killed (`targets`: [], `sigkill`: []) and no files removed. This implies that readiness checks do not trigger a hard reset of the DF process if it is already responsive [VERIFIED].
- **Observe**: Probes are lightweight (0.008s) and return structured metadata alongside game output. Observations should parse the `BONSAI_PROBE_RESULT` JSON to determine runtime health before interpreting game state [VERIFIED].
- **Act/Advance**: Since `started` is `false`, the game world has not initialized. Actions that depend on in-game entities (units, jobs) will fail or return empty sets until a start command is issued and `started` becomes `true` [INFERRED].

## Coding Recommendations

1. **Parse Probe Results**: Always parse the `BONSAI_PROBE_RESULT` JSON from stdout when using `bonsai-df-probe`. Do not rely solely on exit codes, as the structured data provides critical runtime state (`ready`, `started`).
2. **Handle Budget Limits**: Implement logic to detect `tool_budget` exhaustion. If a recovery phase is limited to 1 tool use, ensure that single probe is comprehensive or that fallback mechanisms are defined outside the probe loop.
3. **Verify Runtime State Before Game Logic**: Check `runtime.started` before attempting to query game-specific structures (e.g., jobs, units). If `started` is `false`, queue actions for later or trigger a start sequence [INFERRED].
4. **Timeout Configuration**: The probe timeout was set to 30 seconds but completed in <1 second. For simple commands like `help`, lower timeouts may be sufficient, but complex queries may require higher limits. Monitor `duration_seconds` to optimize timeout settings [OPEN].
