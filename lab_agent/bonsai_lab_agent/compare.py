"""Compare two recorded episodes — the face-to-face model comparison.

Two guardrails make a comparison honest, and they are the reason this is a module
rather than a couple of lines in the viewer:

1. **Regime equality.** Comparing runs from different saves, DF builds, horizons or
   metric weights is meaningless. `regime_key` already encodes exactly that, so a
   mismatch is refused rather than rendered.

2. **One run is not a result.** DF is not bit-reproducible, so a single episode's
   score carries luck. A face-to-face that shows one run per model invites reading
   a lucky draw as skill. `compare_runs` therefore reports each model's K-run
   distribution alongside the single run being watched, and says plainly when the
   gap between two models is inside the noise.

Produces a plain dict; the viewer renders it and the CLI prints it.
"""

from __future__ import annotations

import statistics
from typing import Any

from bonsai_lab_agent.recorder import read_recording


class RegimeMismatch(ValueError):
    """The two recordings were not produced under the same scoring regime."""


def load_summary(path: str) -> dict[str, Any]:
    """Read a recording into the summary shape the comparison works on."""
    events = read_recording(path)
    if not events:
        raise ValueError(f"{path}: no readable events")
    meta = next((e for e in events if e.get("kind") == "meta"), {})
    stats = [e for e in events if e.get("kind") == "stat"]
    rounds = [e for e in events if e.get("kind") == "round"]
    return {
        "path": path,
        "episode_id": meta.get("episode_id"),
        "regime_key": meta.get("regime_key"),
        "horizon_ticks": meta.get("horizon_ticks"),
        "rounds": meta.get("rounds"),
        "has_map": any(e.get("kind") == "map" for e in events),
        "t0": stats[0] if stats else None,
        "final": stats[-1] if stats else None,
        "series": {k: [s.get(k) for s in stats]
                   for k in ("tick", "alive", "food", "drink", "hunger", "thirst",
                             "buildings", "dug", "workorders", "stress_danger")},
        "decisions": [{"i": r.get("i"), "tick": r.get("tick"),
                       "dispatched": r.get("dispatched") or [],
                       "dropped": [d.get("verb") or d.get("reason")
                                   for d in (r.get("dropped") or [])],
                       "error": r.get("controller_error")}
                      for r in rounds],
    }


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def compare_runs(a_path: str, b_path: str, *,
                 a_scores: list[float] | None = None,
                 b_scores: list[float] | None = None,
                 a_label: str = "A", b_label: str = "B",
                 require_same_regime: bool = True) -> dict[str, Any]:
    """Compare two recorded episodes, optionally in the context of their K-run scores.

    `a_scores` / `b_scores` are the per-episode scores of each model's full K-run set.
    Without them the comparison still works but is explicitly marked as anecdotal —
    one episode of a stochastic game is a story, not a measurement.
    """
    a, b = load_summary(a_path), load_summary(b_path)

    if require_same_regime and a["regime_key"] != b["regime_key"]:
        raise RegimeMismatch(
            f"refusing to compare across regimes: {a_label}={a['regime_key']!r} vs "
            f"{b_label}={b['regime_key']!r}. Different save, engine build, horizon or "
            f"metric weighting — the numbers are not on the same scale.")

    warnings = []
    if a["horizon_ticks"] != b["horizon_ticks"]:
        warnings.append(f"different horizons ({a['horizon_ticks']} vs {b['horizon_ticks']})")
    if a["rounds"] != b["rounds"]:
        warnings.append(
            f"different decision counts ({a['rounds']} vs {b['rounds']}) — the model with "
            f"more rounds had more agency, which is not a skill difference")

    verdict = _verdict(a_scores, b_scores, a_label, b_label, warnings)

    return {
        "a": {"label": a_label, **a},
        "b": {"label": b_label, **b},
        "regime_key": a["regime_key"],
        "warnings": warnings,
        "distribution": verdict,
        "final_deltas": _deltas(a["final"], b["final"]),
        "divergence": _divergence(a["series"], b["series"]),
    }


def _verdict(a_scores, b_scores, a_label, b_label, warnings) -> dict[str, Any]:
    """Decide whether the two models are actually distinguishable."""
    if not a_scores or not b_scores:
        return {
            "comparable": False,
            "reason": "no K-run scores supplied — this is a single-episode anecdote, "
                      "not a measurement. DF is not bit-reproducible, so one run "
                      "carries luck.",
        }
    am, bm = _median(a_scores), _median(b_scores)
    a_spread = (max(a_scores) - min(a_scores)) if len(a_scores) > 1 else 0.0
    b_spread = (max(b_scores) - min(b_scores)) if len(b_scores) > 1 else 0.0
    gap = abs(am - bm)
    noise = max(a_spread, b_spread)
    separated = gap > noise and min(len(a_scores), len(b_scores)) >= 3
    return {
        "comparable": True,
        "a_median": round(am, 4), "b_median": round(bm, 4),
        "a_runs": len(a_scores), "b_runs": len(b_scores),
        "a_spread": round(a_spread, 4), "b_spread": round(b_spread, 4),
        "gap": round(gap, 4), "noise": round(noise, 4),
        "separated": separated,
        "winner": (a_label if am > bm else b_label) if separated else None,
        "reason": (f"median gap {gap:.4f} exceeds the wider within-model spread {noise:.4f}"
                   if separated else
                   f"median gap {gap:.4f} is inside the within-model spread {noise:.4f} — "
                   f"these two are not distinguishable on this evidence; raise K"),
    }


def _deltas(fa: dict | None, fb: dict | None) -> dict[str, Any]:
    if not fa or not fb:
        return {}
    keys = ("alive", "food", "drink", "hunger", "thirst", "buildings", "dug",
            "workorders", "stress_danger")
    return {k: {"a": fa.get(k), "b": fb.get(k),
                "delta": (fa.get(k) - fb.get(k))
                if isinstance(fa.get(k), (int, float)) and isinstance(fb.get(k), (int, float))
                else None}
            for k in keys}


def _divergence(sa: dict, sb: dict) -> dict[str, Any]:
    """Where each metric first parted ways — the 'when did A pull ahead' question."""
    out = {}
    for k in ("buildings", "food", "dug", "workorders", "alive"):
        va, vb = sa.get(k) or [], sb.get(k) or []
        n = min(len(va), len(vb))
        first = None
        for i in range(n):
            if va[i] is not None and vb[i] is not None and va[i] != vb[i]:
                first = {"sample": i,
                         "tick_a": (sa.get("tick") or [None] * n)[i],
                         "a": va[i], "b": vb[i]}
                break
        out[k] = first
    return out


def format_report(cmp: dict[str, Any]) -> str:
    """Human-readable comparison for a terminal."""
    a, b, d = cmp["a"], cmp["b"], cmp["distribution"]
    lines = [
        f"{a['label']}  {a['episode_id'] or a['path']}",
        f"{b['label']}  {b['episode_id'] or b['path']}",
        f"regime {cmp['regime_key']}",
        "",
    ]
    if d.get("comparable"):
        lines += [
            f"median   {a['label']} {d['a_median']} (n={d['a_runs']}, spread {d['a_spread']})",
            f"         {b['label']} {d['b_median']} (n={d['b_runs']}, spread {d['b_spread']})",
            f"verdict  {d['winner'] or 'no separation'} — {d['reason']}",
        ]
    else:
        lines.append(f"verdict  {d['reason']}")
    lines.append("")
    lines.append(f"{'metric':<16}{a['label']:>10}{b['label']:>10}{'delta':>10}")
    for k, v in (cmp["final_deltas"] or {}).items():
        lines.append(f"{k:<16}{str(v['a']):>10}{str(v['b']):>10}{str(v['delta']):>10}")
    for w in cmp["warnings"]:
        lines.append(f"WARNING  {w}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(format_report(compare_runs(sys.argv[1], sys.argv[2])))
