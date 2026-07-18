"""Episode runner for headless DF episodes via the bridge contract."""

import copy
import hashlib
import json
import os
import subprocess
import uuid

# Path to the active DFHack installation.
DF_DIR = "/srv/df-bonsai/current"
BRIDGE_LUA = os.path.join(os.path.dirname(__file__), "..", "bridge", "core.lua")

HASHID_BYTES = 8


def _deterministic_seed(seed):
    """Produce a deterministic byte sequence from an integer seed."""
    return hashlib.sha256(str(seed).encode()).digest()[:HASHID_BYTES]


def _simulate_citizens(seed, num_citizens=4):
    """Create citizen unit dict list deterministically from seed.

    Uses SHA256(bytes) as a primitive RNG: each citizen gets 4 random ints for id, race and civ_id fields.
    Returns a tuple (list_of_unit_dicts, threshold_for_first_death_ticks).
    """
    d = _deterministic_seed(seed)
    offset = 0

    units = []
    for i in range(num_citizens):
        # Simple LCG style from our hash bytes.
        h = int.from_bytes(d[offset:offset + 4], "little") if offset + 4 <= len(d) else seed
        b_offset = (i * 2 + offset) % HASHID_BYTES
        raw_id = d[b_offset] if b_offset < len(d) else 0
        race_id = (raw_id + i) % 5
        civ_id_val = ((raw_id >> 3) & 31) + 1

        units.append({
            "id": 200000 + i * 100 + raw_id,
            "race": race_id,
            "civ_id": civ_id_val,
            "killed": False,
            "pos": [i * 3, i, 0],
        })

    # Survival ticks based on seed — determines at what tick a stress event occurs.
    # We use the same seed to compute how many ticks until the first simulated death.
    survival_hash = _deterministic_seed(seed + 1)
    first_death_ticks = int.from_bytes(survival_hash, "little") % (86400 * 30) + 86400 * 5

    return units, first_death_ticks


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

    def __init__(self, save_id=None, max_steps=100, action_budget=50, seed=42, num_citizens=4):
        self.save_id = save_id or str(uuid.uuid4())[:8]
        self.max_steps = max_steps
        self.action_budget = action_budget
        self.seed = seed
        self.num_citizens = num_citizens
        self.metrics = {}
        self.trace = []
        self._obs_state = None
        self.units, self.death_ticks = _simulate_citizens(self.seed, self.num_citizens)

    # ------------------------------------------------------------------
    def reset(self):
        """Reset episode state before run."""
        self.metrics = {"seed": self.seed, "steps_taken": 0, "actions_used": 0}
        self.trace = []
        self.units, self.death_ticks = _simulate_citizens(self.seed, self.num_citizens)
        self._obs_state = _default_observation()
        # Units in obs_state reference the same dicts as self.units so
        # stress event mutations are visible to subsequent observations.
        self._obs_state["units"] = [dict(u) for u in self.units]
        return True

    # ------------------------------------------------------------------
    def _stub_observe(self):
        """Internal observation state shared by advance and the loop.

        Units always read from self.units so stress mutations are visible.
        """
        if self._obs_state is None:
            self._obs_state = _default_observation()
        # Sync citizen state (killed flags, etc.) to internal slot.
        self._obs_state["units"] = [dict(u) for u in self.units]
        return self._obs_state

    # ------------------------------------------------------------------
    def observe(self):
        """Thin wrapper around bridge.observe() — stub for headless use."""
        s = self._stub_observe()
        result = {**s}
        result["units"] = [dict(u) for u in s["units"]]
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
    def _process_stress_events(self):
        """Mark dead citizens whose death threshold has been crossed."""
        current_tick = self._stub_observe()["cur_tick"]
        for unit in self.units:
            if not unit["killed"] and current_tick >= self.death_ticks:
                # Deterministic death: only kill units whose id's last digit
                # is <= (current_tick - death_ticks) // (86400 * 3). This spreads deaths.
                days_past = (current_tick - self.death_ticks) // 86400
                if unit["id"] % 10 <= min(days_past, 9):
                    unit["killed"] = True

    # ------------------------------------------------------------------
    def advance(self, ticks=100):
        """Advance N game ticks — stub incrementing internal counter."""
        state = self._stub_observe()
        state["cur_tick"] += ticks
        state["tick"] += 1
        self.metrics["final_tick"] = (self.metrics.get("final_tick") or 0) + ticks
        self._process_stress_events()
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
    def save_checkpoint(self, path):
        """Write a full episode snapshot to *path* for later restoration.

        Parameters:
            path: filesystem path (file or directory).  If the path is an
                  existing directory a file named ``<save_id>.checkpoint.json``
                  will be created inside it.
        Returns:
            Normalized absolute path that was written.
        """
        payload = self.serialize()
        if os.path.isdir(path):
            dest = os.path.join(path, f"{self.save_id}.checkpoint.json")
        else:
            dest = path

        # Ensure parent directory exists.
        parent = os.path.dirname(dest) or "."
        os.makedirs(parent, exist_ok=True)

        with open(dest, "w") as fp:
            json.dump(payload, fp, indent=2)

        return os.path.abspath(dest)

    @classmethod
    def load_checkpoint(cls, path):
        """Restore an EpisodeRunner from a previously written checkpoint file.

        Parameters:
            path: filesystem path to a ``.checkpoint.json`` file created by
                  ``save_checkpoint()``.  May also be a directory in which case
                  the first ``*.checkpoint.json`` file inside will be used.
        Returns:
            Deserialized EpisodeRunner instance at the saved evaluation point.
        """
        if os.path.isdir(path):
            files = [f for f in os.listdir(path) if f.endswith(".checkpoint.json")]
            if not files:
                raise FileNotFoundError(
                    f"No *.checkpoint.json found inside {path}"
                )
            path = os.path.join(path, sorted(files)[0])

        with open(path) as fp:
            payload = json.load(fp)

        return cls.deserialize(payload)

    # ------------------------------------------------------------------
    def serialize(self):
        """Return a JSON-serializable dict of the complete episode state.

        Includes runner configuration so that `deserialize()` can
        reconstruct an identical EpisodeRunner for replay or comparison.
        """
        return {
            "seed": self.seed,
            "save_id": self.save_id,
            "max_steps": self.max_steps,
            "action_budget": self.action_budget,
            "num_citizens": self.num_citizens,
            "metrics": copy.deepcopy(self.metrics),
            "trace": copy.deepcopy(self.trace),
        }

    @classmethod
    def deserialize(cls, state_dict):
        """Reconstruct an EpisodeRunner from a serialized snapshot.

        Returns the runner with metrics and trace restored to the saved
        point so that `run()` can continue from the checkpoint.
        """
        runner = cls(
            save_id=state_dict["save_id"],
            max_steps=state_dict["max_steps"],
            action_budget=state_dict["action_budget"],
            seed=state_dict["seed"],
            num_citizens=state_dict.get("num_citizens", 4),
        )
        runner.metrics = copy.deepcopy(state_dict["metrics"])
        runner.trace = copy.deepcopy(state_dict["trace"])
        runner.units, runner.death_ticks = _simulate_citizens(
            state_dict["seed"], state_dict.get("num_citizens", 4)
        )
        runner._obs_state = _default_observation()
        runner._obs_state["units"] = [dict(u) for u in runner.units]
        return runner

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
        survivors = sum(1 for u in self.units if not u["killed"] and u["civ_id"] is not None)

        self.metrics["survivors"] = survivors
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
