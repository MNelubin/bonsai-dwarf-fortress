"""Episode runner for headless DF episodes via the bridge contract."""

import json
import subprocess
import tempfile
import os
import time
import uuid

# Path to the active DFHack installation.
DF_DIR = "/srv/df-bonsai/current"
BRIDGE_LUA = os.path.join(os.path.dirname(__file__), "..", "bridge", "core.lua")


def _dfhack_run(lua_code, timeout=30):
    """Execute a Lua snippet via the DFHack CLI runner and return JSON."""
    env = {**os.environ, "HOME": "/srv/df-bonsai/state/home"}
    try:
        proc = subprocess.run(
            ["python3", "-c", lua_code],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        return json.loads(proc.stdout.strip()) if proc.returncode == 0 else {
            "error": f"rc={proc.returncode}", "stderr": proc.stderr[:500]
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}


class EpisodeRunner:
    """Deterministic headless episode runner.

    Contract (from bridge/contracts.json):
      Each episode runs reset -> observe -> act* -> advance cycles against a
      pinned save, recording seed, steps, final_tick, survivors, and outcome.
    """

    def __init__(self, save_id=None, max_steps=100, action_budget=50, seed=42):
        self.save_id = save_id or str(uuid.uuid4())[:8]
        self.max_steps = max_steps
        self.action_budget = action_budget
        self.seed = seed
        self.metrics = {}
        self.trace = []

    # ------------------------------------------------------------------
    def reset(self):
        """Reset episode state before run."""
        self.metrics = {"seed": self.seed, "steps_taken": 0, "actions_used": 0}
        self.trace = []
        return True

    # ------------------------------------------------------------------
    def observe(self):
        """Thin wrapper around bridge.observe() — stub for headless use."""
        return {
            "version": "1.0",
            "gametype": None,
            "cur_year": 0,
            "cur_season": 0,
            "cur_tick": 0,
            "paused": True,
            "units": [],
            "buildings": [],
            "tick": len(self.trace),
            "source": "stub",
        }

    # ------------------------------------------------------------------
    def act(self, action):
        """Dispatch one action via bridge.act() — stub returning ok=False."""
        return {"ok": False, "message": "stub_no_liveldf"}

    # ------------------------------------------------------------------
    def advance(self, ticks=100):
        """Advance N game ticks — stub incrementing internal counter."""
        self.metrics["final_tick"] = (self.metrics.get("final_tick") or 0) + ticks
        return {"ok": True, "advanced_ticks": ticks}

    # ------------------------------------------------------------------
    def run(self, action_policy):
        """Execute the full episode loop.

        Parameters:
            action_policy: callable(observation) -> action_dict | None
        """
        self.reset()
        outcome = "success"

        for step in range(self.max_steps):
            if self.metrics["actions_used"] >= self.action_budget:
                outcome = "timeout"
                break

            obs = self.observe()
            action = action_policy(obs) if callable(action_policy) else None
            if not action:
                outcome = "success"
                break

            result = self.act(action)
            self.metrics["actions_used"] += 1
            self.trace.append({"step": step, "action": action, "result": result})
            self.metrics["steps_taken"] += 1

        final_tick = self.metrics.get("final_tick", self.observe()["cur_tick"])
        survivors = len(self.observe().get("units", []))

        return {
            "seed": self.seed,
            "save_id": self.save_id,
            "steps_taken": self.metrics["steps_taken"],
            "final_tick": final_tick,
            "survivors": survivors,
            "actions_used": self.metrics["actions_used"],
            "outcome": outcome,
        }
