"""Statistical, format-independent gameplay scorer for headless DF episodes.

Calibrated 2026-07-24. The DF fort sim is NOT bit-reproducible (intrinsic engine
render/logic thread concurrency; see memory bonsai-real-scorer-plan), so scoring
is STATISTICAL by design — K episodes per policy, a robust median, a
distribution-free confidence interval, and a trust gate. This is the correct
formulation for a stochastic game: a good policy must perform well over the
DISTRIBUTION of random events (wildlife, later monsters/sieges), not on one
lucky run. The same code works for any format; harsher formats just need larger K.

Only observables shown EMPIRICALLY σ≈0 across independent reload+advance episodes
are scored:
    cohort survival, hunger, thirst, food, drink, buildings, dug tiles, workorders.
Excluded as noisy: raw wildlife/unit counts, total item count, raw stress sum.
Stress enters ONLY as a coarse threshold (count of dwarves in a danger band),
which calibration showed is 0/stable even though the raw sum swings ~40%.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
import math

# Fort mode runs ~1200 ticks per in-game day (empirically confirmed: cur_year_tick
# advances 1:1 with world.frame_counter). NOTE: bridge/core.lua + player/*.py carry
# a legacy TICKS_PER_DAY=86400 bug being fixed in a separate task; do not import it.
TICKS_PER_DAY = 1200

# Development is the discriminating axis (7 dwarves don't starve in 30 days, so
# survival alone can't separate policies); survival stays a hard multiplicative gate.
DEFAULT_WEIGHTS = {
    "provisioning": 0.30,  # food + drink stocks adequate for pop over horizon
    "comfort": 0.20,       # low hunger/thirst timers (dwarves kept fed/watered)
    "development": 0.50,   # dug tiles + completed workorders + built workshops
}

# A dwarf's stress above this counts as "in danger" (coarse, robust to the raw-sum
# noise). Per-dwarf stress in a healthy fort sits well below this in every episode.
STRESS_DANGER_THRESHOLD = 100_000

# Calibrated per-horizon endpoints for normalized_score() — the median RAW composite
# of a do-nothing controller (baseline, scores 0) and a competent reference (ceiling,
# scores 1). Measured LIVE (full format, wildlife ON) via live_episode.calibrate_*.
# no-op is σ≈0 across episodes (scored surface is deterministic); ref is filled once
# the reference policy (action verbs) exists. Horizons are fort-days*1200 ticks.
# Endpoints are keyed by (SAVE, horizon), not by horizon alone. A fort's no-op composite
# is a property of that fort: measured live on 2026-09-05, doing nothing on the mature
# region3-lab scored 0.176 against these pinned-save endpoints, because a mature fort
# keeps working without being told to. Scoring one save against another save's endpoints
# measures the wrong world - and regime_key already recorded scenario and save_sha256
# while the lookup ignored both.
CALIBRATION = {
    # Re-measured 2026-07-30 under the STEPPED driver (interaction model B) with the
    # development signals working, on the pinned bonsaifort2 save under DF 53.15. The
    # previous table was taken under the one-shot driver against a metric whose
    # development term was structurally 0 for every agent, so its endpoints were
    # measuring provisioning drift and nothing else - every rung had the same +0.055 gap
    # regardless of horizon, which is exactly the fingerprint of a dead component.
    #
    # The gap now GROWS with the horizon, as it should: more time is more fort to
    # build. Reference is a plain competent policy (mine steadily, keep stockpiles,
    # staff the labours), deliberately not an optimal one, so 1.0 stays reachable.
    #
    #                          no-op      reference   gap     ref dug/buildings
    ("bonsaifort2", 3600):  {"noop": 0.267857, "ref": 0.344119},   # 0.076   18 / 7
    ("bonsaifort2", 12000): {"noop": 0.278571, "ref": 0.381475},   # 0.103   64 / 7
    ("bonsaifort2", 36000): {"noop": 0.337346, "ref": 0.456135},   # 0.119   86 / 8
}

DEFAULT_SAVE = "bonsaifort2"


def calibration_for(save, horizon_ticks):
    """Endpoints for one fort at one horizon, or None if that pair was never measured.

    Refusing is the point. An uncalibrated pair must yield `uncalibrated_horizon` rather
    than a number computed against another fort's baseline, because such a number looks
    exactly like a real score and is not one.
    """
    return CALIBRATION.get((save or DEFAULT_SAVE, int(horizon_ticks)))


@dataclass(frozen=True)
class EpisodeObs:
    """Ground-truth observables sampled by the trusted evaluator (never agent-reported).

    Sourced from hack/scripts/bonsai-observe.lua at a fixed, fully-quiesced tick.
    All fields are DFHack ground truth the controller cannot forge.
    """
    abs_tick: int              # cur_year*1e6 + cur_year_tick; horizon boundary check
    cohort_alive: int          # of the pinned T0 citizen id-set, how many are alive
    cohort_size: int           # |T0 citizen id-set| (denominator; immune to migrants)
    hunger_sum: int            # sum of citizen hunger_timer (lower = better fed)
    thirst_sum: int            # sum of citizen thirst_timer (lower = better watered)
    stress_danger: int         # of cohort, how many have stress > STRESS_DANGER_THRESHOLD
    food_count: int            # fort food items (excl. corpses/remains)
    drink_count: int           # fort drink items
    buildings: int             # workshops/stockpiles etc. (development)
    dug_tiles: int             # tiles dug since T0 (development)
    workorders_done: int       # manager order units completed since T0 (development)


def _sat(timer_sum: int, cohort_size: int, horizon_ticks: int) -> float:
    """Provisioning-comfort satisfaction in [0,1]: 1.0 = perfectly fed/watered.

    hunger/thirst timers climb when a need is unmet. Normalize the per-dwarf mean
    timer against the horizon length (the worst case is a dwarf hungry the whole
    episode). Higher timer -> lower satisfaction.
    """
    if cohort_size <= 0 or horizon_ticks <= 0:
        return 0.0
    mean_timer = timer_sum / cohort_size
    return max(0.0, 1.0 - mean_timer / horizon_ticks)


def raw_components(obs: EpisodeObs, t0: EpisodeObs, horizon_ticks: int,
                   weights: dict | None = None) -> dict:
    """Compute per-episode score components (all pre-normalization, ordered so a
    better policy scores higher). Returns a dict incl. a `composite` raw score and
    the multiplicative `survival_gate`."""
    w = weights or DEFAULT_WEIGHTS

    # --- survival gate (hard multiplier): fraction of the T0 cohort still alive ---
    denom = t0.cohort_size if t0.cohort_size > 0 else 1
    survival = obs.cohort_alive / denom
    if obs.cohort_alive < t0.cohort_size:
        # any death is heavily penalized (survival is the load-bearing outcome)
        survival *= (obs.cohort_alive / denom)

    # --- provisioning: food + drink stock adequacy (per dwarf) ---
    need = max(1, t0.cohort_size)
    food_adeq = min(1.0, obs.food_count / (need * 2))     # ~2 food/dwarf buffer
    drink_adeq = min(1.0, obs.drink_count / (need * 2))
    provisioning = 0.5 * (food_adeq + drink_adeq)

    # --- comfort: dwarves kept fed/watered (low hunger/thirst) ---
    comfort = 0.5 * (_sat(obs.hunger_sum, t0.cohort_size, horizon_ticks)
                     + _sat(obs.thirst_sum, t0.cohort_size, horizon_ticks))
    # a dwarf in the stress danger band zeroes comfort credit for that dwarf
    if t0.cohort_size > 0:
        comfort *= max(0.0, 1.0 - obs.stress_danger / t0.cohort_size)

    # --- development: what the fort actually produced/built/dug ---
    dug = max(0, obs.dug_tiles - t0.dug_tiles)
    orders = max(0, obs.workorders_done - t0.workorders_done)
    builds = max(0, obs.buildings - t0.buildings)
    # soft-saturating so a huge dig doesn't dwarf everything else
    development = (_sat_pos(dug, 200) + _sat_pos(orders, 20) + _sat_pos(builds, 10)) / 3.0

    composite = survival * (
        w["provisioning"] * provisioning
        + w["comfort"] * comfort
        + w["development"] * development
    )
    return {
        "survival_gate": survival,
        "provisioning": provisioning,
        "comfort": comfort,
        "development": development,
        "composite": composite,
    }


def _sat_pos(x: float, scale: float) -> float:
    """Saturating map of a non-negative quantity into [0,1); scale = the value that
    reaches ~0.5. Rewards progress with diminishing returns."""
    if x <= 0:
        return 0.0
    return x / (x + scale)


def normalized_score(obs: EpisodeObs, t0: EpisodeObs, horizon_ticks: int,
                     noop_composite: float, ref_composite: float,
                     weights: dict | None = None) -> float:
    """Baseline-subtracted score in [0,1]: (agent - noop) / (ref - noop).

    noop_composite / ref_composite are calibrated per horizon (median raw composite
    of a do-nothing controller and a competent reference controller). Ensures
    inaction scores ~0 and the reference ~1; agents are placed on that axis.
    """
    raw = raw_components(obs, t0, horizon_ticks, weights)["composite"]
    span = ref_composite - noop_composite
    if span <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, (raw - noop_composite) / span))


# ---------------------------------------------------------------------------
# K-run aggregation: robust median + distribution-free CI + trust gate.
# ---------------------------------------------------------------------------

# Rank pairs (lo, hi) giving an ~90% confidence interval for the median via the
# binomial order-statistic method, indexed by sample size n. Deterministic — no
# bootstrap RNG, which matters for a TRUSTED evaluator (reproducible verdicts).
_MEDIAN_CI_RANKS = {
    3: (0, 2), 4: (0, 3), 5: (0, 4), 6: (0, 5), 7: (1, 5),
    8: (1, 6), 9: (2, 7), 10: (2, 8), 11: (2, 9), 12: (3, 9),
}


@dataclass(frozen=True)
class RunStats:
    n: int
    median: float
    mad: float           # median absolute deviation (robust spread)
    ci_low: float
    ci_high: float

    @property
    def ci_half(self) -> float:
        return (self.ci_high - self.ci_low) / 2.0


def aggregate(scores: list[float]) -> RunStats:
    """Aggregate K per-episode scores into a robust median + distribution-free CI."""
    n = len(scores)
    if n == 0:
        return RunStats(0, 0.0, 0.0, 0.0, 0.0)
    s = sorted(scores)
    med = median(s)
    mad = median([abs(x - med) for x in s]) if n > 1 else 0.0
    if n < 3:
        # too few runs to bound; CI spans the observed range (untrustworthy-wide)
        return RunStats(n, med, mad, s[0], s[-1])
    lo_i, hi_i = _MEDIAN_CI_RANKS.get(n, (0, n - 1))
    hi_i = min(hi_i, n - 1)
    return RunStats(n, med, mad, s[lo_i], s[hi_i])


@dataclass(frozen=True)
class Comparison:
    trustworthy: bool
    winner: str          # "A", "B", or "tie"
    delta: float         # median(A) - median(B)
    noise_band: float    # ci_half(A) + ci_half(B)
    reason: str


def compare(a: RunStats, b: RunStats, label_a: str = "A", label_b: str = "B") -> Comparison:
    """Decide whether A beats B trustworthily: the median gap must exceed the
    combined CI half-widths. Otherwise the comparison is UNTRUSTWORTHY (raise K)."""
    delta = a.median - b.median
    band = a.ci_half + b.ci_half
    if a.n < 3 or b.n < 3:
        return Comparison(False, "tie", delta, band,
                          f"too few runs (nA={a.n}, nB={b.n}); need >=3 each")
    if abs(delta) <= band:
        return Comparison(False, "tie", delta, band,
                          f"|delta|={abs(delta):.3f} <= noise band={band:.3f}: UNTRUSTWORTHY, raise K")
    winner = label_a if delta > 0 else label_b
    return Comparison(True, winner, delta, band,
                      f"{winner} wins: |delta|={abs(delta):.3f} > noise band={band:.3f}")
