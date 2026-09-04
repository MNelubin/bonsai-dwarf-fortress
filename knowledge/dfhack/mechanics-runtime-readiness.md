# Runtime Readiness and Probe Recovery

## Scope

This note documents the verified mechanics for establishing runtime readiness in Dwarf Fortress 53.15 with DFHack 53.15-r2 within the DF-Bonsai LXC environment. It details the successful probe path using `bonsai-df-probe` and contrasts it with failed direct execution attempts.

## Verified Runtime Readiness Probe [VERIFIED]

A successful runtime readiness check was executed during the `live_game_probe_recovery` phase. The command used the trusted wrapper to invoke DFHack's help system, confirming connectivity and version status without initiating a full game simulation loop.

**Command:**
```bash
/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help
```

**Result Analysis:**
The probe returned a `BONSAI_PROBE_RESULT` JSON object with the following verified fields:
- `exit`: 0 (Success)
- `timed_out`: false
- `duration_seconds`: 0.007
- `runtime_ready`: true
- `runtime.started`: false (Indicates DFHack is connected but no fortress simulation is actively running/loaded in the session context, or the game is paused/idle at startup).
- `runtime.attempts`: 1

**Output Content:**
The stdout contained the standard DFHack help text:
```
Here are some basic commands to get you started:
  help|?|man         - This text.
  help <tool>        - Usage help for the given plugin, command, or script.
  tags               - List the tags that the DFHack tools are grouped by.
  ls|dir [<filter>]  - List commands, optionally filtered by a tag or substring.
                       Optional parameters:
                         --notags: skip printing tags for each command.
                         --dev:  include commands intended for developers and modders.
  cls|clear          - Clear the console.
  fpause             - Force DF to pause.
  die                - Force DF to close immediately, without saving.
  keybinding         - Modify bindings of commands to in-game key shortcuts.

See more commands by running 'ls'.

DFHack version 53.15-r2 (release) on x86_64
```

This confirms that `dfhack-run` is the correct entry point for RPC-style command execution and that the runtime environment is responsive.

## Failed Direct Execution Paths [VERIFIED]

Previous attempts to execute Lua directly via CLI arguments failed or were unsafe:
1. **Direct `dwarfort -- lua -e`**: Processes remained alive with high CPU usage (up to 756% summed across multiple instances) and produced no terminal result. This is classified as [OPEN] for success but [VERIFIED] as a failure mode for autonomous jobs due to resource exhaustion and lack of termination signals.
2. **RPC Lua Injection**: Passing `lua <code>` strings directly to the RPC client was rejected with "is not a recognized command". [VERIFIED]

## Implications for Reset/Observe/Act/Advance

1. **Reset**: To reset state, rely on `dfhack-run die` or process management via the wrapper's SIGKILL capability if the game hangs. Do not use direct binary kills without cleanup.
2. **Observe**: Use `dfhack-run <command>` for all state queries. The `help` command serves as a lightweight heartbeat probe. Complex state observation requires specific DFHack plugins (e.g., `lua`, `json`) invoked through this runner, not raw CLI args.
3. **Act/Advance**: Actions must be queued via supported DFHack commands. Time advancement should use `fpause` or specific tick-advance commands if available, rather than relying on the game loop to run freely, which risks CPU spikes observed in failed probes.

## Coding Recommendations

1. **Always Use Wrapper**: All autonomous interactions must go through `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe` with a timeout (e.g., 30s).
2. **Check `runtime_ready`**: Parse the `BONSAI_PROBE_RESULT` JSON. If `runtime_ready` is false, retry or escalate. If `started` is false, the game may need initialization before complex queries.
3. **Avoid Raw Lua CLI**: Do not attempt `dwarfort -- lua -e`. Use DFHack's internal Lua execution capabilities via `dfhack-run` if supported by specific plugins, or stick to native DFHack commands.
4. **Resource Monitoring**: Monitor for high CPU usage associated with `dwarfort` processes. If a probe hangs, the wrapper's SIGKILL mechanism is the only reliable recovery path.
5. **State Verification**: Before acting, verify runtime readiness with a lightweight command like `help` or `ls` to ensure the DFHack bridge is active and responsive.
