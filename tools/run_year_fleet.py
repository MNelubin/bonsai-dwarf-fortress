"""Run a fleet of full-year episodes concurrently and score them.

Replaces the serial year runner. A DF year is 403,200 ticks (12 x 28 x 1200) and one
fort sustains about 1,000 ticks/s on this host, so a year is ~7 minutes of pure advance
and a K-run of three policies was costing the better part of an hour end to end — for
no reason other than that the driver started one fort at a time.

What parallelism actually buys, measured on this host (Xeon E5-2699 v4, container
pinned to 16 CPUs):

    1 fort      1,014 ticks/s
    3 forts     1,853-1,920 ticks/s aggregate
    6 forts     1,853 ticks/s aggregate

So the ceiling is ~1.85x, and it is reached at three forts. Every DF still burns ~120%
CPU at six-way, while delivering a third of its solo tick rate — the signature of a
memory-bound workload, not of CPU starvation (the cgroup has no CPU quota and the host
was at load 13 of 88). Adding forts past three therefore buys nothing per fort, but it
does not cost anything either: six years finish in the time two would take serially, so
running the whole evidence matrix in one shot is strictly better than staging it.

Per-fort rates vary a lot within a run (309 to 704 ticks/s at six-way). Each of this
container's CPUs shares a physical core with a hyperthread sibling belonging to another
container on the host, so a fort whose sibling is busy runs at roughly half speed. That
is not ours to schedule, which is why the fleet is sized by aggregate throughput and the
stragglers are simply waited on.

    python run_year_fleet.py [replicates] [tier ...]
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback

from bonsai_lab_agent import recorder as rec
from bonsai_lab_agent import stepped_episode as se
from bonsai_lab_agent.baselines import TIERS
from bonsai_lab_agent.map_recorder import MapRecorder
from bonsai_lab_agent.scoring import raw_components
from bonsai_lab_agent.session import DFSession

YEAR = 403200
ROUNDS = 48                       # ~8400 ticks (7 fort-days) per decision
BASE_PORT = 5001                  # 5000 is the supervised runtime and is never touched
OUT = "/srv/df-bonsai/recordings"
RESULT = "/tmp/year_fleet_result.json"

# A year at ~1,850 aggregate ticks/s is minutes, but a straggler sharing a physical core
# can take twice as long, and the watchdog kills the fort when it fires.
WATCHDOG = 10800


def run_one(tier: str, replicate: int, port: int, out: dict, lock: threading.Lock,
            want_map: bool) -> None:
    """One full-year episode on its own DF. Never raises — a dead fort is a datum."""
    name = f"{tier}-year-r{replicate}"
    path = f"{OUT}/{name}.rec.jsonl.gz"
    if os.path.exists(path):
        os.remove(path)
    controller = TIERS[tier]
    sess = DFSession(port=port, watchdog_seconds=WATCHDOG)
    started = time.time()
    try:
        sess.boot()
        # The map track is the expensive one and only exists to be looked at, so one
        # replicate per tier carries it and the rest stay cheap.
        mrec = MapRecorder(sess, keyframe_every=12) if want_map else None
        r = rec.EpisodeRecorder(path, meta={"episode_id": name, "tier": tier,
                                            "replicate": replicate,
                                            "regime_key": "year-403200"},
                                map_recorder=mrec)
        trace: list[dict] = []

        def spy(obs: dict, _fn=controller, _tr=trace) -> list[dict]:
            _tr.append({"r": obs.get("round"), "alive": obs.get("cohort_alive"),
                        "food": obs.get("food_count"), "drink": obs.get("drink_count"),
                        "hunger": obs.get("hunger_sum"), "thirst": obs.get("thirst_sum"),
                        "dug": obs.get("dug_tiles"), "bld": obs.get("buildings"),
                        "threat": bool(obs.get("under_threat")),
                        "hostiles": obs.get("hostiles", 0)})
            return _fn(obs)

        t0, h = se.run_stepped_episode(spy, horizon_ticks=YEAR, rounds=ROUNDS,
                                       session=sess, recorder=r)
        r.close()
        comp = raw_components(h, t0, YEAR)
        row = {
            "tier": tier, "replicate": replicate, "port": port, "file": path,
            "wall_s": round(time.time() - started, 1),
            "composite": round(comp["composite"], 5),
            "development": round(comp.get("development", -1), 5),
            "provisioning": round(comp.get("provisioning", -1), 5),
            "comfort": round(comp.get("comfort", -1), 5),
            "survival_gate": round(comp.get("survival_gate", -1), 5),
            "cohort_start": t0.cohort_size, "cohort_end": h.cohort_alive,
            "dug": h.dug_tiles, "buildings": h.buildings,
            "food": [t0.food_count, h.food_count],
            "drink": [t0.drink_count, h.drink_count],
            "hunger": [t0.hunger_sum, h.hunger_sum],
            # abs_tick is cur_year * 1e6 + cur_year_tick, so its delta is a CALENDAR
            # reading, not a tick count: exactly one year elapsed shows up as 1,000,000
            # rather than 403,200. Reported under its own name so a report cannot quote
            # it as "ticks simulated".
            "horizon_ticks": YEAR,
            "calendar_delta": h.abs_tick - t0.abs_tick,
            "years_elapsed": round((h.abs_tick - t0.abs_tick) / 1_000_000, 3),
            "bytes": os.path.getsize(path), "map_track": want_map, "trace": trace,
        }
        with lock:
            out["runs"].append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "trace"}), flush=True)
    except Exception:                                        # noqa: BLE001
        with lock:
            out["errors"].append(f"{name}: {traceback.format_exc()[-400:]}")
        print(f"ERR {name}", flush=True)
    finally:
        sess.close()


def main() -> int:
    replicates = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    tiers = sys.argv[2:] or ["v0_idle", "v1_developer", "v2_reactive"]
    unknown = [t for t in tiers if t not in TIERS]
    if unknown:
        print(f"unknown tiers: {unknown}; have {sorted(TIERS)}", file=sys.stderr)
        return 2

    jobs = [(t, k) for t in tiers for k in range(replicates)]
    out: dict = {"runs": [], "errors": [], "year": YEAR, "rounds": ROUNDS,
                 "fleet": len(jobs)}
    lock = threading.Lock()
    print(f"fleet of {len(jobs)}: {tiers} x {replicates} replicates", flush=True)

    t0 = time.time()
    threads = [threading.Thread(target=run_one,
                                args=(t, k, BASE_PORT + i, out, lock, k == 0))
               for i, (t, k) in enumerate(jobs)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    out["wall_s"] = round(time.time() - t0, 1)

    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"fleet wall={out['wall_s']}s ok={len(out['runs'])}/{len(jobs)}", flush=True)
    for e in out["errors"]:
        print("ERROR " + e, flush=True)
    print(f"BONSAI_RESULT_SAVED {RESULT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
