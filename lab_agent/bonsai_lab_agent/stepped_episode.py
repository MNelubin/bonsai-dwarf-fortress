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

import math
import time
from typing import Callable

from bonsai_lab_agent import game_scorer
from bonsai_lab_agent.scoring import EpisodeObs
from bonsai_lab_agent.session import DFSession, SessionError

DEFAULT_ROUNDS = 24
MIN_CHUNK_TICKS = 100
FEEDBACK_TEXT_LIMIT = 1200


def _compact_feedback_value(value):
    """Bound untrusted controller values before echoing them into model context."""
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k)[:80]: _compact_feedback_value(v)
                for k, v in list(value.items())[:16]}
    if isinstance(value, (list, tuple)):
        return [_compact_feedback_value(v) for v in list(value)[:16]]
    return str(value)[:240]


def _raw_int(raw: dict, key: str) -> int | None:
    """Parse an optional observer integer without turning 'not deployed' into zero."""
    try:
        return int(raw[key])
    except (KeyError, TypeError, ValueError):
        return None


def dependency_state(raw: dict) -> dict:
    """Policy-facing prerequisite state emitted by the trusted DFHack observer."""
    def counts(key: str) -> dict:
        parsed = {}
        for part in str(raw.get(key) or "").split(","):
            name, sep, value = part.partition(":")
            if not sep:
                continue
            try:
                parsed[name] = int(value)
            except ValueError:
                continue
        return parsed

    shop_counts = counts("shops")
    pending_shop_counts = counts("pending_shops")
    return {
        "resources": {
            "wood": _raw_int(raw, "nwood"),
            "boulders": _raw_int(raw, "nboulder"),
            "blocks": _raw_int(raw, "nblocks"),
            "bars": _raw_int(raw, "nbars"),
            "beds": _raw_int(raw, "nbeds"),
            "barrels": _raw_int(raw, "nbarrels"),
            "seed_stacks": _raw_int(raw, "nseeds"),
            "plant_stacks": _raw_int(raw, "nplants"),
        },
        "workshops": {
            "total": _raw_int(raw, "nworkshop"),
            "built": _raw_int(raw, "nbuiltshop"),
            "unbuilt": _raw_int(raw, "nunbuiltshop"),
            "built_by_type": shop_counts,
            "pending_by_type": pending_shop_counts,
        },
        "jobs": {
            "total": _raw_int(raw, "njobs"),
            "unassigned": _raw_int(raw, "nunassignedjobs"),
            "by_manager": _raw_int(raw, "nmanagerjobs"),
            "brewing": _raw_int(raw, "nbrewjobs"),
        },
        "manager_orders": {
            "active": _raw_int(raw, "norders"),
            "amount_left": _raw_int(raw, "norderleft"),
        },
        "food_chain": {
            "farm_plots": _raw_int(raw, "nfarmplots"),
        },
    }


def _dependency_delta(before_raw: dict, after_raw: dict) -> dict:
    before, after = dependency_state(before_raw), dependency_state(after_raw)
    out = {}
    for section in ("resources", "jobs", "manager_orders", "food_chain"):
        changed = {}
        for name, old in before[section].items():
            new = after[section].get(name)
            if old is not None and new is not None and old != new:
                changed[name] = new - old
        if changed:
            out[section] = changed
    changed_workshops = {}
    for name in ("total", "built", "unbuilt"):
        old = before["workshops"][name]
        new = after["workshops"][name]
        if old is not None and new is not None and old != new:
            changed_workshops[name] = new - old
    old_types = before["workshops"]["built_by_type"]
    new_types = after["workshops"]["built_by_type"]
    type_delta = {name: new_types.get(name, 0) - old_types.get(name, 0)
                  for name in set(old_types) | set(new_types)
                  if new_types.get(name, 0) != old_types.get(name, 0)}
    if type_delta:
        changed_workshops["built_by_type"] = type_delta
    old_pending = before["workshops"]["pending_by_type"]
    new_pending = after["workshops"]["pending_by_type"]
    pending_delta = {name: new_pending.get(name, 0) - old_pending.get(name, 0)
                     for name in set(old_pending) | set(new_pending)
                     if new_pending.get(name, 0) != old_pending.get(name, 0)}
    if pending_delta:
        changed_workshops["pending_by_type"] = pending_delta
    if changed_workshops:
        out["workshops"] = changed_workshops
    return out


def _action_feedback(round_index: int, raw_actions, clean: list[dict],
                     dispatched: list[dict], gate_messages: list[str],
                     applied: str, controller_error: str | None,
                     before: EpisodeObs, after: EpisodeObs,
                     before_raw: dict, after_raw: dict) -> dict:
    """Build the compact trusted receipt supplied with the next observation.

    Replays already recorded what the controller requested and what DFHack printed,
    but the controller itself could not see that evidence on the next round. Keep the
    receipt bounded so a verbose prerequisite trace cannot exhaust model context.
    """
    fields = (
        "cohort_alive", "hunger_sum", "thirst_sum", "stress_danger",
        "food_count", "drink_count", "buildings", "dug_tiles", "workorders_done",
    )
    delta = {name: getattr(after, name) - getattr(before, name) for name in fields}
    delta = {name: value for name, value in delta.items() if value}
    requested = raw_actions
    if isinstance(requested, dict):
        requested = [requested]
    if not isinstance(requested, (list, tuple)):
        requested = []
    return {
        "round": round_index,
        "requested": _compact_feedback_value(list(requested)[:16]),
        "accepted": _compact_feedback_value(clean[:16]),
        "dispatched": [a.get("verb") for a in dispatched[:16]],
        "gate_messages": [message[:240] for message in gate_messages[:16]],
        "dfhack": (applied or "")[-FEEDBACK_TEXT_LIMIT:],
        "controller_error": controller_error,
        "elapsed_ticks": after.abs_tick - before.abs_tick,
        "observed_delta": delta,
        "dependency_delta": _dependency_delta(before_raw, after_raw),
        "after": {
            "cohort_alive": after.cohort_alive,
            "food_count": after.food_count,
            "drink_count": after.drink_count,
            "buildings": after.buildings,
            "dug_tiles": after.dug_tiles,
            "workorders_done": after.workorders_done,
        },
    }


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
    # No T0 solid count means no excavation measure. It used to fall back to a "dug" key,
    # which the observer has never emitted, so the fallback was a silent zero dressed as a
    # reading -- exactly how the retired second adapter scored every episode's digging at
    # nothing. Zero is honest here only because the caller failed to pin T0.
    dug = 0
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
                        repeat_schema: bool = True,
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
        previous_feedback = None
        for i, chunk in enumerate(chunks):
            before_raw = cur_raw
            cur = obs_to_episode_obs(cur_raw, cohort_ids, t0_solid)
            cobs = game_scorer.controller_observation(cur)
            if i > 0 and not repeat_schema:
                cobs.pop("action_schema", None)
                cobs.pop("available_actions", None)
                cobs["action_schema_ref"] = "round:0"
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
            # A single casualty is not a fort under attack; on a fort of 136 it is
            # Tuesday. Threat means danger present or arriving, or casualties on a scale
            # that is itself the emergency -- otherwise the flag latches on and every
            # policy that reads it stops developing for good.
            cobs["wounded"] = int(cur_raw.get("nwounded", 0) or 0)
            casualty_alarm = max(2, math.ceil(0.10 * max(1, int(cur_raw.get("ncit", 0) or 0))))
            cobs["under_threat"] = (cobs["hostiles"] > 0
                                    or cobs["danger_events"] > 0
                                    or cobs["injured"] >= casualty_alarm)
            # Work the fort refused to do, kept apart from danger. The observer used to
            # score a cancelled dig job as a danger event, which latched `under_threat`
            # on for good on any fort that was actually working. These say WHY the fort
            # is not doing what it was told -- "Damp stone located" is the difference
            # between a policy that re-asks forever and one that digs somewhere else.
            cobs["cancellations"] = int(cur_raw.get("ncancel", 0) or 0)
            cobs["cancel_reasons"] = [
                c for c in (cur_raw.get("cancels", "none") or "").split(";")
                if c and c != "none"]
            cobs["hostiles_on_map"] = int(cur_raw.get("nhostile_map", 0) or 0)
            cobs["dependencies"] = dependency_state(cur_raw)
            cobs["previous_action_feedback"] = previous_feedback

            t_dec = time.time()
            raw_actions, err = _safe_controller(controller_fn, cobs)
            clean, gate_messages = game_scorer.sanitize_actions_verbose(raw_actions)
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
            previous_feedback = _action_feedback(
                i, raw_actions, clean, dispatch, gate_messages, applied, err, cur, post,
                before_raw, cur_raw)
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
