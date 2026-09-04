from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, cast


DEFAULT_RUNTIME_ROOT = Path("/srv/df-bonsai/current")
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
MAX_OUTPUT_BYTES = 128 * 1024
ALLOWED_ENTRY_POINTS = {"dfhack-run", "dwarfort"}
DEFAULT_RUNTIME_SERVICE = "bonsai-df-runtime.service"
DEFAULT_READY_TIMEOUT = 30.0
READY_POLL_SECONDS = 0.5
CommandRunner = Callable[..., subprocess.CompletedProcess[bytes]]


def _allowed_executable(command: list[str], runtime_root: Path) -> Path:
    if not command:
        raise ValueError("probe command is empty")
    root = runtime_root.resolve()
    executable = Path(command[0]).resolve()
    if executable.parent != root or executable.name not in ALLOWED_ENTRY_POINTS:
        raise ValueError(
            "probe executable must be /srv/df-bonsai/current/dfhack-run or dwarfort"
        )
    return executable


def _stop_group(process: subprocess.Popen[bytes], grace_seconds: float = 2.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=max(1.0, grace_seconds))


def _probe_environment() -> dict[str, str]:
    return {
        **os.environ,
        "DISPLAY": "",
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
        "HOME": "/srv/df-bonsai/runtime/home",
        "XDG_RUNTIME_DIR": "/srv/df-bonsai/runtime/xdg",
        "DFHACK_HEADLESS": "1",
        "DFHACK_DISABLE_CONSOLE": "1",
        "TERM": "dumb",
    }


def ensure_runtime_ready(
    *,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    service: str = DEFAULT_RUNTIME_SERVICE,
    timeout_seconds: float = DEFAULT_READY_TIMEOUT,
    command_runner: CommandRunner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Start the supervised DF runtime if needed and wait for local DFHack RPC."""
    root = runtime_root.resolve()
    client = (root / "dfhack-run").resolve()
    if client.parent != root or not client.is_file():
        return {
            "ready": False,
            "started": False,
            "attempts": 0,
            "error": f"missing trusted DFHack client: {client}",
        }

    timeout_seconds = min(MAX_TIMEOUT, max(1.0, float(timeout_seconds)))
    deadline = monotonic() + timeout_seconds
    attempts = 0
    last_output = ""

    def check() -> bool:
        nonlocal attempts, last_output
        attempts += 1
        try:
            result = command_runner(
                [str(client), "version"],
                cwd=root,
                env=_probe_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=min(5.0, timeout_seconds),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            last_output = repr(exc)
            return False
        last_output = result.stdout[-4096:].decode("utf-8", errors="replace")
        return result.returncode == 0

    if check():
        return {
            "ready": True,
            "started": False,
            "attempts": attempts,
            "output": last_output,
        }

    try:
        start = command_runner(
            ["/usr/bin/systemctl", "start", service],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ready": False,
            "started": False,
            "attempts": attempts,
            "error": f"failed to start {service}: {exc!r}",
            "output": last_output,
        }
    if start.returncode != 0:
        start_output = start.stdout[-4096:].decode("utf-8", errors="replace")
        return {
            "ready": False,
            "started": False,
            "attempts": attempts,
            "error": f"systemctl start {service} exited {start.returncode}",
            "output": start_output,
        }

    while monotonic() < deadline:
        sleep(READY_POLL_SECONDS)
        if check():
            return {
                "ready": True,
                "started": True,
                "attempts": attempts,
                "output": last_output,
            }
    return {
        "ready": False,
        "started": True,
        "attempts": attempts,
        "error": f"DFHack RPC was not ready within {timeout_seconds:.1f}s",
        "output": last_output,
    }


def run_guarded_probe(
    command: list[str],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    ready_timeout_seconds: float = DEFAULT_READY_TIMEOUT,
    readiness_check: Callable[..., dict[str, object]] = ensure_runtime_ready,
) -> dict[str, object]:
    executable = _allowed_executable(command, runtime_root)
    timeout_seconds = min(MAX_TIMEOUT, max(1.0, float(timeout_seconds)))
    normalized = [str(executable), *command[1:]]
    readiness: dict[str, object] = {
        "ready": True,
        "started": False,
        "attempts": 0,
        "required": executable.name == "dfhack-run",
    }
    if executable.name == "dfhack-run":
        readiness = readiness_check(
            runtime_root=runtime_root,
            timeout_seconds=ready_timeout_seconds,
        )
        readiness["required"] = True
        if readiness.get("ready") is not True:
            error = str(readiness.get("error") or "supervised DF runtime is unavailable")
            detail = str(readiness.get("output") or "")[-4096:]
            return {
                "exit_code": 126,
                "timed_out": False,
                "duration_seconds": 0.0,
                "output": "\n".join(part for part in (error, detail) if part),
                "command": normalized,
                "runtime": readiness,
            }
    started = time.monotonic()
    process = subprocess.Popen(
        normalized,
        cwd=runtime_root.resolve(),
        env=_probe_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    output = b""
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = exc.output or b""
        _stop_group(process)
        try:
            remainder, _ = process.communicate(timeout=2.0)
            output += remainder or b""
        except subprocess.TimeoutExpired:
            pass
    finally:
        _stop_group(process)
    duration = round(time.monotonic() - started, 3)
    return {
        "exit_code": 124 if timed_out else int(process.returncode or 0),
        "timed_out": timed_out,
        "duration_seconds": duration,
        "output": output[-MAX_OUTPUT_BYTES:].decode("utf-8", errors="replace"),
        "command": normalized,
        "runtime": readiness,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one allowlisted Dwarf Fortress probe with a hard process-group timeout."
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--ready-timeout", type=float, default=DEFAULT_READY_TIMEOUT)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        result = run_guarded_probe(
            command,
            timeout_seconds=args.timeout,
            ready_timeout_seconds=args.ready_timeout,
        )
    except (OSError, ValueError) as exc:
        result = {
            "exit_code": 125,
            "timed_out": False,
            "duration_seconds": 0.0,
            "output": str(exc),
            "command": command,
            "runtime": {"ready": False, "required": False},
        }
    output = str(result["output"])
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    runtime = cast(dict[str, object], result.get("runtime") or {})
    exit_code = result.get("exit_code")
    if not isinstance(exit_code, int):
        exit_code = 125
    marker = {
        "exit": exit_code,
        "timed_out": result["timed_out"],
        "duration_seconds": result["duration_seconds"],
        "command": result["command"],
        "runtime_ready": runtime.get("ready") is True,
        "runtime": runtime,
    }
    print("BONSAI_PROBE_RESULT " + json.dumps(marker, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
