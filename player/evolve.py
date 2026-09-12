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


def _which(model: dict, layers: str) -> list[int]:
    return list(range(len(model["layers"]))) if layers == "all" else [len(model["layers"]) - 1]


def flat_out(model: dict, layers: str = "output") -> list[float]:
    """The weights under search, as one flat list. `output` is the last layer only --
    what fires when, over features the imitation already learned. `all` includes the
    hidden layer -- what the player notices in the first place -- which is where a
    behaviour the teacher never had can come from."""
    out: list[float] = []
    for i in _which(model, layers):
        L = model["layers"][i]
        out += [v for row in L["W"] for v in row] + list(L["b"])
    return out


def set_out(model: dict, flat: list[float], layers: str = "output") -> dict:
    m = copy.deepcopy(model)
    k = 0
    for i in _which(m, layers):
        L = m["layers"][i]
        n_out, n_in = len(L["W"]), len(L["W"][0])
        for r in range(n_out):
            L["W"][r] = flat[k:k + n_in]; k += n_in
        L["b"] = flat[k:k + n_out]; k += n_out
    assert k == len(flat)
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
    ap.add_argument("--layers", choices=("output", "all"), default="output")
    ap.add_argument("--select", choices=("fresh", "both"), default="both")
    ap.add_argument("--mature-top", type=int, default=4)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    mean = flat_out(base, a.layers)
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
        best_score = s_fresh + (s_mature or 0.0) if a.select == "both" else s_fresh

    for gen in range(1, a.generations + 1):
        t = time.time()
        cands, models = [], []
        for i in range(a.pop):
            flat = [v + rng.gauss(0, sigma) for v in mean]
            m = set_out(base, flat, a.layers)
            p = out / f"gen{gen:03d}_c{i:02d}.json"
            p.write_text(json.dumps(m)); cands.append(p); models.append((flat, m))
        scores = evaluate(cands, FRESH, a.horizon, a.port, 900)
        ranked = sorted([(s, i) for i, s in enumerate(scores) if s is not None], reverse=True)
        if not ranked:
            print(f"gen {gen}: every candidate failed", flush=True); continue
        if a.select == "both":
            # Selecting on the fresh embark alone overfits it. Measured: forty generations
            # of --layers all took the fresh score 0.6666 -> 0.6753 and the mature score
            # 0.6334 -> 0.5857, four more dwarves dead and three buildings lost, while the
            # unselected holdout only REPORTED the slide. So the top candidates by fresh
            # score also play the mature save, and the elite is ranked by the SUM. One
            # mature episode per candidate is enough: its spread is 0.0008.
            top = [i for _, i in ranked[:a.mature_top]]
            m_scores = evaluate([cands[i] for i in top], MATURE, a.horizon, a.port + 20, 1500)
            both = sorted([(scores[i] + (m if m is not None else 0.0), i, scores[i], m)
                           for i, m in zip(top, m_scores)], reverse=True)
            elite = [(s, i) for s, i, _, _ in both[:a.elite]]
            fitness_of = {i: s for s, i, _, _ in both}
        else:
            elite = ranked[:a.elite]
            fitness_of = dict((i, s) for s, i in ranked)
        # CEM: the next mean is the elite's mean; the elite's spread tempers sigma
        mean = [statistics.fmean(models[i][0][k] for _, i in elite) for k in range(len(mean))]
        sigma *= a.sigma_decay
        gi = elite[0][1]
        gen_best = fitness_of[gi]
        if gen_best > best_score:
            best_score, best_model = gen_best, models[gi][1]
            (out / "student_best.json").write_text(json.dumps(best_model))
        row = {"gen": gen, "kind": "gen", "sigma": round(sigma, 4), "best": gen_best,
               "best_fresh": scores[gi], "best_mature": (fitness_of[gi] - scores[gi]) if a.select == "both" else None,
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
