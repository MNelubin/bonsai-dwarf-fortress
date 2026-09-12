"""Record a teacher tier playing, one (features, actions) row per round.

Runs on the lab beside the fort. Writes JSONL that the trainer consumes anywhere with
numpy. The teacher is unchanged and unaware; the collector only watches what it decides
against what it saw.

    BONSAI_EPISODE_SAVE=ourfort16-final python -m player.collect_trajectories v3_survival 3 3600 out.jsonl
"""
from __future__ import annotations

import json
import os
import sys
import time

from bonsai_lab_agent import baselines, scoring, stepped_episode
from player.imitation import FEATURE_NAMES, action_key, featurize


def main() -> None:
    tier, k, horizon, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    teacher = getattr(baselines, tier)
    save = os.environ.get("BONSAI_EPISODE_SAVE")
    started = time.time()
    with open(out, "a", encoding="utf-8") as f:
        for ep in range(k):
            rows: list[dict] = []

            def watched(obs: dict) -> list[dict]:
                acts = teacher(obs)
                rows.append({
                    "x": featurize(obs),
                    "y": sorted({action_key(a) for a in acts if a.get("command") != "advance"}),
                    "round": obs.get("round"),
                })
                return acts

            try:
                t0, h = stepped_episode.run_stepped_episode(watched, horizon_ticks=horizon, rounds=24)
                c = scoring.raw_components(h, t0, horizon)
                for r in rows:
                    r.update({"save": save, "tier": tier, "episode": ep, "horizon": horizon,
                              "episode_composite": c["composite"]})
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
                f.flush()
                print(f"  ep{ep+1}/{k} rows={len(rows)} composite={c['composite']:.6f} "
                      f"t={time.time()-started:.0f}s", flush=True)
            except Exception as exc:
                print(f"  ep{ep+1}/{k} FAILED {type(exc).__name__}: {exc}"[:160], flush=True)
    print(f"done features={len(FEATURE_NAMES)}", flush=True)


if __name__ == "__main__":
    main()
