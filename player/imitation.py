"""Stage B of the player: a compact CPU policy that imitates a teacher tier.

The vision (PROJECT_VISION.md, "Обучение CPU Player") is explicit about the order of
things: a programmable baseline first, then a small model that learns to reproduce the
baseline's choice of skills from the observation, then DAgger, then RL. The baseline
tiers in `bonsai_lab_agent.baselines` are stage A. This module is stage B.

Three pieces, deliberately separable:

  featurize()   observation dict -> fixed-length list of floats, documented order
  action_key()  one action intent -> a canonical string label, and back
  Student       pure-Python forward pass over weights loaded from JSON -- no numpy, no
                framework, sub-millisecond, so the lab venv needs nothing installed

Training lives in `player/train_imitation.py` and needs numpy; it runs anywhere with a
CPU and writes the JSON the Student loads. The lab only ever runs the Student.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ADVANCE = [{"command": "advance"}]

# Workshop kinds the dependency view reports individually.
SHOP_KINDS = ("Carpenters", "Masons", "Still", "Craftsdwarfs", "Farmers")

# The feature order IS the contract between collector, trainer and student. Append
# only; never reorder, or every saved model silently reads the wrong columns.
FEATURE_NAMES: tuple[str, ...] = (
    "round_frac", "ticks_left_frac", "alive_frac", "cohort_log",
    "dug_log", "buildings_log", "orders_log", "food_per_dwarf", "drink_per_dwarf",
    "hostiles_log", "hostiles_map_log", "injured_frac", "danger_log", "under_threat",
    "cancellations_log", "wounded_frac",
    "wood_log", "boulders_log", "blocks_log", "bars_log", "beds_log", "barrels_log",
    "seeds_log", "plants_log",
    "shops_built_log", "shops_unbuilt_log", "stockpiles_log", "farm_plots_log",
    "jobs_log", "jobs_unassigned_log", "jobs_manager_log", "jobs_brewing_log",
    "orders_active_log", "orders_left_log",
) + tuple(f"built_{k}" for k in SHOP_KINDS) + tuple(f"pending_{k}" for k in SHOP_KINDS)


def _log(x) -> float:
    try:
        return math.log1p(max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def featurize(obs: dict) -> list[float]:
    """The observation as the model sees it. Counts are log1p'd so a mature fort's
    thousands and an embark's dozens land on one scale; ratios stay ratios."""
    deps = obs.get("dependencies") or {}
    res = deps.get("resources") or {}
    ws = deps.get("workshops") or {}
    built = ws.get("built_by_type") or {}
    pend = ws.get("pending_by_type") or {}
    jobs = deps.get("jobs") or {}
    orders = deps.get("orders") or {}
    food_chain = deps.get("food_chain") or {}
    logistics = deps.get("logistics") or {}

    rounds_total = max(1.0, _num(obs.get("rounds_total"), 24))
    r = _num(obs.get("round"))
    ticks_left = _num(obs.get("ticks_remaining"))
    horizon = max(1.0, ticks_left / max(1e-9, 1 - r / rounds_total)) if r < rounds_total else max(1.0, ticks_left)
    cohort = max(1.0, _num(obs.get("cohort_size"), 1))
    alive = _num(obs.get("cohort_alive"), cohort)

    f = [
        r / rounds_total,
        min(1.0, ticks_left / horizon),
        alive / cohort,
        _log(cohort),
        _log(obs.get("dug_tiles")), _log(obs.get("buildings")), _log(obs.get("workorders_done")),
        _num(obs.get("food_count")) / cohort, _num(obs.get("drink_count")) / cohort,
        _log(obs.get("hostiles")), _log(obs.get("hostiles_on_map")),
        _num(obs.get("injured")) / cohort, _log(obs.get("danger_events")),
        1.0 if obs.get("under_threat") else 0.0,
        _log(obs.get("cancellations")), _num(obs.get("wounded")) / cohort,
        _log(res.get("wood")), _log(res.get("boulders")), _log(res.get("blocks")), _log(res.get("bars")),
        _log(res.get("beds")), _log(res.get("barrels")), _log(res.get("seed_stacks")), _log(res.get("plant_stacks")),
        _log(ws.get("built")), _log(ws.get("unbuilt")), _log(logistics.get("stockpiles")),
        _log(food_chain.get("farm_plots")),
        _log(jobs.get("total")), _log(jobs.get("unassigned")), _log(jobs.get("by_manager")), _log(jobs.get("brewing")),
        _log(orders.get("active")), _log(orders.get("amount_left")),
    ]
    f += [_log(built.get(k)) for k in SHOP_KINDS]
    f += [_log(pend.get(k)) for k in SHOP_KINDS]
    assert len(f) == len(FEATURE_NAMES), (len(f), len(FEATURE_NAMES))
    return f


def action_key(action: dict) -> str:
    """`{"command": "set_labor", "args": ["MINE", True]}` -> `set_labor|MINE|True`."""
    args = action.get("args") or []
    if isinstance(args, dict):
        args = list(args.values())
    return "|".join([str(action.get("command"))] + [str(a) for a in args])


def key_action(key: str) -> dict:
    """The inverse: `set_labor|MINE|True` -> an intent the gate will canonicalise."""
    parts = key.split("|")
    args: list = []
    for p in parts[1:]:
        if p in ("True", "False"):
            args.append(p == "True")
        else:
            try:
                args.append(int(p))
            except ValueError:
                args.append(p)
    return {"command": parts[0], "args": args}


class Student:
    """Pure-Python MLP: features -> per-action probabilities -> the actions above a
    threshold, in the teacher's usual order. Nothing here imports anything heavier
    than json and math, so it runs in the lab venv as it is."""

    def __init__(self, weights: dict):
        self.features = list(weights["features"])
        self.labels = list(weights["labels"])
        self.mean = weights["norm"]["mean"]
        self.std = weights["norm"]["std"]
        self.layers = [(w["W"], w["b"]) for w in weights["layers"]]
        self.threshold = float(weights.get("threshold", 0.5))
        if self.features != list(FEATURE_NAMES):
            raise ValueError("saved model was trained on a different feature order")

    @classmethod
    def load(cls, path: str | Path) -> "Student":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def probabilities(self, obs: dict) -> list[float]:
        x = [(v - m) / (s if s > 1e-9 else 1.0) for v, m, s in zip(featurize(obs), self.mean, self.std)]
        for i, (W, b) in enumerate(self.layers):
            y = [sum(wi * xi for wi, xi in zip(row, x)) + bi for row, bi in zip(W, b)]
            if i < len(self.layers) - 1:
                x = [v if v > 0 else 0.0 for v in y]            # relu
            else:
                x = [1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, v)))) for v in y]   # sigmoid
        return x

    def __call__(self, obs: dict) -> list[dict]:
        probs = self.probabilities(obs)
        chosen = [key_action(k) for k, p in zip(self.labels, probs) if p >= self.threshold]
        return chosen or ADVANCE
