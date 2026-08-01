"""Stepped episode driver — interaction model B.

The agent controller is re-invoked repeatedly DURING the episode against the LIVE
fort, instead of once at T0:

    observe -> controller decides -> sanitize -> dispatch -> advance a chunk -> observe -> ...

This reconciles the scorer with the existing agent submissions: a step-loop policy
that returns {"command": "advance"} is now MEANINGFUL (it means "develop nothing this
round") rather than degenerate, while a policy that returns development intents can
react to what the fort actually looks like at that moment.

Decision density is pinned by `rounds`, not by chunk size, so episodes at different
horizons give the agent the same number of decisions — otherwise a 30-day episode
would hand the agent 10x the agency of a 3-day one and the horizons would not be
comparable.

FAIL-SAFE: a controller that crashes, hangs, or returns garbage costs the agent its
actions for that round only. It never aborts the episode — otherwise a broken
submission would be indistinguishable from infrastructure failure.
"""

from __future__ import annotations

import time
from typing import Callable

from bonsai_lab_agent import game_scorer
from bonsai_lab_agent.scoring import EpisodeObs
from bonsai_lab_agent.session import DFSession, SessionError

DEFAULT_ROUNDS = 24
MIN_CHUNK_TICKS = 100


def chunk_plan(horizon_ticks: int, rounds: int = DEFAULT_ROUNDS) -> list[int]:
    """Split the horizon into per-round tick chunks that sum EXACTLY to the horizon.

    Exactness matters: the score compares fort state at a fixed horizon, so an episode
    that silently advanced 35 900 of 36 000 ticks would be scored against the wrong
    baseline.
    """
    if horizon_ticks <= 0:
        return []
    rounds = max(1, min(rounds, horizon_ticks // MIN_CHUNK_TICKS or 1))
    base, extra = divmod(horizon_ticks, rounds)
    return [base + (1 if i < extra else 0) for i in range(rounds)]


def obs_to_episode_obs(d: dict, cohort_ids: set[str], t0_solid: int | None = None) -> EpisodeObs:
    """Convert a raw OBS dict into the scored observation.

    Cohort survival is the intersection with the T0 id-set, so migrants and births
    cannot inflate it and the denominator stays pinned to the starting seven.

    `dug_tiles` is derived from the drop in the fort's solid-tile count since T0 —
    digging turns walls into floors. The observer emits `nsolid`; before it did, the
    field parsed as 0 forever and a third of the development term was blind no matter
    how much the agent mined.
    """
    live = set(d.get("cids", "").split(",")) - {""}
    solid = int(d.get("nsolid", -1))
    dug = int(d.get("dug", 0))
    if t0_solid is not None and t0_solid >= 0 and solid >= 0:
        dug = max(0, t0_solid - solid)
    return EpisodeObs(
        abs_tick=int(d.get("t", 0)),
        cohort_alive=len(cohort_ids & live) if cohort_ids else len(live),
        cohort_size=len(cohort_ids) if cohort_ids else len(live),
        hunger_sum=int(d.get("hsum", 0)), thirst_sum=int(d.get("tsum", 0)),
        stress_danger=int(d.get("strdang", 0)),
        food_count=int(d.get("nfood", 0)), drink_count=int(d.get("ndrink", 0)),
        buildings=int(d.get("nbuild", 0)), dug_tiles=dug,
        workorders_done=int(d.get("worders", 0)),
    )


def _safe_controller(controller_fn: Callable[[dict], list[dict]], obs: dict) -> tuple[list, str | None]:
    """Invoke the untrusted controller. Returns (raw_actions, error_or_None)."""
    try:
        return controller_fn(obs) or [], None
    except Exception as e:                       # noqa: BLE001 - untrusted code, catch all
        return [], f"{type(e).__name__}: {e}"[:200]


def run_stepped_episode(controller_fn: Callable[[dict], list[dict]], *,
                        horizon_ticks: int,
                        rounds: int = DEFAULT_ROUNDS,
                        suppress_wildlife: bool = False,
                        recorder=None,
                        session: DFSession | None = None) -> tuple[EpisodeObs, EpisodeObs]:
    """Run one live stepped episode. Returns the (T0, horizon) observation pair.

    `recorder`, if given, receives on_start/on_round/on_end and is what produces the
    replay file. Recording failures are swallowed — an episode must never fail because
    a recorder had a bad day.
    """
    own_session = session is None
    sess = session or DFSession()
    try:
        if own_session:
            sess.boot()
        if suppress_wildlife:
            sess.suppress_wildlife()

        t0_raw = sess.observe()
        cohort_ids = set(t0_raw.get("cids", "").split(",")) - {""}
        t0_solid = int(t0_raw.get("nsolid", -1))
        t0 = obs_to_episode_obs(t0_raw, cohort_ids, t0_solid)
        _emit(recorder, "on_start", t0_raw, t0, horizon_ticks, rounds)

        cur_raw = t0_raw
        chunks = chunk_plan(horizon_ticks, rounds)
        remaining = horizon_ticks
        for i, chunk in enumerate(chunks):
            cur = obs_to_episode_obs(cur_raw, cohort_ids, t0_solid)
            cobs = game_scorer.controller_observation(cur)
            cobs["round"] = i
            cobs["rounds_total"] = len(chunks)
            cobs["ticks_remaining"] = remaining
            # Threat channel. Kept OUT of EpisodeObs on purpose: these are decision
            # inputs, not scored observables — scoring them would let an agent farm
            # danger. The policy needs them to react; the metric must not see them.
            cobs["hostiles"] = int(cur_raw.get("nhostile", 0))
            cobs["injured"] = int(cur_raw.get("ninjured", 0))
            cobs["danger_events"] = int(cur_raw.get("ndanger", 0))
            cobs["warnings"] = [w for w in (cur_raw.get("warn", "none") or "").split(";")
                                if w and w != "none"]
            cobs["under_threat"] = (cobs["hostiles"] > 0 or cobs["injured"] > 0
                                    or cobs["danger_events"] > 0)

            t_dec = time.time()
            raw_actions, err = _safe_controller(controller_fn, cobs)
            clean = game_scorer.sanitize_actions(raw_actions)
            # `advance` is the legacy step-loop verb: it carries no dispatch, it just
            # means "no development this round". Filter it out of the dispatch set.
            dispatch = [a for a in clean if a["verb"] != "advance"]
            decide_ms = int((time.time() - t_dec) * 1000)

            applied = ""
            if dispatch:
                try:
                    applied = sess.apply_actions(dispatch)
                except SessionError:
                    raise
                except Exception as e:            # noqa: BLE001
                    applied = f"APPLY_ERROR {type(e).__name__}: {e}"[:200]

            sess.advance(chunk)
            remaining -= chunk
            cur_raw = sess.observe()

            _emit(recorder, "on_round", i, cobs, raw_actions, clean, dispatch,
                  applied, err, decide_ms, cur_raw)
            # The metric track is FREE: the driver already had to observe here, so the
            # recorder samples the scored observables at no extra RPC cost.
            post = obs_to_episode_obs(cur_raw, cohort_ids, t0_solid)
            _emit(recorder, "on_post_round", i, post.abs_tick, post)

        h = obs_to_episode_obs(cur_raw, cohort_ids, t0_solid)
        _emit(recorder, "on_end", h)
        return t0, h
    finally:
        if own_session:
            sess.close()
        _emit(recorder, "close")


def _emit(recorder, hook: str, *args) -> None:
    """Call a recorder hook, swallowing anything it throws."""
    if recorder is None:
        return
    fn = getattr(recorder, hook, None)
    if fn is None:
        return
    try:
        fn(*args)
    except Exception:                             # noqa: BLE001 - never fail an episode
        pass
