from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_RUNTIME_ROOT = Path("/srv/df-bonsai/current")
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
MAX_OUTPUT_BYTES = 128 * 1024
ALLOWED_ENTRY_POINTS = {"dfhack-run", "dwarfort"}


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


def run_guarded_probe(
    command: list[str],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
) -> dict[str, object]:
    executable = _allowed_executable(command, runtime_root)
    timeout_seconds = min(MAX_TIMEOUT, max(1.0, float(timeout_seconds)))
    normalized = [str(executable), *command[1:]]
    started = time.monotonic()
    process = subprocess.Popen(
        normalized,
        cwd=runtime_root.resolve(),
        env={
            **os.environ,
            "DISPLAY": "",
            "SDL_VIDEODRIVER": "dummy",
            "HOME": "/srv/df-bonsai/state/home",
        },
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
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one allowlisted Dwarf Fortress probe with a hard process-group timeout."
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        result = run_guarded_probe(command, timeout_seconds=args.timeout)
    except (OSError, ValueError) as exc:
        result = {
            "exit_code": 125,
            "timed_out": False,
            "duration_seconds": 0.0,
            "output": str(exc),
            "command": command,
        }
    output = str(result["output"])
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    marker = {
        "exit": result["exit_code"],
        "timed_out": result["timed_out"],
        "duration_seconds": result["duration_seconds"],
        "command": result["command"],
    }
    print("BONSAI_PROBE_RESULT " + json.dumps(marker, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(int(result["exit_code"]))


if __name__ == "__main__":
    main()
