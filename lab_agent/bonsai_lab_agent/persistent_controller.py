"""Long-lived controller process for the stepped episode driver.

`controller_invoke.make_controller_fn` spawns the agent's controller ONCE PER CALL.
That was fine for the one-shot setup model, but interaction model B asks the
controller ~24 questions per episode, and a fresh Python interpreter + repo import per
question costs far more than the decision itself.

The wire protocol is unchanged: the trusted `controller_host` already serves an
unbounded stdin loop (`for raw_line in sys.stdin: ... print(response, flush=True)`) —
it was only ever *used* one-shot. This module keeps that process alive for the whole
episode and exchanges one JSON line per round.

TRUST: the controller is untrusted code that now lives for minutes rather than
seconds. It is still just a pipe endpoint — it never touches DF, and every intent it
returns goes through `game_scorer.sanitize_actions` before dispatch. What changes is
the failure surface, so this module is deliberately paranoid:

  * a round that exceeds `round_timeout` is abandoned, the process is killed, and every
    later round degrades to no-op — a hung controller must not hang the evaluator
  * a crashed/exited process yields no-op rounds rather than an episode failure
  * stdout is read one line at a time in a reader thread, so a controller that prints
    nothing (or floods) cannot deadlock us on a full pipe
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from typing import Any, Callable

DEFAULT_ROUND_TIMEOUT = float(os.environ.get("BONSAI_CONTROLLER_ROUND_TIMEOUT", "30"))


class PersistentController:
    """One agent controller subprocess, kept alive across an episode's rounds.

    Use as a context manager; `__exit__` always reaps the process.
    """

    def __init__(self, command: list[str], repo: str, *,
                 round_timeout: float = DEFAULT_ROUND_TIMEOUT):
        self.command = command
        self.repo = repo
        self.round_timeout = round_timeout
        self.proc: subprocess.Popen | None = None
        self.dead = False
        self.rounds = 0
        self.failures: list[str] = []
        self._q: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    # ------------------------------------------------------------ lifecycle
    def __enter__(self) -> "PersistentController":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        try:
            self.proc = subprocess.Popen(
                self.command, cwd=self.repo,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except OSError as e:
            self._fail(f"spawn: {type(e).__name__}: {e}")
            return
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        """Drain stdout line by line so a chatty controller cannot block on a full pipe."""
        try:
            assert self.proc is not None and self.proc.stdout is not None
            for line in self.proc.stdout:
                self._q.put(line)
        except Exception:                             # noqa: BLE001
            pass
        finally:
            self._q.put(None)                         # EOF sentinel

    def close(self) -> None:
        self.dead = True
        p, self.proc = self.proc, None
        if p is None:
            return
        for step in (p.stdin and p.stdin.close, p.terminate, p.kill):
            try:
                if step:
                    step()
                p.wait(timeout=3)
                return
            except Exception:                         # noqa: BLE001
                continue

    def _fail(self, why: str) -> None:
        self.failures.append(why[:200])
        self.dead = True

    # ------------------------------------------------------------ one round
    def ask(self, observation: dict) -> list[dict]:
        """Send one observation, return the raw (unsanitized) action intents.

        Never raises. Once the controller has failed, every later round is a no-op —
        we do not resurrect it mid-episode, because a controller that died holding
        fort state would answer from a stale world.
        """
        if self.dead or self.proc is None:
            return []
        self.rounds += 1
        req = json.dumps({"type": "observation", "episode_id": "scored",
                          "step": self.rounds - 1, "observation": observation},
                         separators=(",", ":"), default=str)
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.write(req + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError, AssertionError) as e:
            self._fail(f"write round {self.rounds}: {type(e).__name__}")
            return []

        try:
            line = self._q.get(timeout=self.round_timeout)
        except queue.Empty:
            self._fail(f"round {self.rounds} timed out after {self.round_timeout}s")
            self.close()
            return []
        if line is None:
            self._fail(f"controller exited during round {self.rounds}")
            return []
        return _extract_actions(line)

    def stats(self) -> dict[str, Any]:
        return {"rounds": self.rounds, "dead": self.dead, "failures": self.failures}


def _extract_actions(line: str) -> list[dict]:
    """Parse one controller_host response line into a list of raw action intents.

    Accepts `{"action": {...}}`, `{"action": [ ... ]}` and `{"error": ...}`.
    """
    line = line.strip()
    if not line:
        return []
    try:
        resp = json.loads(line)
    except json.JSONDecodeError:
        return []
    if not isinstance(resp, dict) or resp.get("error"):
        return []
    a = resp.get("action")
    if isinstance(a, dict):
        return [a]
    if isinstance(a, list):
        return [x for x in a if isinstance(x, dict)]
    return []


def make_persistent_controller_fn(command: list[str], repo: str, *,
                                  round_timeout: float = DEFAULT_ROUND_TIMEOUT
                                  ) -> tuple[Callable[[dict], list[dict]], PersistentController]:
    """Return `(controller_fn, handle)` for the stepped driver.

    The handle exposes `.close()` and `.stats()` so the episode runner can reap the
    process and record why a controller stopped answering.
    """
    ctl = PersistentController(command, repo, round_timeout=round_timeout)
    ctl.start()
    return ctl.ask, ctl
