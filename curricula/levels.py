"""Curriculum definitions for progressive Dwarf Fortress training.

A curriculum is an ordered list of episodes with increasing difficulty.
Each entry specifies the policy, runner parameters, and success criteria.
"""

from player.baseline import baseline_policy
from player.cpu_policy import cpu_policy


# ---------------------------------------------------------------------------
# Curriculum level definitions
# ---------------------------------------------------------------------------

CURRICULUM_LEVELS = [
    {
        "name": "unpause_and_survive_1_day",
        "description": "Start game, survive 1 day.",
        "policy": baseline_policy,
        "max_steps": 50,
        "action_budget": 20,
        "target_days": 1,
        "min_survivors": 0,
    },
    {
        "name": "survive_7_days",
        "description": "Fortress survives one week.",
        "policy": baseline_policy,
        "max_steps": 50,
        "action_budget": 30,
        "target_days": 7,
        "min_survivors": 1,
    },
    {
        "name": "survive_30_days_baseline",
        "description": "Full 30-day survival with rules-based policy.",
        "policy": baseline_policy,
        "max_steps": 100,
        "action_budget": 50,
        "target_days": 30,
        "min_survivors": 1,
    },
    {
        "name": "survive_30_days_cpu",
        "description": "Full 30-day survival with CPU inference policy.",
        "policy": cpu_policy,
        "max_steps": 100,
        "action_budget": 50,
        "target_days": 30,
        "min_survivors": 1,
    },
]


def get_level(index):
    """Return curriculum level by index."""
    if 0 <= index < len(CURRICULUM_LEVELS):
        return CURRICULUM_LEVELS[index]
    raise IndexError(f"Level {index} not in range [0, {len(CURRICULUM_LEVELS)})")


def run_curriculum(runner_factory, evaluator):
    """Run all curriculum levels in order.

    Parameters:
        runner_factory: callable(level_dict) -> EpisodeRunner
        evaluator: callable(metrics_list) -> aggregate_dict

    Returns:
        List of (level_name, metrics, passed) tuples.
    """
    results = []
    for level in CURRICULUM_LEVELS:
        runner = runner_factory(level)
        metrics = runner.run(level["policy"])
        from player.baseline import TICKS_PER_DAY, evaluate_episode
        target_ticks = level["target_days"] * TICKS_PER_DAY
        score, verdict = evaluate_episode({
            **metrics,
            "final_tick": max(metrics.get("final_tick", 0), target_ticks) if metrics.get("survivors", 0) >= level["min_survivors"] else metrics.get("final_tick", 0),
        })
        passed = verdict == "pass" and metrics.get("survivors", 0) >= level["min_survivors"]
        results.append((level["name"], metrics, passed))
    return results
