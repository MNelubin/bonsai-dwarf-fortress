"""Real gameplay scorer for the trusted evaluator (suite v4).

Replaces the degenerate smoke score (evaluator.evaluation_outcome: an API-contract
arithmetic that always lands ~1.0) with a STATISTICAL gameplay score computed from
DFHack ground truth the controller cannot forge.

Trust model: this module + scoring.py + live_episode.py + the bonsai-*.lua scripts
run ONLY on the trusted evaluator side. The untrusted agent contributes a controller
that maps observation -> action intents; the evaluator DISPATCHES those intents
deterministically (bonsai-apply-actions.lua) so the agent cannot reach into DF state
or fabricate outcomes. The score reads only the empirically σ≈0 observables
(see scoring.py); wildlife/stress noise is excluded.

Flow per episode (on the DF host, port 5001, supervised DF kept alive on 5000):
  load pinned save -> observe T0 -> invoke agent controller with T0 obs ->
  write approved action intents -> deterministic DFHack dispatch -> advance horizon
  -> observe H -> EpisodeObs pair. K episodes -> median + distribution-free CI +
  trust gate. Full format (wildlife ON) by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Any, Callable

from bonsai_lab_agent import scoring
from bonsai_lab_agent.scoring import EpisodeObs, aggregate, raw_components, DEFAULT_WEIGHTS
from bonsai_lab_agent import live_episode

SUITE_NAME = "gameplay_survival_development"
SUITE_VERSION = "4"


def regime_key(*, scenario_id: str, save_sha256: str | None, df_version: str,
               dfhack_version: str, plugin_set_hash: str | None, horizon_ticks: int,
               k: int, weights: dict | None = None) -> str:
    """Stable identifier for the scoring regime. The orchestrator MUST reset the
    champion / best_score whenever this changes — otherwise a score from a different
    save, engine version, horizon, or metric weighting is compared against a stale
    high-water mark (the smoke-era 1.0 would freeze the champion forever). Any change
    to the pinned scenario, DF/DFHack build, plugin set, horizon, K, suite, or metric
    weights yields a new key."""
    payload = {
        "suite": SUITE_NAME, "suite_version": SUITE_VERSION,
        "scenario_id": scenario_id, "save_sha256": save_sha256,
        "df_version": df_version, "dfhack_version": dfhack_version,
        "plugin_set_hash": plugin_set_hash,
        "horizon_ticks": horizon_ticks, "k": k,
        "weights": weights or DEFAULT_WEIGHTS,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

# The action verbs the evaluator will dispatch deterministically. Anything else the
# controller emits is ignored (logged), never executed — the agent cannot run
# arbitrary DFHack. Kept in sync with bonsai-apply-actions.lua.
ALLOWED_VERBS = {"set_labor", "designate_dig", "create_stockpile", "add_workorder", "advance"}

DF_DIR = os.environ.get("BONSAI_DF_DIR", "/srv/df-bonsai/current")
ACTIONS_FILE = os.path.join(DF_DIR, "agent_actions.txt")

# The pinned save's T0 observation is CONSTANT (read-only save at a paused T0), so the
# controller can decide setup actions from it without a wasteful probe episode. Values
# are the empirically-verified pinned start state (cids are the T0 cohort). A redeploy
# must re-verify start_state_hash; a mismatch marks the scenario 'drifted' (excluded).
PINNED_T0 = EpisodeObs(
    abs_tick=2016801, cohort_alive=7, cohort_size=7, hunger_sum=7, thirst_sum=7,
    stress_danger=0, food_count=12, drink_count=12, buildings=1, dug_tiles=0,
    workorders_done=0,
)


def sanitize_actions(raw_actions: list[dict]) -> list[dict]:
    """Keep only well-formed, allow-listed action intents. The evaluator never
    trusts the agent's actions verbatim; this is the anti-forgery gate."""
    clean = []
    for a in raw_actions or []:
        if not isinstance(a, dict):
            continue
        verb = a.get("command") or a.get("name")
        if verb in ALLOWED_VERBS:
            args = a.get("args")
            clean.append({"verb": verb, "args": args if isinstance(args, (list, dict)) else []})
    return clean


def _write_actions(actions: list[dict]) -> None:
    """Write sanitized actions as tab-separated lines: `verb\\targ1\\targ2` (a
    dependency-free format the DFHack dispatch script parses without a JSON lib)."""
    with open(ACTIONS_FILE, "w") as f:
        for a in actions:
            args = a.get("args") or []
            if isinstance(args, dict):
                args = list(args.values())
            f.write("\t".join([a["verb"], *[str(x) for x in args]]) + "\n")


def run_scored_episode(controller_fn: Callable[[dict], list[dict]],
                       horizon_ticks: int, suppress_wildlife: bool = False,
                       t0_obs: EpisodeObs = PINNED_T0,
                       timeout: int = 300) -> tuple[EpisodeObs, EpisodeObs]:
    """One real scored episode. The controller decides setup actions from the pinned
    T0 observation; the evaluator sanitizes + writes them; bonsai-apply-actions.lua
    dispatches them deterministically after the runner samples T0, then advances.
    Returns the (T0, H) EpisodeObs pair sampled live."""
    actions = sanitize_actions(controller_fn(t0_obs.__dict__))
    _write_actions(actions)
    p = subprocess.run(
        ["bash", live_episode.EPISODE_SH, str(horizon_ticks),
         "1" if suppress_wildlife else "0", "bonsai-apply-actions"],
        capture_output=True, text=True, timeout=timeout, cwd=DF_DIR,
    )
    t0d = hd = None
    for line in p.stdout.splitlines():
        if "OBS_T0 OBS" in line:
            t0d = live_episode._parse_obs(line)
        elif "OBS_H OBS" in line:
            hd = live_episode._parse_obs(line)
    if not t0d or not hd:
        raise RuntimeError(f"scored episode produced no OBS pair: ...{(p.stdout + p.stderr)[-200:]}")
    return live_episode._pair_to_obs(t0d, hd)


def score_submission(controller_fn: Callable[[dict], list[dict]], *,
                     horizon_ticks: int, k: int,
                     noop_composite: float, ref_composite: float,
                     suppress_wildlife: bool = False,
                     on_episode: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Run K real episodes and produce the v4 result dict for evaluate_job.

    Score is baseline-subtracted (agent-noop)/(ref-noop), clamped [0,1], reported as
    the K-run median with a distribution-free CI. `trustworthy` is False when the CI
    is too wide to distinguish the agent from the no-op baseline (evaluator should
    raise K or refuse to promote). `on_episode(done, total)` is called after each
    episode — evaluate_job_v4 wires it to the evaluator heartbeat so a long K-run eval
    (~2-20 min) does not outlive its job lease."""
    pairs = []
    for _ in range(k):
        try:
            pairs.append(run_scored_episode(controller_fn, horizon_ticks, suppress_wildlife))
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        if on_episode is not None:
            try:
                on_episode(len(pairs), k)
            except Exception:
                pass

    scores = [
        scoring.normalized_score(h, t0, horizon_ticks, noop_composite, ref_composite)
        for t0, h in pairs
    ]
    st = aggregate(scores)
    survived_all = all(h.cohort_alive == h.cohort_size for _, h in pairs) if pairs else False
    # trustworthy = enough runs AND the score band excludes the no-op baseline (0.0)
    trustworthy = st.n >= 3 and (st.ci_low > 0.05 or st.ci_high < 0.05 or st.ci_half < 0.15)

    verdict = "gameplay_scored" if pairs else "episode_failed"
    failure_kind = None if pairs else "runtime"

    return {
        "suite_name": SUITE_NAME,
        "suite_version": SUITE_VERSION,
        "score": round(st.median, 6),
        "verdict": verdict,
        "failure_kind": failure_kind,
        "summary": {
            "episodes_run": st.n, "episodes_requested": k,
            "horizon_ticks": horizon_ticks, "format": "full" if not suppress_wildlife else "nowild",
            "per_episode_scores": [round(s, 4) for s in scores],
            "median": round(st.median, 4), "mad": round(st.mad, 4),
            "ci": [round(st.ci_low, 4), round(st.ci_high, 4)], "ci_half": round(st.ci_half, 4),
            "trustworthy": trustworthy, "all_cohort_survived": survived_all,
            "noop_composite": noop_composite, "ref_composite": ref_composite,
            "scope": "K-run statistical gameplay score on the deterministic dwarf surface",
        },
        "metrics": [
            {"name": "gameplay.score_median", "value": round(st.median, 6), "unit": "ratio"},
            {"name": "gameplay.ci_half", "value": round(st.ci_half, 6), "unit": "ratio"},
            {"name": "gameplay.episodes", "value": float(st.n), "unit": "count"},
            {"name": "gameplay.trustworthy", "value": 1.0 if trustworthy else 0.0, "unit": "boolean"},
        ],
    }
