"""Persistent DF session transport for the trusted evaluator.

Owns one live headless DF process (port 5001) and exposes it as a set of primitive
operations — observe, apply actions, advance N ticks — instead of one opaque
run-to-completion script. This is what makes interaction model B possible: the agent
controller can be re-invoked between chunks while the SAME fort keeps running.

Verified against the live server (2026-07-29 probe):
  * DF stays alive and responsive across many separate dfhack-run RPC calls
  * Lua globals persist between those calls (so a recorder can hold state in-engine)
  * one `dfhack-run` call is a full connect -> run -> disconnect cycle

Transport only — this module knows nothing about scoring or recording. The fragile
boot/load/prep sequence stays in the battle-tested bonsai_session.sh.

INVARIANT: the supervised df-runtime DF on port 5000 is never touched. Our own boot
hangs without it (it provides the shared init environment).
"""

from __future__ import annotations

import os
import re
import subprocess
import time

DF_DIR = os.environ.get("BONSAI_DF_DIR", "/srv/df-bonsai/current")
SESSION_SH = os.path.join(DF_DIR, "bonsai_session.sh")
DFHACK_RUN = os.path.join(DF_DIR, "dfhack-run")   # wrapper: sets LD_LIBRARY_PATH, cds to DF_DIR
ADVANCE_N = os.path.join(DF_DIR, "advance_n.txt")
ACTIONS_FILE = os.path.join(DF_DIR, "agent_actions.txt")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_OBS_RE = re.compile(r"(\w+)=(\S+)")
_INT = re.compile(r"-?\d+")

# The project convention: every dfhack-run call is bounded. An unbounded call against
# a wedged DF hangs forever (observed 2026-07-29 against the unresponsive port-5000 DF).
RPC_TIMEOUT = int(os.environ.get("BONSAI_RPC_TIMEOUT", "25"))

# Advance polling. Measured 2026-07-29: one frame+pause RPC costs ~7ms, so polling
# finely is nearly free, while a coarse interval dominates the cost of small chunks.
POLL_MIN_INTERVAL = float(os.environ.get("BONSAI_POLL_MIN", "0.05"))
POLL_MAX_INTERVAL = float(os.environ.get("BONSAI_POLL_MAX", "0.5"))


class SessionError(RuntimeError):
    """DF session could not be established or has become unusable."""


class DFSession:
    """A live, loaded DF fort that accepts repeated commands.

    Use as a context manager — __exit__ guarantees the process is killed even if the
    episode raises, which is what keeps runaway DF instances (which have wedged this
    host before) from surviving a crash.
    """

    def __init__(self, *, port: int = 5001, df_dir: str = DF_DIR,
                 watchdog_seconds: int = 1800, save: str = "bonsaifort2"):
        self.port = port
        self.df_dir = df_dir
        self.watchdog_seconds = watchdog_seconds
        self.save = save
        self.booted = False
        self.boot_frame = 0

    # ---------------------------------------------------------------- lifecycle
    def __enter__(self) -> "DFSession":
        self.boot()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def boot(self, timeout: int = 300) -> None:
        """Boot DF, load the pinned save, prep it, and leave it paused and ready."""
        p = subprocess.run(
            ["bash", SESSION_SH, "boot", str(self.watchdog_seconds), self.save],
            capture_output=True, text=True, timeout=timeout, cwd=self.df_dir,
            env=self._env(),
        )
        out = _ANSI.sub("", p.stdout)
        if "READY" not in out:
            raise SessionError(f"boot failed: {(out + p.stderr)[-300:]}")
        self.booted = True
        # READY only means the load finished; the first RPC after it can still come
        # back empty (observed live: SessionError 'no number from frame_counter'
        # immediately after a successful boot). Retry rather than lose the session.
        for attempt in range(6):
            try:
                self.boot_frame = self.frame()
                return
            except SessionError:
                if attempt == 5:
                    raise
                time.sleep(2)

    def close(self) -> None:
        """Kill our DF (never the supervised one). Safe to call twice."""
        if not self.booted:
            return
        self.booted = False
        try:
            subprocess.run(["bash", SESSION_SH, "kill"], capture_output=True,
                           text=True, timeout=60, cwd=self.df_dir, env=self._env())
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _env(self) -> dict:
        return dict(os.environ, DFHACK_PORT=str(self.port))

    # ---------------------------------------------------------------- primitives
    def run(self, *args: str, timeout: int = RPC_TIMEOUT) -> str:
        """One dfhack-run RPC. Returns stdout with ANSI colour stripped."""
        try:
            p = subprocess.run([DFHACK_RUN, *args], capture_output=True, text=True,
                               timeout=timeout, cwd=self.df_dir, env=self._env())
        except subprocess.TimeoutExpired as e:
            raise SessionError(f"dfhack-run {args[0] if args else ''} timed out") from e
        return _ANSI.sub("", p.stdout)

    def lua(self, code: str, timeout: int = RPC_TIMEOUT) -> str:
        return self.run("lua", code, timeout=timeout)

    def getnum(self, expr: str) -> int:
        m = _INT.search(self.lua(f"print(({expr}))"))
        if not m:
            raise SessionError(f"no number from {expr!r}")
        return int(m.group())

    def frame(self) -> int:
        return self.getnum("df.global.world.frame_counter")

    def frame_and_paused(self) -> tuple[int, bool]:
        """Frame counter and pause state in ONE round trip (halves advance polling)."""
        out = self.lua("print(df.global.world.frame_counter, df.global.pause_state)")
        m = _INT.search(out)
        if not m:
            raise SessionError(f"bad frame/pause reply: {out[:120]!r}")
        return int(m.group()), ("true" in out.lower())

    # ---------------------------------------------------------------- operations
    def observe(self) -> dict:
        """Ground-truth observation via bonsai-observe.lua. Raises if DF went away."""
        for line in self.observe_raw().splitlines():
            if "OBS " in line:
                return dict(_OBS_RE.findall(line))
        raise SessionError("bonsai-observe produced no OBS line")

    def observe_raw(self) -> str:
        return self.run("bonsai-observe")

    def suppress_wildlife(self) -> None:
        self.run("bonsai-nowild")

    def apply_actions(self, actions: list[dict]) -> str:
        """Write sanitized intents and dispatch them deterministically.

        `actions` MUST already be allow-listed by the caller (game_scorer.sanitize_actions)
        — this layer is transport and does not police the agent.
        """
        with open(ACTIONS_FILE, "w") as f:
            for a in actions:
                args = a.get("args") or []
                if isinstance(args, dict):
                    args = list(args.values())
                f.write("\t".join([a["verb"], *[str(x) for x in args]]) + "\n")
        return self.run("bonsai-apply-actions")

    def advance(self, ticks: int, poll_timeout: int = 240) -> int:
        """Advance exactly `ticks` sim frames, then pause. Returns the new frame counter.

        bonsai-advance2.lua counts from the CURRENT frame_counter, so successive calls
        compose — that is what makes chunked advancing work.

        Polling starts fine and backs off. A flat 1s poll made EVERY advance cost ~1s
        regardless of size (measured 2026-07-29: advance(100) and advance(500) both took
        ~1.03s, i.e. entirely poll latency) — which at 24 rounds burned ~24s per episode
        of pure waiting. Each poll is a ~7ms RPC, so fine polling is nearly free.
        """
        if ticks <= 0:
            return self.frame()
        start = self.frame()
        target = start + ticks
        with open(ADVANCE_N, "w") as f:
            f.write(f"{ticks}\n")
        self.run("bonsai-advance2")
        deadline = time.time() + poll_timeout
        interval = POLL_MIN_INTERVAL
        while time.time() < deadline:
            fc, paused = self.frame_and_paused()
            if fc >= target and paused:
                return fc
            time.sleep(interval)
            interval = min(interval * 1.5, POLL_MAX_INTERVAL)
        raise SessionError(f"advance stalled: {self.frame()} < {target} after {poll_timeout}s")
