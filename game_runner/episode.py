"""Episode runner for headless DF episodes via the bridge contract."""

import copy
import json
import os
import subprocess
import uuid

# Path to the active DFHack installation.
DF_DIR = "/srv/df-bonsai/current"
BRIDGE_LUA = os.path.join(os.path.dirname(__file__), "..", "bridge", "core.lua")


def _default_observation():
    """Fresh observation state matching the contracts.json observe output."""
    return {
        "version": "1.0",
        "gametype": None,
        "cur_year": 0,
        "cur_season": 0,
        "cur_tick": 0,
        "paused": True,
        "units": [],
        "buildings": [],
        "tick": 0,
        "source": "stub",
    }


def _dfhack_run(lua_code, timeout=30):
    """Execute a Lua snippet via the DFHack CLI runner and return JSON."""
    env = {**os.environ, "HOME": "/srv/df-bonsai/state/home"}
    try:
        proc = subprocess.run(
            [os.path.join(DF_DIR, "hack", "dfhack-run"), "-q", lua_code],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=DF_DIR,
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
        self._obs_state = None

    # ------------------------------------------------------------------
    def reset(self):
        """Reset episode state before run."""
        self.metrics = {"seed": self.seed, "steps_taken": 0, "actions_used": 0}
        self.trace = []
        self._obs_state = _default_observation()
        return True

    # ------------------------------------------------------------------
    def _stub_observe(self):
        """Internal observation state shared by advance and the loop."""
        if self._obs_state is None:
            self._obs_state = _default_observation()
        return self._obs_state

    # ------------------------------------------------------------------
    def observe(self):
        """Thin wrapper around bridge.observe() — stub for headless use."""
        s = self._stub_observe()
        result = {**s}
        result["units"] = list(s["units"])
        result["buildings"] = list(s["buildings"])
        return result

    # ------------------------------------------------------------------
    def act(self, action):
        """Dispatch one action via bridge.act() — stub processing advances."""
        cmd = action.get("command", "") or action.get("name", "")
        state = self._stub_observe()

        if cmd == "unpause":
            state["paused"] = False
            state["gametype"] = "df.game_type.DWARF_FORTRESS"
            return {"ok": True, "message": "unpaused"}
        elif cmd == "advance":
            args = action.get("args", []) or []
            tick_amount = int(args[0]) if args else 100
            self.advance(tick_amount)
            return {"ok": True, "message": f"advanced {tick_amount} ticks"}
        elif cmd == "pause":
            state["paused"] = True
            return {"ok": True, "message": "paused"}
        elif cmd == "observe":
            return {"ok": True, "output": self.observe()}
        else:
            return {"ok": False, "message": f"stub_unknown_cmd:{cmd}"}

    # ------------------------------------------------------------------
    def advance(self, ticks=100):
        """Advance N game ticks — stub incrementing internal counter."""
        state = self._stub_observe()
        state["cur_tick"] += ticks
        state["tick"] += 1
        self.metrics["final_tick"] = (self.metrics.get("final_tick") or 0) + ticks
        return {"ok": True, "advanced_ticks": ticks}

    # ------------------------------------------------------------------
    def get_trace(self):
        """Return a deep copy of the episode trace for external inspection."""
        return copy.deepcopy(self.trace)

    # ------------------------------------------------------------------
    def to_json(self):
        """Serialize full episode state (metrics + trace) to JSON string."""
        payload = {
            "seed": self.seed,
            "save_id": self.save_id,
            "metrics": self.metrics,
            "trace": self.trace,
        }
        return json.dumps(payload, indent=2)

    # ------------------------------------------------------------------
    def run(self, action_policy):
        """Execute the full episode loop.

        Parameters:
            action_policy: callable(observation) -> action_dict | None
        """
        self.reset()
        if callable(getattr(action_policy, '_reset', None)):
            action_policy._reset()
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


def evaluate_multiple_runs(run_metrics_list):
    """Aggregate metrics across multiple episode runs.

    Parameters:
        run_metrics_list: list of dicts matching episode output contract.

    Returns a dict with aggregate statistics and worst-run metrics.
    """
    n = len(run_metrics_list)
    if n == 0:
        return {
            "runs": 0,
            "mean_score": 0.0,
            "median_score": 0.0,
            "worst_score": 0.0,
            "best_score": 0.0,
            "pass_rate": 0.0,
            "worst_run": None,
        }

    from player.baseline import evaluate_episode

    scored = []
    for m in run_metrics_list:
        score, _ = evaluate_episode(m)
        scored.append((score, m))

    scores = [s for s, _ in scored]
    passed = sum(1 for s in scores if s >= 0.8)

    sorted_scores = sorted(scores)
    median_idx = n // 2
    median = (sorted_scores[median_idx - 1] + sorted_scores[median_idx]) / 2 if n % 2 == 0 else sorted_scores[median_idx]

    worst_scored = min(scored, key=lambda x: x[0])
    best_scored = max(scored, key=lambda x: x[0])

    return {
        "runs": n,
        "mean_score": sum(scores) / n,
        "median_score": median,
        "worst_score": worst_scored[0],
        "best_score": best_scored[0],
        "pass_rate": passed / n,
        "worst_run": worst_scored[1],
        "best_run": best_scored[1],
    }
