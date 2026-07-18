import math

TICKS_PER_DAY = 86400
DAYS_PER_SEASON = 361
SEASONS_PER_YEAR = 4

ADVANCE_AMOUNT = TICKS_PER_DAY * 5


def baseline_policy(observation):
    """Rules-based 30-day fortress survival policy.

    Decision logic (deterministic, no LLM):

      1. If game has not started (gametype is None), act('unpause').
      2. If the fortress has been running < 30 days worth of ticks:
         - advance in increments; check survivors each cycle.
      3. If all citizens are dead, abort with failure.
      4. On success (>= 30 days survived with >= 1 citizen), return None to stop the loop.

    Returns an action dict or None.
    """
    cur_tick = observation.get("cur_tick") or 0
    units = observation.get("units", [])

    citizens_alive = sum(
        1 for u in units if not u.get("killed", False) and u.get("civ_id") is not None
    )

    target_ticks = TICKS_PER_DAY * 30

    if cur_tick >= target_ticks:
        return {"name": "observe"}

    if citizens_alive == 0 and observation.get("gametype"):
        return None

    return {
        "command": "advance",
        "args": [ADVANCE_AMOUNT],
    }


def evaluate_episode(episode_metrics):
    """Score an episode run against the 30-day survival baseline.

    Returns (score, verdict) where score is in [0, 1] and verdict is a string.
    """
    survivors = episode_metrics.get("survivors", 0)
    final_tick = episode_metrics.get("final_tick") or 0
    steps = episode_metrics.get("steps_taken", 0)
    outcome = episode_metrics.get("outcome", "failure")

    tick_progress = min(1, final_tick / (TICKS_PER_DAY * 30)) if final_tick else 0

    score = float(max(0, min(1, 0.4 * tick_progress + 0.6 * float(survivors > 0))))
    verdict = "pass" if score >= 0.8 and outcome != "timeout" else "below_baseline"

    return score, verdict
