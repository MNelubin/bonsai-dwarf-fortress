"""Live DF episode driver + scoring harness for the trusted evaluator.

Runs ON the DF host (CT123). Delegates the fragile boot/load/advance to the
battle-tested bash runner `bonsai_episode.sh` (keeps the supervised df-runtime DF
on port 5000 alive, runs the scored episode on 5001 with a watchdog, robust
verify-retry load), then parses its ground-truth OBS lines into EpisodeObs and
scores via metric.py.

FORMAT: wildlife/monsters ON by default (the real game). suppress_wildlife=True is
a deterministic DEBUG mode (zeroes the spawn pool) for regressioning the scorer.
Scoring is STATISTICAL: K episodes -> robust median + distribution-free CI + trust
gate (see metric.py); a good policy must win over the DISTRIBUTION of random events.
"""

from __future__ import annotations

import os
import re
import subprocess

from game_runner import metric
from game_runner.metric import EpisodeObs, raw_components, aggregate, compare

DF_DIR = os.environ.get("BONSAI_DF_DIR", "/srv/df-bonsai/current")
EPISODE_SH = os.path.join(DF_DIR, "bonsai_episode.sh")
_OBS_RE = re.compile(r"(\w+)=(\S+)")


def _parse_obs(line: str) -> dict:
    return dict(_OBS_RE.findall(line))


def _pair_to_obs(t0d: dict, hd: dict) -> tuple[EpisodeObs, EpisodeObs]:
    """Build the (T0, horizon) EpisodeObs pair, computing cohort survival from the
    intersection of the T0 citizen id-set with the horizon id-set (immune to
    migrants/births — the denominator is pinned to the T0 cohort)."""
    t0_ids = set(t0d.get("cids", "").split(",")) - {""}
    h_ids = set(hd.get("cids", "").split(",")) - {""}
    size = len(t0_ids)

    def mk(d: dict, alive: int, coh: int) -> EpisodeObs:
        return EpisodeObs(
            abs_tick=int(d.get("t", 0)),
            cohort_alive=alive, cohort_size=coh,
            hunger_sum=int(d.get("hsum", 0)), thirst_sum=int(d.get("tsum", 0)),
            stress_danger=int(d.get("strdang", 0)),
            food_count=int(d.get("nfood", 0)), drink_count=int(d.get("ndrink", 0)),
            buildings=int(d.get("nbuild", 0)), dug_tiles=int(d.get("dug", 0)),
            workorders_done=int(d.get("worders", 0)),
        )
    t0 = mk(t0d, size, size)
    h = mk(hd, len(t0_ids & h_ids), size)
    return t0, h


def run_episode(horizon_ticks: int, suppress_wildlife: bool = False,
                timeout: int = 300) -> tuple[EpisodeObs, EpisodeObs]:
    """Run one live episode via the canonical bash runner; return (T0, horizon) obs.
    Raises RuntimeError if the load failed (the caller skips it)."""
    p = subprocess.run(
        ["bash", EPISODE_SH, str(horizon_ticks), "1" if suppress_wildlife else "0"],
        capture_output=True, text=True, timeout=timeout, cwd=DF_DIR,
    )
    t0d = hd = None
    for line in p.stdout.splitlines():
        if "OBS_T0 OBS" in line:
            t0d = _parse_obs(line)
        elif "OBS_H OBS" in line:
            hd = _parse_obs(line)
    if not t0d or not hd:
        tail = (p.stdout + p.stderr)[-300:]
        raise RuntimeError(f"episode produced no OBS pair: ...{tail}")
    return _pair_to_obs(t0d, hd)


def run_k(horizon_ticks: int, k: int, suppress_wildlife: bool = False):
    """Run K live episodes; return list of (T0, horizon) EpisodeObs pairs (skipping
    episodes whose load failed)."""
    out = []
    for _ in range(k):
        try:
            out.append(run_episode(horizon_ticks, suppress_wildlife))
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
    return out


def score_pairs(pairs, horizon_ticks: int) -> list[float]:
    """Raw composite score for each (T0, horizon) pair (pre-normalization)."""
    return [raw_components(h, t0, horizon_ticks)["composite"] for t0, h in pairs]


def calibrate_noop(horizon_ticks: int, k: int = 5) -> float:
    """Median raw no-op composite at a horizon — the baseline endpoint for
    normalized_score(). Run once per horizon; store in metric CALIBRATION."""
    pairs = run_k(horizon_ticks, k, suppress_wildlife=False)
    comps = score_pairs(pairs, horizon_ticks)
    return aggregate(comps).median if comps else 0.0


def evaluate_policy(horizon_ticks: int, k: int, noop_composite: float,
                    ref_composite: float, suppress_wildlife: bool = False):
    """Run K episodes of the CURRENT scenario and return the aggregated normalized
    score (median + CI). The policy's actions are applied inside bonsai_episode.sh
    (v1 = no-op; action verbs added next). Returns metric.RunStats."""
    pairs = run_k(horizon_ticks, k, suppress_wildlife)
    scores = [
        metric.normalized_score(h, t0, horizon_ticks, noop_composite, ref_composite)
        for t0, h in pairs
    ]
    return aggregate(scores)


if __name__ == "__main__":
    import sys, json
    H = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
    K = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    pairs = run_k(H, K)
    comps = score_pairs(pairs, H)
    st = aggregate(comps)
    print(json.dumps({
        "horizon": H, "episodes": len(pairs), "composites": [round(c, 4) for c in comps],
        "median": round(st.median, 4), "mad": round(st.mad, 4),
        "ci": [round(st.ci_low, 4), round(st.ci_high, 4)], "ci_half": round(st.ci_half, 4),
    }))
