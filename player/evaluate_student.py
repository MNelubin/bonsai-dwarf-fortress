"""Score a trained Student the same way the tiers are scored.

    BONSAI_EPISODE_SAVE=ourfort16-final python -m player.evaluate_student weights.json 3 3600
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

from bonsai_lab_agent import scoring, stepped_episode
from player.imitation import Student, action_key

weights, k, horizon = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
student = Student.load(weights)
save = os.environ.get("BONSAI_EPISODE_SAVE")
rows, started = [], time.time()
for i in range(k):
    fired: dict[str, int] = {}

    def counted(obs):
        acts = student(obs)
        for a in acts:
            fired[action_key(a)] = fired.get(action_key(a), 0) + 1
        return acts

    try:
        t0, h = stepped_episode.run_stepped_episode(counted, horizon_ticks=horizon, rounds=24)
        c = scoring.raw_components(h, t0, horizon)
        rows.append(c["composite"])
        print(f"  ep{i+1}/{k} composite={c['composite']:.6f} dug={h.dug_tiles-t0.dug_tiles} "
              f"orders={h.workorders_done-t0.workorders_done} builds={h.buildings-t0.buildings} "
              f"alive={h.cohort_alive}/{t0.cohort_size} t={time.time()-started:.0f}s", flush=True)
        print("     fired: " + ", ".join(f"{k}x{v}" for k, v in sorted(fired.items(), key=lambda kv: -kv[1])[:8]), flush=True)
    except Exception as exc:
        print(f"  ep{i+1}/{k} FAILED {type(exc).__name__}: {exc}"[:160], flush=True)
if rows:
    print("STUDENT " + json.dumps({"save": save, "weights": os.path.basename(weights), "n": len(rows),
                                   "composite_median": statistics.median(rows)}), flush=True)
