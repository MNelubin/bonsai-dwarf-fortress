"""Public evaluator: deterministic scoring and batch metrics for DF episodes.

Provides a contract-compliant scorer that maps episode output to a normalized
score in [0, 1], plus aggregation over multiple runs with statistical
confidence bounds on worst-case performance.
"""

import math

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
        pass_rate, failing_runs, worst_run, best_run, std_dev, confidence_interval_95
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
            "confidence_interval_95": (0.0, 0.0),
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

    # Approximate 95% confidence interval using Chebyshev's inequality bounds
    # For n runs: mean ± std_dev * sqrt(1 - alpha) / sqrt(n)
    # Using z=1.96 for normal approximation when n >= 30, else conservative fallback.
    ci = _confidence_interval_95(scores, std_dev, n)

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
        "confidence_interval_95": (round(ci[0], 4), round(ci[1], 4)),
    }


def _confidence_interval_95(scores, std_dev, n):
    """Compute a conservative 95% confidence interval for the mean.

    Uses standard error = std_dev / sqrt(n).  For small samples (n < 30)
    applies a Tukey-style adjustment: widens the half-width by 1 + 6/(n-1).
    Returns (lower, upper) both clamped to [0.0, 1.0].
    """
    if n <= 1 or std_dev == 0:
        return (scores[0] if scores else 0.0, scores[0] if scores else 0.0)

    se = std_dev / math.sqrt(n)
    z = 1.96
    adjustment = 1 + 6 / (n - 1) if n < 30 else 1.0
    half_width = z * se * adjustment
    lower = max(0.0, sum(scores) / n - half_width)
    upper = min(1.0, sum(scores) / n + half_width)
    return (lower, upper)


# ---------------------------------------------------------------------------
# Benchmarking helpers
# ---------------------------------------------------------------------------
def benchmark_runners(*runner_policies, num_runs=10, max_steps=100, action_budget=50):
    """Run a set of policies multiple times and return per-policy aggregates.

    Parameters:
        *runner_policies: tuples of (policy_name, policy_callable) or just callables.
        num_runs: how many seeded episodes to run per policy.
        max_steps/max_budget: passed through EpisodeRunner constructor.

    Returns:
        dict mapping policy name -> aggregate stats from `aggregate_runs()`.
    """
    from game_runner.episode import EpisodeRunner

    results = {}
    for item in runner_policies:
        if isinstance(item, tuple):
            name, policy = item
        else:
            name = getattr(policy, "__name__", "unnamed")  # noqa: F821
            policy = item

        metrics_list = []
        for i in range(num_runs):
            runner = EpisodeRunner(
                seed=i * 1000 + hash(name) % 100,  # Unique seeds per policy.
                max_steps=max_steps,
                action_budget=action_budget,
            )
            m = runner.run(policy)
            metrics_list.append(m)

        results[name] = aggregate_runs(metrics_list)

    return results


benchmark_runner = benchmark_runners


# ---------------------------------------------------------------------------
# Inference latency benchmarks (Milestone 6)
# ---------------------------------------------------------------------------
import time as _time


def measure_policy_latency(policy_callable, observation, n_warmup=5, n_bench=100):
    """Measure per-step inference latency for a policy function.

    Parameters:
        policy_callable: a policy(observation) -> action | None
        observation: sample observation dict used as input.
        n_warmup: warm-up calls (not measured).
        n_bench: benchmarked calls; time is averaged over these.

    Returns:
        mean_seconds (float): average inference time per step in seconds.
    """
    for _ in range(n_warmup):
        policy_callable(observation)

    start = _time.perf_counter()
    for _ in range(n_bench):
        policy_callable(observation)
    duration = _time.perf_counter() - start

    return duration / n_bench


def benchmark_inference_latency(*policies, sample_obs=None, n_warmup=5, n_bench=100):
    """Benchmark inference latency for multiple policies.

    Parameters:
        *policies: tuples of (name, callable) or bare callables.
        sample_obs: observation dict; if None a minimal stub is created.
        n_warmup, n_bench: passed to measure_policy_latency.

    Returns:
        dict mapping policy name -> mean inference seconds per step.
    """
    if sample_obs is None:
        sample_obs = {
            "version": "1.0",
            "gametype": "df.game_type.DWARF_FORTRESS",
            "cur_year": 1, "cur_season": 1,
            "cur_tick": 86400 * 5,
            "paused": False,
            "units": [
                {"id": i, "race": 0, "civ_id": 1, "killed": False, "pos": [0, 0, 0]}
                for i in range(4)
            ],
            "buildings": [],
            "tick": 10,
        }

    results = {}
    for item in policies:
        if isinstance(item, tuple):
            name, policy = item
        else:
            name = getattr(item, "__name__", "unnamed")
            policy = item
        latency = measure_policy_latency(policy, sample_obs, n_warmup, n_bench)
        results[name] = round(latency, 9)

    return results


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
