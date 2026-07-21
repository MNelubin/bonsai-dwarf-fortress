# Runtime Probe Recovery and Budget Exhaustion

This note documents the behavior of the DFHack runtime readiness checks, probe execution mechanics, and budget exhaustion events observed during live game interaction attempts.

## Target Versions
- **Dwarf Fortress**: 53.15 (Steam Build 23622201)
- **DFHack**: 53.15-r2 (release)

## Runtime Readiness Verification

The runtime readiness check confirms the availability of the DFHack CLI interface before attempting complex probes.

### Observed Behavior
- **Command**: `help` executed via `dfhack-run`
- **Result**: Successful output listing basic commands (`help`, `tags`, `ls`, `cls`, `fpause`, `die`, `keybinding`).
- **Version String**: `DFHack version 53.15-r2 (release) on x86_64` [VERIFIED]
- **Readiness State**: The probe wrapper reports `runtime_ready: true` and `started: false` when the CLI is responsive but no fortress simulation is actively running or loaded in a way that triggers full initialization flags. [VERIFIED]

### Probe Metadata Structure
The `bonsai-df-probe` tool wraps DFHack commands and returns structured JSON metadata:
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
[VERIFIED]

## Budget Exhaustion and Recovery Phases

The research trace reveals two distinct phases where tool budgets were exhausted, preventing deeper investigation into Lua transport or calendar mechanics.

### Phase 1: Open Code Discovery
- **Phase**: `opencode`
- **Tool Profile**: `general`
- **Exhaustion Reason**: `probe_deadline`
- **Max Tool Uses**: 16
- **Observation**: The system attempted to list repository contents and check git status but did not proceed to deeper file inspection or DFHack Lua probing before the deadline. [VERIFIED]

### Phase 2: Live Game Probe Recovery
- **Phase**: `live_game_probe_recovery`
- **Tool Profile**: `implementation_only`
- **Exhaustion Reason**: `tool_budget`
- **Max Tool Uses**: 1
- **Observation**: Only a single readiness probe (`help`) was executed. No further state inspection (e.g., calendar, units, jobs) occurred due to immediate budget exhaustion. [VERIFIED]

## Implications for Reset/Observe/Act/Advance

1. **Readiness vs. Started State**: The runtime reports `ready: true` but `started: false`. This indicates that while the DFHack CLI is accessible, the game simulation may not be in a state where advanced queries (like unit lists or job queues) are valid or safe to execute without prior initialization steps.
2. **Budget Constraints**: Current tool budgets are insufficient for multi-step discovery. A single probe cycle cannot verify both runtime readiness and deep state inspection.
3. **Probe Timeout**: The `probe_deadline` exhaustion suggests that network or I/O latency in the initial phase consumed the available time budget before substantive commands could be issued.

## Coding Recommendations

1. **Pre-flight Check Optimization**: Ensure the `help` command is cached or skipped if runtime readiness is already confirmed by a previous successful connection, to save tool uses for actual state inspection.
2. **State Transition Verification**: Before issuing complex Lua queries, explicitly verify that `started: true` in the runtime metadata. If `started: false`, issue a `start` or equivalent initialization command first.
3. **Budget Allocation**: Increase `max_tool_uses` for `live_game_probe_recovery` phases to allow at least 3-5 probes: one for readiness, one for calendar/time state, and one for unit/job existence.
4. **Error Handling**: Implement retry logic for `probe_deadline` failures by reducing command complexity or increasing timeout thresholds in the probe wrapper configuration.

## Open Questions
- What specific DFHack commands are required to transition from `started: false` to `started: true`? [OPEN]
- Does the Lua transport require explicit initialization beyond CLI readiness? [OPEN]
- How does the `bonsai-df-probe` timeout interact with DFHack's internal command execution latency? [OPEN]
