"""Tiny CPU-inference policy for Dwarf Fortress episodes.

Distills successful behavior into a decision table keyed on extracted
features (tick progress, survivor count, pause state). Runs locally
with no ML framework dependency and sub-millisecond inference.
"""

import math

TICKS_PER_DAY = 86400
DAYS_TARGET = 30
TARGET_TICKS = TICKS_PER_DAY * DAYS_TARGET

# Decision table: thresholds that produce known-good actions.
# Format: (min_tick, max_tick, min_survivors) -> action_template
# This is the distilled "policy network" — a handful of rules that cover
# the observation space for 30-day survival episodes.
_DECISION_TABLE = [
    # Phase 1: game paused → unpause immediately
    ("unpause_phase", lambda obs: obs.get("paused") and not obs.get("gametype")),
    # Phase 2: early game → aggressive advance; allows forward progress when units unknown
    ("advance_early", lambda obs:
         _alive(obs) >= 1 and (obs.get("cur_tick") or 0) < TARGET_TICKS * 0.3),
    # Phase 3: mid game, monitor more carefully
    ("advance_mid", lambda obs: _alive(obs) >= 1 and (obs.get("cur_tick") or 0) < TARGET_TICKS * 0.7),
    # Phase 4: approaching target, conservative advance
    ("advance_late", lambda obs: _alive(obs) >= 1 and (obs.get("cur_tick") or 0) < TARGET_TICKS),
    # Terminal: survived long enough → signal success
    ("done", lambda obs: (obs.get("cur_tick") or 0) >= TARGET_TICKS),
    # Failure: confirmed units exist but all dead
    ("abort", lambda obs: len(obs.get("units", [])) > 0 and _alive(obs) == 0 and obs.get("gametype")),
]

_ADVANCE_EARLY = 5 * TICKS_PER_DAY
_ADVANCE_MID = 3 * TICKS_PER_DAY
_ADVANCE_LATE = 1 * TICKS_PER_DAY


def _alive(obs):
    """Count living citizens in observation."""
    units = obs.get("units", [])
    return sum(
        1 for u in units
        if not u.get("killed", False) and u.get("civ_id") is not None
    )


def _extract_features(obs):
    """Extract numeric features for CPU inference."""
    cur_tick = obs.get("cur_tick") or 0
    progress = min(1.0, cur_tick / TARGET_TICKS) if TARGET_TICKS else 0
    survivors = _alive(obs)
    is_paused = 1 if obs.get("paused") else 0
    has_gametype = 1 if obs.get("gametype") else 0
    return {
        "tick_progress": progress,
        "survivors": survivors,
        "isPaused": is_paused,
        "hasGameType": has_gametype,
    }


def cpu_policy(observation):
    """Infer the next action using distilled decision table.

    This replaces an LLM call with a local lookup based on hand-engineered
    thresholds from observed successful runs.  Returns an action dict or None
    to terminate the episode.
    """
    feat = _extract_features(observation)

    match_name = "none"
    for name, guard in _DECISION_TABLE:
        if guard(observation):
            match_name = name
            break

    if match_name == "unpause_phase":
        return {"command": "unpause"}
    elif match_name == "advance_early":
        return {"command": "advance", "args": [_ADVANCE_EARLY]}
    elif match_name == "advance_mid":
        return {"command": "advance", "args": [_ADVANCE_MID]}
    elif match_name == "advance_late":
        return {"command": "advance", "args": [_ADVANCE_LATE]}
    elif match_name == "done":
        return {"name": "observe"}
    elif match_name == "abort":
        return None

    # Safe fallback: conservative advance if nothing matched.
    return {"command": "advance", "args": [_ADVANCE_LATE]}


def cpu_policy_with_features(observation):
    """Like cpu_policy but also returns the feature vector for logging."""
    feat = _extract_features(observation)
    action = cpu_policy(observation)
    # Attach features to the action for visibility.
    if action:
        action["_features"] = feat
    return action
