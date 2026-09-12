"""Let the Student improve against the scorer itself. Stage C, the cheap way.

Imitation gives a Student that equals its teacher and cannot exceed it. This closes the
loop with the only signal that can lift it past the teacher: the composite score the
evaluator computes from a live fort. No gradients cross the game, so this is black-box
search -- a cross-entropy method over the Student's output layer, twelve candidates a
generation played in parallel on the lab, the best few averaged into the next mean.

Pure Python on purpose. Four thousand weights and Gaussian noise do not need numpy, and
the lab venv then needs nothing installed to run the whole loop.

Selection is on the fresh embark because an episode there costs a minute. The mature
save is a HOLDOUT: the elite plays it every few generations and the score is logged, not
selected on. If fresh climbs while mature falls, the search found a habit of one fort and
not a better player -- or found a hole in the metric, which is worth knowing either way.

    BONSAI_PLAYER_PKG=/srv/bonsai-agent/player_pkg python -m player.evolve \
        --base student_v1.json --out /srv/bonsai-agent/evolve --generations 25
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

PY = sys.executable
FRESH, MATURE = "ourfort16-final", "region3-lab"


def flat_out(model: dict) -> list[float]:
    W, b = model["layers"][-1]["W"], model["layers"][-1]["b"]
    return [v for row in W for v in row] + list(b)


def set_out(model: dict, flat: list[float]) -> dict:
    m = copy.deepcopy(model)
    W, b = m["layers"][-1]["W"], m["layers"][-1]["b"]
    n_out, n_hid = len(W), len(W[0])
    for i in range(n_out):
        W[i] = flat[i * n_hid:(i + 1) * n_hid]
    m["layers"][-1]["b"] = flat[n_out * n_hid:]
    return m


def evaluate(cands: list[Path], save: str, horizon: int, base_port: int, timeout: int) -> list[float | None]:
    """Play every candidate once, all at the same time. None where the episode failed."""
    procs = []
    for i, path in enumerate(cands):
        env = {**os.environ, "BONSAI_EPISODE_SAVE": save, "BONSAI_EPISODE_PORT": str(base_port + i),
               "PYTHONPATH": os.environ.get("BONSAI_PLAYER_PKG", "")}
        log = open(str(path) + f".{save}.log", "w")
        procs.append((subprocess.Popen([PY, "-m", "player.evaluate_student", str(path), "1", str(horizon)],
                                       stdout=log, stderr=subprocess.STDOUT, env=env, cwd="/srv/df-bonsai/current"), log))
    deadline = time.time() + timeout
    for p, log in procs:
        try:
            p.wait(timeout=max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            p.kill()
        log.close()
    out = []
    for path in cands:
        text = Path(str(path) + f".{save}.log").read_text(encoding="utf-8", errors="replace")
        m = re.search(r'"composite_median": ([0-9.]+)', text)
        out.append(float(m.group(1)) if m else None)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--generations", type=int, default=25); ap.add_argument("--pop", type=int, default=12)
    ap.add_argument("--elite", type=int, default=4); ap.add_argument("--sigma", type=float, default=0.15)
    ap.add_argument("--sigma-decay", type=float, default=0.97); ap.add_argument("--horizon", type=int, default=3600)
    ap.add_argument("--holdout-every", type=int, default=5); ap.add_argument("--port", type=int, default=7300)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    mean = flat_out(base)
    sigma = a.sigma
    best_score, best_model = -1.0, base
    log = open(out / "evolve_log.jsonl", "a", encoding="utf-8")

    # generation 0: where does the imitation student stand, on both forts, before touching it
    (out / "gen000_base.json").write_text(json.dumps(base))
    s_fresh = evaluate([out / "gen000_base.json"], FRESH, a.horizon, a.port, 600)[0]
    s_mature = evaluate([out / "gen000_base.json"], MATURE, a.horizon, a.port, 1200)[0]
    log.write(json.dumps({"gen": 0, "kind": "base", "fresh": s_fresh, "mature": s_mature}) + "\n"); log.flush()
    print(f"gen 0 base: fresh={s_fresh} mature={s_mature}", flush=True)
    if s_fresh is not None:
        best_score = s_fresh

    for gen in range(1, a.generations + 1):
        t = time.time()
        cands, models = [], []
        for i in range(a.pop):
            flat = [v + rng.gauss(0, sigma) for v in mean]
            m = set_out(base, flat)
            p = out / f"gen{gen:03d}_c{i:02d}.json"
            p.write_text(json.dumps(m)); cands.append(p); models.append((flat, m))
        scores = evaluate(cands, FRESH, a.horizon, a.port, 900)
        ranked = sorted([(s, i) for i, s in enumerate(scores) if s is not None], reverse=True)
        if not ranked:
            print(f"gen {gen}: every candidate failed", flush=True); continue
        elite = ranked[:a.elite]
        # CEM: the next mean is the elite's mean; the elite's spread tempers sigma
        mean = [statistics.fmean(models[i][0][k] for _, i in elite) for k in range(len(mean))]
        sigma *= a.sigma_decay
        gen_best, gi = ranked[0]
        if gen_best > best_score:
            best_score, best_model = gen_best, models[gi][1]
            (out / "student_best.json").write_text(json.dumps(best_model))
        row = {"gen": gen, "kind": "gen", "sigma": round(sigma, 4), "best": gen_best,
               "elite_mean": statistics.fmean(s for s, _ in elite), "median": statistics.median(s for s, _ in ranked),
               "worst": ranked[-1][0], "failed": scores.count(None), "best_ever": best_score,
               "seconds": round(time.time() - t)}
        if gen % a.holdout_every == 0:
            row["mature_holdout"] = evaluate([out / "student_best.json"], MATURE, a.horizon, a.port, 1200)[0]
        log.write(json.dumps(row) + "\n"); log.flush()
        print(json.dumps(row), flush=True)
        for p in cands:                                   # keep the directory small
            if p != out / "student_best.json":
                p.unlink(missing_ok=True)
    print(f"done best_ever={best_score}", flush=True)


if __name__ == "__main__":
    main()
