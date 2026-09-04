# Runtime Probing and State Verification

This note documents the mechanics of verifying DFHack runtime readiness and executing probes within the DF-Bonsai environment, based on observed trace data.

## Target Versions
- **Dwarf Fortress**: 53.15 (Steam Build 23622201)
- **DFHack**: 53.15-r2 (release)

## Runtime Readiness Mechanics

### State Fields
The runtime readiness state is exposed via a JSON structure containing the following fields:
- `ready`: Boolean indicating if the DFHack bridge is initialized. [VERIFIED]
- `started`: Boolean indicating if the game simulation has begun. [VERIFIED]
- `attempts`: Integer count of initialization attempts. [VERIFIED]
- `output`: String containing the initial console output from DFHack. [VERIFIED]

### Observed Values
In the trace, a successful readiness check yielded:
```json
{
  "ready": true,
  "started": false,
  "attempts": 1,
  "output": "\u001b[0mHere are some basic commands to get you started:..."
}
```
This indicates that `ready: true` does not imply `started: true`. The game may be paused or in a pre-simulation state. [VERIFIED]

## Probe Execution and Results

### Command Structure
Probes are executed via the `bonsai-df-probe` wrapper, which invokes `dfhack-run` with specific arguments.
- **Executable Path**: `/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run` [VERIFIED]
- **Wrapper Path**: `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe` [VERIFIED]

### Result Format
The probe returns a `BONSAI_PROBE_RESULT` JSON object appended to the stdout.
- `exit`: Exit code (0 for success). [VERIFIED]
- `timed_out`: Boolean indicating timeout. [VERIFIED]
- `duration_seconds`: Float representing execution time. [VERIFIED]
- `command`: Array of strings representing the executed command. [VERIFIED]
- `runtime_ready`: Boolean mirroring the runtime state. [VERIFIED]

### Example Probe
Command: `help`
Result:
```json
{
  "exit": 0,
  "timed_out": false,
  "duration_seconds": 0.007,
  "command": ["/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run", "help"],
  "runtime_ready": true
}
```
[VERIFIED]

## Implications for Reset/Observe/Act/Advance

1. **Reset**: Before resetting, ensure `runtime.ready` is true to avoid connection errors. The trace shows `attempts: 1`, suggesting a single retry logic might be sufficient for initial connections, but robust code should handle retries. [INFERRED]
2. **Observe**: Observing state requires parsing the `BONSAI_PROBE_RESULT` JSON from stdout. The presence of ANSI escape codes (`\u001b[0m`) in the output suggests that raw console output must be cleaned or parsed carefully if extracting text data. [VERIFIED]
3. **Act**: Actions are sent via `dfhack-run`. The low latency (`0.007s` for `help`) indicates that simple commands are fast, but complex queries may vary. [VERIFIED]
4. **Advance**: Since `started: false` was observed even when `ready: true`, advancing time requires explicit commands (e.g., `advance`) after verifying readiness. Do not assume simulation progress upon connection. [INFERRED]

## Coding Recommendations

1. **Parse Probe Results**: Always parse the last line of stdout for `BONSAI_PROBE_RESULT` to determine success/failure and runtime state. Do not rely solely on exit codes. [VERIFIED]
2. **Handle ANSI Codes**: Strip ANSI escape sequences from DFHack output before processing text data. [VERIFIED]
3. **Check `started` State**: Explicitly check the `started` field in the runtime object to determine if the game simulation is active. [VERIFIED]
4. **Timeout Handling**: Use the `timed_out` flag in probe results to distinguish between command failures and network/bridge timeouts. [VERIFIED]
5. **Path Resolution**: Use the release-specific path for `dfhack-run` as observed in the trace, rather than assuming a static location. [VERIFIED]
