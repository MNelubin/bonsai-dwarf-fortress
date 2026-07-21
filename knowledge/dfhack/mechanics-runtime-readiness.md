---
title: Runtime Readiness and Probe Recovery
path: dfhack/mechanics-runtime-readiness.md
---

# Runtime Readiness and Probe Recovery

This note documents the mechanics of verifying DFHack runtime readiness, specifically focusing on the `runtime_readiness` phase and recovery procedures when probes fail or time out. It details the state transitions observed during initialization and the specific commands used to verify environment stability.

## 1. Runtime Readiness Verification

The system employs a `runtime_readiness` check to ensure the DFHack environment is stable before executing complex logic. This phase is critical for preventing race conditions where scripts might execute against an uninitialized or crashing game state.

### Observed State Fields
Based on the trace data from the `ensure_runtime_ready` phase, the following fields define the readiness state:

*   **`ready`**: Boolean indicating if the runtime is prepared. In the trace, this was `true` [VERIFIED].
*   **`started`**: Boolean indicating if the game simulation has actively begun. In the trace, this was `false` [VERIFIED], suggesting the world may be paused or in a pre-game menu state.
*   **`attempts`**: Integer count of initialization attempts. The trace shows `1` [VERIFIED].
*   **`output`**: Contains the raw console output from the DFHack help command, confirming version and available primitives [VERIFIED].

### Version Confirmation
The runtime explicitly reports:
> "DFHack version 53.15-r2 (release) on x86_64" [VERIFIED]

This confirms compatibility with Dwarf Fortress 53.15.

## 2. Probe Execution and Recovery

When the initial `opencode` phase exhausts its budget or encounters a deadline (`probe_deadline`), the system transitions to a `live_game_probe_recovery` phase. This mechanism ensures that transient failures do not permanently halt knowledge acquisition.

### Recovery Command Structure
The recovery process utilizes a specific probe command structure:
```bash
/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help
```
*   **Tool**: `bonsai-df-probe` [VERIFIED]
*   **Timeout**: 30 seconds [VERIFIED]
*   **Target Command**: `/srv/df-bonsai/current/dfhack-run help` [VERIFIED]

### Probe Result Analysis
The probe returns a structured JSON object `BONSAI_PROBE_RESULT` containing:
*   **`exit`**: 0 (Success) [VERIFIED]
*   **`timed_out`**: false [VERIFIED]
*   **`duration_seconds`**: 0.008 [VERIFIED]
*   **`runtime_ready`**: true [VERIFIED]
*   **`runtime`**: Nested object confirming `ready: true`, `started: false`, and `attempts: 1` [VERIFIED].

## 3. Implications for Reset/Observe/Act/Advance

### Reset
If `runtime_ready` is false or `timed_out` is true, the system should trigger a reset of the DFHack process rather than attempting further commands. The trace shows that even after a `probe_deadline`, the recovery probe succeeded quickly (0.008s), indicating the underlying runtime was likely stable but perhaps unresponsive to previous high-load operations.

### Observe
Observation scripts must check the `started` field. If `started` is false, game-state-dependent observations (e.g., unit positions, job queues) will return empty or invalid data. The trace confirms `started: false`, so any observation of game entities at this stage would be futile.

### Act
Actions should only be dispatched if `runtime_ready` is true. The presence of the `help` command output in the readiness check serves as a lightweight heartbeat. If this fails, higher-level actions are likely to fail.

### Advance
Time advancement commands (e.g., `advance`) should not be issued if `started` is false, as the game loop may not be active. The trace indicates the game is not started, so advancing time would have no effect or could cause errors.

## 4. Coding Recommendations

1.  **Pre-Flight Check**: Always execute a lightweight probe (e.g., `help`) before complex operations to verify `runtime_ready` and capture the current version string.
2.  **State Awareness**: Explicitly check the `started` field in the runtime metadata. If false, defer game-state observations until the simulation begins.
3.  **Recovery Logic**: Implement a retry mechanism with a timeout (e.g., 30s) for probe commands. If a probe times out, assume the runtime is hung and trigger a process reset rather than continuing to queue commands.
4.  **Version Pinning**: Validate that the reported DFHack version matches the expected target (53.15-r2) before executing version-specific Lua scripts or memory offsets.
5.  **Error Handling**: Parse the `BONSAI_PROBE_RESULT` JSON for `exit` codes. Non-zero exits should be treated as critical failures requiring immediate intervention.

## 5. Open Questions
*   What is the exact threshold for `attempts` before a hard reset is triggered? [OPEN]
*   Does `started: false` imply the game is in the main menu, or is it paused at tick 0? Further probing of the calendar state is required to distinguish these scenarios. [OPEN]
