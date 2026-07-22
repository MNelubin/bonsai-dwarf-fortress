# Mechanics: Help Command Overview (DFHack 53.15‑r2)

## Observation (VERIFIED)

- **DFHack version** is `53.15-r2` (release) on architecture `x86_64` (source: bash probe output, command `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help`).
- **Runtime readiness** returned `ready: true`, `started: false`, `attempts: 1` (cited from JSON of type `runtime_readiness`).
- **Help command output** lists the following primary commands: `help|?|man`, `help <tool>`, `tags`, `ls|dir`, `cls|clear`, `fpause`, `die`, `keybinding`. These exact strings were captured in the probe output and in the initial runtime output.

## Probe Result (VERIFIED)

The probe "bonsai-df-probe" executed with `--timeout 30` reported:

```json
{
  "exit": 0,
  "timed_out": false,
  "duration_seconds": 0.007,
  "command": ["/srv/df-bonsai/releases/df-53.15-steam-23622201_dfhack-53.15-r2/dfhack-run","help"],
  "runtime_ready": true,
  "runtime": {
    "ready": true,
    "started": false,
    "attempts": 1,
    "output": "\u001b[0mHere are some basic commands to get you started:\n  help|?|man         - This text.\n  help <tool>        - Usage help for the given plugin, command, or script.\n  tags               - List the tags that the DFHack tools are grouped by.\n  ls|dir [<filter>]  - List commands, optionally filtered by a tag or substring.\n                       Optional parameters:\n                         --notags: skip printing tags for each command.\n                         --dev:  include commands intended for developers and modders.\n  cls|clear          - Clear the console.\n  fpause             - Force DF to pause.\n  die                - Force DF to close immediately, without saving.\n  keybinding         - Modify bindings of commands to in-game key shortcuts.\n\nSee more commands by running 'ls'.\n\n\u001b[0mDFHack version 53.15-r2 (release) on x86_64\n\u001b[0m"
  },
  "required": true
}
```

The JSON is sourced directly from the `BONSAI_PROBE_RESULT` block in the trace.

## Inferred Implications (INFERRED)

- Because `runtime.started == false`, any subsequent `dfhack` actions must first **reset** or **launch** the DF process; attempting to read world data without starting would fail.
- The presence of `fpause` indicates that resetting the world while paused can be achieved without terminating the DF binary, useful for safe observation cycles.
- The `die` command suggests an **emergency reset** is possible by forcing a shutdown without saving; this can be used to clear state between experiments.

## Open Questions (OPEN)

- The exact effect of each tag filter for `ls|dir` (e.g., `--notags`, `--dev`) on command discovery has not been exercised.
- Whether the `help <tool>` output changes after the runtime has been started is unobserved.

## Recommendations (Concrete Coding)

1. **Runtime guard**: Before invoking any probe, check `runtime.ready && runtime.started` as verified above; abort if not ready.
2. **Probe wrapper**: Capture the `BONSAI_PROBE_RESULT` block, log `duration_seconds` for latency budgeting, and branch on `exit != 0`.
3. **Command catalog**: Store the help list in a static table keyed by command name; reference this when constructing `act` scripts to avoid re‑probing.
4. **Reset strategy**: Use `fpause` followed by an external world reset to transition from `started:false` to a known state; avoid `die` unless a full discard is intended.
5. **Error handling**: The attempted `read` of `mechanics-pause.md` and `mechanics-units.md` failed; implement a `fallback_read` that creates a placeholder note when a file is missing.
