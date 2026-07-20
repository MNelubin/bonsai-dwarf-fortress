# CLI Lua Execution and RPC Limitations

## Scope

This note records observed behavior for Dwarf Fortress 53.15 with DFHack 53.15-r2 in the
DF-Bonsai LXC. It supersedes the earlier claim that a high-CPU `dwarfort -- lua -e` process
proved successful Lua execution.

## RPC command behavior [VERIFIED]

Passing an arbitrary `lua <code>` string to the existing `dfhack-run` RPC client was rejected.

Observed stderr:

```text
lua local json=require('data-JSON');local g=df.global;... is not a recognized command.
Shutting down client connection.
```

This proves only that this command form is unsupported by the connected RPC command parser. It
does not prove that all DFHack RPC commands are unavailable.

## Direct `dwarfort` probes did not complete [VERIFIED]

Commands such as:

```bash
./dwarfort -- lua -e "local w=df.global.world; print(w.cur_year)"
./dwarfort --help
./dwarfort --version
```

remained alive with high CPU usage and produced no terminal result. On 2026-07-20 the lab contained
21 `dwarfort`/wrapper processes, 15 older than three hours and one about 19 hours old. Their summed
CPU usage was approximately 756%, and CT123 load average was 29.6 on 16 vCPUs.

Therefore:

- process existence or CPU usage is **not** evidence that injected Lua executed;
- the direct CLI Lua form is currently [OPEN], not VERIFIED;
- a timeout without a kill-after escalation is insufficient because `dwarfort` can ignore SIGTERM;
- short-lived direct `dwarfort` launches must not be used by autonomous jobs.

## Required bounded probe path [VERIFIED]

Autonomous jobs must use the trusted wrapper:

```bash
/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- \
  /srv/df-bonsai/current/dfhack-run <dfhack-command>
```

The wrapper:

1. accepts only `dfhack-run` or `dwarfort` from `/srv/df-bonsai/current`;
2. runs from the actual game directory;
3. places the command in a separate process group;
4. sends SIGTERM at the deadline and SIGKILL after a short grace period;
5. emits a terminal `BONSAI_PROBE_RESULT` containing exit status, timeout state, duration, and command.

A failed wrapper result is useful evidence when stdout/stderr contains a precise blocker. Merely
observing a still-running process is not a completed probe.

## Design implications

- **Observe/act/advance:** prefer supported DFHack commands over arbitrary RPC Lua injection.
- **Persistent bridge:** arbitrary live state access still requires a controlled persistent DFHack
  bridge or plugin; repeatedly starting the full game is not an acceptable polling mechanism.
- **Evidence discipline:** record exact wrapper output and keep uncertain API behavior tagged OPEN.
- **Generated logs:** root-level `errorlog.txt`, `gamelog.txt`, `stdout.log`, and `stderr.log` produced
  by a probe are runtime artifacts, not candidate implementation changes.

## Open questions

- Which existing DFHack command or plugin offers the smallest persistent state-query surface? [OPEN]
- Can a dedicated DFHack Lua script be invoked through a supported command without starting another
  game instance? [OPEN]
- What reset/observe/act/advance protocol should the persistent bridge expose first? [OPEN]
