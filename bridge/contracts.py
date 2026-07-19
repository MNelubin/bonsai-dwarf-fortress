"""Bridge contracts, validation helpers, and deterministic episode logging.

Provides the JSON contract schema for reset/observe/act/advance, field-level
type validators that enforce *contracts.json*, and an EpisodeLogger class that
records every action, observation hash, and game tick for reproducible runs.
"""

import copy
import datetime
import hashlib
import json
import math
import operator
import os
from collections import OrderedDict

_CONTRACTS_PATH = os.path.join(os.path.dirname(__file__), "contracts.json")

with open(_CONTRACTS_PATH) as _f:
    CONTRACT_SCHEMA = json.load(_f)


# ---------------------------------------------------------------------------
# Deterministic episode logger
# ---------------------------------------------------------------------------

class EpisodeLogger:
    """Record seeds, actions, ticks, and outcomes for deterministic replay.

    Usage in episode loop::

        logger = EpisodeLogger(seed=42, save_id="abc123")
        # ... inside run loop
        logger.log_action(step, action)
        logger.log_tick(cur_tick)
        # ... after run completes
        logger.finalize(outcome, survivors, final_tick)
        report = logger.as_dict()       # full structured dict
        json_bytes = logger.to_json()   # compact JSON bytes
        fingerprint = logger.fingerprint()  # SHA-256 digest of the run

    All methods are deterministic given identical input sequences.
    """

    def __init__(self, seed=None, save_id=None):
        self.seed = seed
        self.save_id = save_id
        self._actions_log = []
        self._tick_log = []
        self._outcome = None
        self._survivors = None
        self._final_tick = None
        self._started_at = datetime.datetime.now(datetime.UTC)

    # -- logging calls -------------------------------------------------

    def log_action(self, step, action):
        """Append *action* dict to the ordered action log.

        ``step`` is an integer index; the action is stored as a JSON-safe
        deepcopy to protect against in-place mutation from downstream code.
        """
        self._actions_log.append({
            "step": step,
            "command": action.get("command") if isinstance(action, dict) else None,
            "args": copy.deepcopy(action.get("args", [])) if isinstance(action, dict) else [],
        })

    def log_tick(self, tick):
        """Record the current game tick value."""
        self._tick_log.append(int(tick) if tick is not None else 0)

    def finalize(self, outcome, survivors=0, final_tick=0):
        """Mark the episode as complete with terminal metrics.

        Parameters:
            outcome: one of ``success``, ``failure``, ``timeout``.
            survivors: number of living citizens at termination.
            final_tick: game tick count at end of episode.
        """
        self._outcome = str(outcome)
        self._survivors = int(survivors) if survivors is not None else 0
        self._final_tick = int(final_tick) if final_tick is not None else 0

    # -- output -------------------------------------------------------

    def as_dict(self):
        """Return the full structured report as a plain dict.

        Keys: ``seed_save_id_actions_ticks_outcome_survivors_final_tick_elapsed_ms``.
        """
        now = datetime.datetime.now(datetime.UTC)
        elapsed_ms = int((now - self._started_at).total_seconds() * 1000)
        return {
            "seed": self.seed,
            "save_id": self.save_id,
            "actions": copy.deepcopy(self._actions_log),
            "ticks": list(self._tick_log),  # shallow int copies are fine
            "outcome": self._outcome,
            "survivors": self._survivors,
            "final_tick": self._final_tick,
            "elapsed_ms": elapsed_ms,
        }

    def to_json(self):
        """Return compact JSON bytes of ``as_dict()``."""
        return json.dumps(self.as_dict(), separators=(",", ":")).encode("utf-8")

    def fingerprint(self):
        """Compute a SHA-256 hex digest unique to this logger state.

        The hash includes the canonicalised log, seed, outcome, survivors,
        and final tick -- but **not** wall-clock ``elapsed_ms``.  Two runs
        with identical seeds + action sequences must yield the same fingerprint.
        """
        payload = OrderedDict((
            ("seed", self.seed),
            ("actions", json.dumps(
                copy.deepcopy(self._actions_log), sort_keys=True)),
            ("outcome", self._outcome or ""),
            ("survivors", self._survivors or 0),
            ("final_tick", self._final_tick or 0),
        ))
        frozen = json.dumps(payload).encode("utf-8")
        return hashlib.sha256(frozen).hexdigest()

    def action_count(self):
        """Return number of logged actions."""
        return len(self._actions_log)

    def tick_delta(self):
        """Return total game ticks advanced (last − first in tick log)."""
        if len(self._tick_log) < 2:
            return 0
        return self._tick_log[-1] - self._tick_log[0]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_observe(obs):
    """Return True if obs conforms to the 'observe' contract shape.

    Checks required key presence, then validates field types against the
    schema definition for stricter conformance.
    """
    required = CONTRACT_SCHEMA["bridge_api"]["observe"]["output"]["required"]
    if not all(k in obs for k in required):
        return False
    props = CONTRACT_SCHEMA["bridge_api"]["observe"]["output"]["properties"]
    for key, spec in props.items():
        if key not in obs:
            continue
        val = obs[key]
        expected = spec.get("type")
        nullable = spec.get("nullable")
        if val is None and nullable:
            continue
        if val is None:
            return False
        if expected == "integer" and not isinstance(val, int):
            return False
        if expected == "string" and not isinstance(val, str):
            return False
        if expected == "boolean" and not isinstance(val, bool):
            return False
        if expected == "array" and not isinstance(val, list):
            return False
    return True


def validate_act_result(result):
    """Return True if result has the required (ok, message) fields."""
    return "ok" in result and "message" in result


def validate_episode_metrics(metrics):
    """Return True if episode output meets the contract schema."""
    fields = [
        "seed", "steps_taken", "final_tick", "survivors", "actions_used", "outcome"
    ]
    return all(f in metrics for f in fields)


def validate_episode_outcome(outcome):
    """Return True if outcome is one of the allowed contract values."""
    return outcome in {"success", "failure", "timeout"}


def validate_act_input(action):
    """Return True if action dict has a valid command field."""
    return isinstance(action, dict) and (
        "command" in action or "name" in action
    )


def validate_advance_result(result):
    """Return True if the advance result has the required 'ok' boolean."""
    return isinstance(result, dict) and isinstance(result.get("ok"), bool)
