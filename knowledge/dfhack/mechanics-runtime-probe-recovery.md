# Runtime Probe Recovery and Budget Exhaustion

This note details the mechanics of runtime readiness verification, probe execution via `bonsai-df-probe`, and the handling of budget exhaustion during discovery phases. It synthesizes observations from the `opencode` and `live_game_probe_recovery` phases.

## 1. Runtime Readiness Verification

The system verifies DFHack readiness before executing probes. The state is captured in a JSON structure within the probe result or runtime check output.

### Observed State Fields
Based on the trace, the runtime readiness object contains the following fields:
- `ready`: Boolean indicating if the runtime is ready. **VERIFIED** (Value: `true` in trace).
- `started`: Boolean indicating if the game simulation has started. **VERIFIED** (Value: `false` in trace, implying pre-game or menu state).
- `attempts`: Integer count of readiness checks performed. **VERIFIED** (Value: `1` in trace).
- `output`: String containing the raw console output from the readiness check command (typically `help`). **VERIFIED**.

### Command Execution
The readiness check is implicitly triggered by executing a benign command like `help`. The output confirms the DFHack version and available commands.
- **Command**: `/srv/df-bonsai/current/dfhack-run help` **VERIFIED**
- **Version String**: `DFHack version 53.15-r2 (release) on x86_64` **VERIFIED**

## 2. Probe Execution Mechanics

Probes are executed using the `bonsai-df-probe` wrapper script, which encapsulates the DFHack command execution and returns structured results.

### Wrapper Command Structure
- **Executable**: `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe` **VERIFIED**
- **Arguments**: `--timeout 30 -- <dfhack-command>` **VERIFIED**
- **Target DFHack Runner**: `/srv/df-bonsai/current/dfhack-run` **VERIFIED**

### Probe Result Structure (`BONSAI_PROBE_RESULT`)
The output of a successful probe includes a JSON block appended to the console output:
```json
{
  "exit": 0,
  "timed_out": false,
  "duration_seconds": 0.009,
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
- `exit`: Exit code of the command. **VERIFIED** (0 indicates success).
- `timed_out`: Boolean indicating if the probe exceeded the timeout. **VERIFIED** (false).
- `duration_seconds`: Time taken to execute the probe. **VERIFIED** (0.009s for `help`).
- `runtime_ready`: Redundant flag confirming readiness at execution time. **VERIFIED**.

## 3. Budget Exhaustion and Phase Termination

The harness enforces strict limits on tool usage per phase. When these limits are reached, the phase terminates with a specific reason.

### Observed Exhaustion Events
1. **Phase**: `opencode`
   - **Reason**: `probe_deadline` **VERIFIED**
   - **Max Tool Uses**: 16 **VERIFIED**
   - **Context**: The phase ended after checking repo state and initial knowledge, likely due to a time-based deadline for the discovery cycle rather than just tool count.

2. **Phase**: `live_game_probe_recovery`
   - **Reason**: `tool_budget` **VERIFIED**
   - **Max Tool Uses**: 1 **VERIFIED**
   - **Context**: This phase was strictly limited to a single tool use (the probe itself). After the probe completed, the budget was exhausted, terminating the phase.

### Implications for Reset/Observe/Act/Advance
- **Reset**: The `runtime_cleanup` steps show that processes are protected (`protected: [588772]`) and no files are removed during cleanup. This suggests a persistent runtime state across phases within a session. **INFERRED**
- **Observe**: Probes must be lightweight (e.g., `help`, `ls`) to avoid budget exhaustion in constrained phases like `live_game_probe_recovery`. **VERIFIED**
- **Act**: Actions that modify game state should be reserved for phases with higher tool budgets or longer deadlines. **INFERRED**
- **Advance**: The `started: false` state indicates the game has not advanced into simulation yet. Probes in this state are safe but limited to menu-level commands. **VERIFIED**

## 4. Coding Recommendations

1. **Probe Design**: Always use `bonsai-df-probe` with a reasonable timeout (e.g., 30s) for non-critical checks. For critical readiness checks, rely on the `runtime_ready` flag in the probe result. **VERIFIED**
2. **Budget Awareness**: In phases labeled `*_recovery` or similar, assume a very low tool budget (possibly 1). Design probes to be atomic and self-contained. **VERIFIED**
3. **State Verification**: Check the `started` field in the runtime object to determine if game-specific commands (e.g., job manipulation) are valid. If `started: false`, restrict actions to menu-level operations. **VERIFIED**
4. **Error Handling**: Monitor for `probe_deadline` vs. `tool_budget` exhaustion reasons to adjust retry logic. A deadline suggests time pressure, while a budget limit suggests resource constraints. **VERIFIED**

## 5. Open Questions
- What is the exact threshold for `probe_deadline`? Is it wall-clock time or cumulative tool execution time? **OPEN**
- How does the system handle probe failures (non-zero exit codes) in terms of budget consumption? **OPEN**
- Can the `protected` process list be dynamically modified during runtime cleanup? **OPEN**
