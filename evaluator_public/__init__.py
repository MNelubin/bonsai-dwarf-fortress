"""Public evaluator: deterministic scoring and batch metrics for DF episodes.

Provides a contract-compliant scorer that maps episode output to a normalized
score in [0, 1], plus aggregation over multiple runs with statistical
confidence bounds on worst-case performance.
"""

from bridge.contracts import CONTRACT_SCHEMA, validate_episode_metrics


# ---------------------------------------------------------------------------
# Constants — match the 30-day survival target
# ---------------------------------------------------------------------------
TICKS_PER_DAY      = 86400
DAYS_PER_SEASON    = 361
SEASONS_PER_YEAR   = 4
TARGET_DAYS        = 30
TARGET_TICKS       = TICKS_PER_DAY * TARGET_DAYS


# ---------------------------------------------------------------------------
# Score thresholds (percent of target ticks needed to survive)
# ---------------------------------------------------------------------------
SURVIVAL_BINS = [
    (1.0,  1.0),   # >= 100 %  → perfect
    (0.75, 0.85),  #  75-99 %  → above baseline
    (0.50, 0.60),  #  50-74 %  → partial progress
    (0.25, 0.30),  #  25-49 %  → low progress
    (0.01, 0.10),  #   1-24 %  → minimal effort
]

WEIGHT_TICK_PROGRESS = 0.4
WEIGHT_SURVIVORS     = 0.6
PASS_THRESHOLD       = 0.8


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------
def score_episode(metrics):
    """Score a single episode run.

    Parameters:
        metrics: dict conforming to bridge/contracts.json output_metrics.

    Returns:
        (score, verdict) — float in [0,1] and one of {pass, below_baseline, failed}.
    """
    if not validate_episode_metrics(metrics):
        return 0.0, "failed"

    final_tick  = metrics.get("final_tick") or 0
    survivors   = metrics.get("survivors", 0)
    outcome     = metrics.get("outcome", "failure")

    tick_progress = min(1.0, final_tick / TARGET_TICKS) if final_tick else 0.0
    survivor_bonus = WEIGHT_SURVIVORS if survivors > 0 else 0.0
    score = float(min(1.0, max(0.0,
                              WEIGHT_TICK_PROGRESS * tick_progress + survivor_bonus)))

    if score >= PASS_THRESHOLD and outcome != "timeout":
        verdict = "pass"
    elif score >= 0.5:
        verdict = "below_baseline"
    else:
        verdict = "failed"

    return round(score, 4), verdict


# ---------------------------------------------------------------------------
# Batch aggregation
# ---------------------------------------------------------------------------
def aggregate_runs(metrics_list):
    """Compute aggregate statistics over multiple episode runs.

    Returns a dict with keys:
        runs, mean_score, median_score, worst_score, best_score,
        pass_rate, failing_runs, worst_run, best_run, std_dev
    """
    n = len(metrics_list)
    if n == 0:
        return {
            "runs": 0,
            "mean_score": 0.0,
            "median_score": 0.0,
            "worst_score": 0.0,
            "best_score": 0.0,
            "pass_rate": 0.0,
            "failing_runs": [],
            "worst_run": None,
            "best_run": None,
            "std_dev": 0.0,
        }

    scored = []
    for m in metrics_list:
        score, _ = score_episode(m)
        scored.append((score, m))

    scores = [s for s, _ in scored]
    passed = sum(1 for s in scores if s >= PASS_THRESHOLD)

    sorted_scores = sorted(scores)
    mid = n // 2
    median = (sorted_scores[mid - 1] + sorted_scores[mid]) / 2 if n % 2 == 0 else sorted_scores[mid]

    mean_score = sum(scores) / n

    variance = sum((s - mean_score) ** 2 for s in scores) / max(1, n)
    std_dev = variance ** 0.5

    worst_scored = min(scored, key=lambda x: x[0])
    best_scored  = max(scored, key=lambda x: x[0])

    failing_runs = [m for s, m in scored if s < PASS_THRESHOLD]

    return {
        "runs": n,
        "mean_score": round(mean_score, 4),
        "median_score": round(median, 4),
        "worst_score": round(worst_scored[0], 4),
        "best_score": round(best_scored[0], 4),
        "pass_rate": round(passed / n, 4),
        "failing_runs": failing_runs,
        "worst_run": worst_scored[1],
        "best_run": best_scored[1],
        "std_dev": round(std_dev, 4),
    }


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------
def verify_trace_determinism(trace_a, trace_b):
    """Check two episode traces are identical.

    Returns:
        (ok, details) — ok is True when every step/action/result pair matches;
        details explains the first mismatch found.
    """
    if len(trace_a) != len(trace_b):
        return False, f"step count differs: {len(trace_a)} vs {len(trace_b)}"

    for i, (a, b) in enumerate(zip(trace_a, trace_b)):
        if a.get("action") != b.get("action"):
            return False, f"step {i} action differs"
        if a.get("result") != b.get("result"):
            return False, f"step {i} result differs"

    return True, "traces identical"


def contract_checksum(observation):
    """Compute a simple hash of an observation dict for determinism checks.

    Excludes the monotonic 'tick' counter intentionally so that bridge-level tick
    differences do not falsely report non-determinism.
    """
    import hashlib
    import json

    clean = {k: v for k, v in observation.items() if k != "tick"}
    frozen = json.dumps(clean, sort_keys=True)
    return hashlib.sha256(frozen.encode()).hexdigest()
