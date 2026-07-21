# Live Game Probe Recovery Mechanics

This note documents the behavior of the `bonsai-df-probe` wrapper during runtime recovery phases, specifically focusing on version verification and state reporting when the game is not yet started.

## Target Versions
- **Dwarf Fortress**: 53.15 (Steam Build 23622201)
- **DFHack**: 53.15-r2 (release)

## Observed Behavior

### Probe Execution and Timing
During the `live_game_probe_recovery` phase, the probe command was executed with a timeout of 30 seconds:
```bash
/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help
```
- **Execution Time**: The probe completed in `0.007` seconds (`duration_seconds`: 0.007) [VERIFIED].
- **Exit Status**: Exit code `0` (success) [VERIFIED].
- **Timeout Status**: `timed_out: false` [VERIFIED].

### Runtime State Reporting
The probe output includes a JSON structure `BONSAI_PROBE_RESULT` containing runtime metadata:
- **Runtime Ready**: `true` [VERIFIED].
- **Game Started**: `false` [VERIFIED]. This indicates that while DFHack is loaded and responsive, the Dwarf Fortress simulation itself has not initialized or started.
- **Attempts**: `1` [VERIFIED]. The readiness check succeeded on the first attempt.

### DFHack Response Content
The `help` command returned standard DFHack help text, confirming the version:
> "DFHack version 53.15-r2 (release) on x86_64" [VERIFIED]

Key commands listed include:
- `fpause`: Force DF to pause.
- `die`: Force DF to close immediately without saving.
- `ls|dir`: List commands.

## Implications for Reset/Observe/Act/Advance

1. **Reset**: The runtime is considered "ready" even if the game hasn't started (`started: false`). This suggests that readiness checks should not block on simulation initialization but rather on DFHack availability.
2. **Observe**: Probes can successfully retrieve metadata and help text before the game starts. However, state-dependent probes (e.g., unit lists, job queues) will likely fail or return empty sets if `started` is false.
3. **Act**: Commands like `fpause` are available, but their effect may be null if the simulation isn't running. The `die` command is available for emergency cleanup.
4. **Advance**: Time advancement commands cannot be executed effectively until `started` becomes true.

## Coding Recommendations

1. **Check `started` Flag**: Before attempting to read game state (units, jobs, tiles), verify that the runtime report indicates `started: true`. If false, defer state-dependent operations.
2. **Handle Early Readiness**: Do not assume `runtime_ready: true` implies a playable simulation. Use the `started` field to distinguish between DFHack availability and game initialization.
3. **Timeout Configuration**: The probe completed in 7ms. A 30-second timeout is excessive for simple commands like `help`. Consider reducing timeouts for non-state-dependent probes to improve efficiency, but maintain higher timeouts for state-heavy queries.
4. **Error Handling**: Ensure that probes handle the case where `started` is false gracefully, avoiding errors from missing game objects.

## Uncertainties (OPEN)
- The exact trigger for transitioning `started` from `false` to `true` is not observed in this trace [OPEN].
- Whether `fpause` has any effect when `started` is false is unknown [OPEN].
