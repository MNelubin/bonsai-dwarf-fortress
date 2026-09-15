"""DAgger from recordings: label the states the STUDENT reached with what the teacher
would have done there, and add them to the imitation set.

Imitation on the teacher's own trajectories leaves the student confident only where
the teacher goes. Read off the recordings on 2026-09-14: the student asked for digging
every round from round 6 on the hungry month where the teacher asks only when its
backlog is short - a state the teacher never reached, so nothing had ever told the
student what to do there. DAgger (Ross, Gordon, Bagnell 2011) closes that: run the
student, ask the teacher at every state it visited, train on both.

Every episode already leaves a recording (stepped_episode + BONSAI_REC_DIR), so this
needs no lab time at all: the round events carry the observation the controller saw
(scalars plus the dependency tree), which is exactly what featurize() and the teacher
read. The teacher's little hidden state (the butcher cooldown) is replayed by walking
each episode in order.

    python -m player.dagger rec/v5/*.rec.jsonl.gz rec/champ9/*.rec.jsonl.gz -o player/traj/dagger.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from bonsai_lab_agent import baselines
from bonsai_lab_agent.recorder import read_recording
from player.imitation import action_key, featurize


def rebuild_obs(round_event: dict) -> dict:
    obs = dict(round_event.get("obs") or {})
    obs["dependencies"] = round_event.get("dependencies") or {}
    obs["previous_action_feedback"] = {}
    return obs


def label_recording(path: str, teacher) -> list[dict]:
    events = read_recording(path)
    meta = next((e for e in events if e.get("kind") == "meta"), {})
    rounds = sorted((e for e in events if e.get("kind") == "round"), key=lambda e: e["i"])
    rows = []
    for e in rounds:
        obs = rebuild_obs(e)
        if "round" not in obs:
            continue
        acts = teacher(obs)                      # in order: the teacher's counters follow the episode
        rows.append({
            "x": featurize(obs),
            "y": sorted({action_key(a) for a in acts if a.get("command") != "advance"}),
            "round": obs.get("round"),
            "save": meta.get("scenario"), "tier": "dagger:" + str(meta.get("label")),
            "episode": Path(path).name, "horizon": meta.get("horizon_ticks"),
            "student_y": sorted(set(e.get("dispatched") or [])),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recordings", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--teacher", default="v3_survival")
    a = ap.parse_args()
    teacher = getattr(baselines, a.teacher)
    paths = [p for pat in a.recordings for p in sorted(glob.glob(pat))]
    n, disagree = 0, 0
    with open(a.out, "w", encoding="utf-8") as f:
        for p in paths:
            rows = label_recording(p, teacher)
            for r in rows:
                if {k.split("|")[0] for k in r["y"]} != set(r["student_y"]):
                    disagree += 1
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
            n += len(rows)
    print(f"labelled {n} states from {len(paths)} recordings; teacher disagreed with the student's verb set on {disagree}", flush=True)


if __name__ == "__main__":
    main()
