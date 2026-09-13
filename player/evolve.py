"""Let the Student improve against the scorer itself. Stage C, the cheap way.

Imitation gives a Student that equals its teacher and cannot exceed it. This closes the
loop with the only signal that can lift it past the teacher: the composite score the
evaluator computes from a live fort. No gradients cross the game, so this is black-box
search -- a cross-entropy method over the Student's output layer, twelve candidates a
generation played in parallel on the lab, the best few averaged into the next mean.

Pure Python on purpose. Four thousand weights and Gaussian noise do not need numpy, and
the lab venv then needs nothing installed to run the whole loop.

Every candidate plays the fresh embark because an episode there costs a minute. The
top few by that score then play the other scenarios (the mature save, the hungry month)
and the elite is ranked by the SUM OF NORMALISED scores across them -- normalised
against each scenario's own calibrated no-op and reference, because a raw composite of
0.63 on the mature fort and 0.42 on the hungry one are not the same distance travelled.
A candidate that only learns the habits of one scenario loses on the others and is not
selected. A scenario with no calibration pair is refused, not scored at zero.

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

# name -> (save, prep script or "", horizon, per-episode timeout seconds)
SCENARIOS = {
    "fresh":  (FRESH, "", 3600, 900),
    "mature": (MATURE, "", 3600, 1500),
    # a fort-month on a wagon with no food: the composite here is mostly whether the
    # policy finds the livestock before the dwarves die
    "hungry": (FRESH, "bonsai-prep-hungry", 33600, 2400),
}


def normalised(score, name: str):
    """(agent - noop) / (ref - noop) against the scenario's calibrated endpoints."""
    if score is None:
        return None
    from bonsai_lab_agent.scoring import calibration_for
    save, prep, horizon, _ = SCENARIOS[name]
    cal = calibration_for(f"{save}+{prep}" if prep else save, horizon)
    if cal is None:
        raise SystemExit(f"scenario {name} has no calibration pair; measure it before selecting on it")
    return (score - cal["noop"]) / (cal["ref"] - cal["noop"])


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


def evaluate(cands: list[Path], name: str, base_port: int) -> list:
    """Play every candidate once on one scenario, all at the same time. None where the
    episode failed. Raw composite medians; see normalised()."""
    save, prep, horizon, timeout = SCENARIOS[name]
    procs = []
    for i, path in enumerate(cands):
        env = {**os.environ, "BONSAI_EPISODE_SAVE": save, "BONSAI_EPISODE_PORT": str(base_port + i),
               "PYTHONPATH": os.environ.get("BONSAI_PLAYER_PKG", "")}
        if prep:
            env["BONSAI_EPISODE_PREP"] = prep
        else:
            env.pop("BONSAI_EPISODE_PREP", None)
        log = open(str(path) + f".{name}.log", "w")
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
        text = Path(str(path) + f".{name}.log").read_text(encoding="utf-8", errors="replace")
        m = re.search(r'"composite_median": ([0-9.]+)', text)
        out.append(float(m.group(1)) if m else None)
    return out


def evaluate_many(cands: list[Path], names: list[str], base_port: int) -> dict:
    """The secondary scenarios run side by side, each on its own port block."""
    import threading
    results: dict = {}

    def run(j, name):
        results[name] = evaluate(cands, name, base_port + 20 * (j + 1))
    threads = [threading.Thread(target=run, args=(j, n)) for j, n in enumerate(names)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--generations", type=int, default=25); ap.add_argument("--pop", type=int, default=12)
    ap.add_argument("--elite", type=int, default=4); ap.add_argument("--sigma", type=float, default=0.15)
    ap.add_argument("--sigma-decay", type=float, default=0.97)
    ap.add_argument("--port", type=int, default=7300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--layers", choices=("output", "all"), default="output")
    ap.add_argument("--scenarios", default="fresh,mature,hungry",
                    help="comma list from %s; everyone plays the first, --top play the rest" % ",".join(SCENARIOS))
    ap.add_argument("--top", type=int, default=6, help="how many candidates by the first scenario play the rest")
    a = ap.parse_args()
    names = [n.strip() for n in a.scenarios.split(",") if n.strip()]
    for n in names:
        if n not in SCENARIOS:
            raise SystemExit(f"unknown scenario {n}")
        normalised(0.0, n)                                  # refuse early if uncalibrated
    first, rest = names[0], names[1:]

    def fitness(raw: dict):
        parts = [normalised(raw.get(n), n) for n in names]
        return None if any(p is None for p in parts) else sum(parts)

    rng = random.Random(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    mean = flat_out(base, a.layers)
    sigma = a.sigma
    best_score, best_model = float("-inf"), base
    log = open(out / "evolve_log.jsonl", "a", encoding="utf-8")

    # generation 0: where does the base stand on every scenario before touching it
    (out / "gen000_base.json").write_text(json.dumps(base))
    raw0 = {first: evaluate([out / "gen000_base.json"], first, a.port)[0]}
    raw0.update({n: v[0] for n, v in evaluate_many([out / "gen000_base.json"], rest, a.port).items()})
    f0 = fitness(raw0)
    log.write(json.dumps({"gen": 0, "kind": "base", "raw": raw0,
                          "norm": {n: normalised(raw0[n], n) for n in names}, "fitness": f0}) + "\n"); log.flush()
    print(f"gen 0 base: raw={raw0} fitness={f0}", flush=True)
    if f0 is not None:
        best_score = f0

    for gen in range(1, a.generations + 1):
        t = time.time()
        cands, models = [], []
        for i in range(a.pop):
            flat = [v + rng.gauss(0, sigma) for v in mean]
            m = set_out(base, flat, a.layers)
            p = out / f"gen{gen:03d}_c{i:02d}.json"
            p.write_text(json.dumps(m)); cands.append(p); models.append((flat, m))
        scores = evaluate(cands, first, a.port)
        ranked = sorted([(s, i) for i, s in enumerate(scores) if s is not None], reverse=True)
        if not ranked:
            print(f"gen {gen}: every candidate failed", flush=True); continue
        # Selecting on the fresh embark alone overfits it. Measured: forty generations of
        # --layers all took the fresh score 0.6666 -> 0.6753 and the mature score
        # 0.6334 -> 0.5857, four more dwarves dead and three buildings lost, while an
        # unselected holdout only REPORTED the slide. So the top candidates by the first
        # scenario play every other one, and the elite is ranked by the summed normalised
        # score. One episode per scenario per candidate: the mature spread is 0.0008.
        top = [i for _, i in ranked[:a.top]]
        others = evaluate_many([cands[i] for i in top], rest, a.port) if rest else {}
        raw_of = {i: {first: scores[i], **{n: others[n][j] for n in rest}} for j, i in enumerate(top)}
        fitness_of = {i: fitness(raw_of[i]) for i in top}
        scored = sorted([(f, i) for i, f in fitness_of.items() if f is not None], reverse=True)
        if not scored:
            print(f"gen {gen}: every top candidate failed a scenario", flush=True); continue
        elite = scored[:a.elite]
        # CEM: the next mean is the elite's mean; the elite's spread tempers sigma
        mean = [statistics.fmean(models[i][0][k] for _, i in elite) for k in range(len(mean))]
        sigma *= a.sigma_decay
        gen_best, gi = elite[0]
        if gen_best > best_score:
            best_score, best_model = gen_best, models[gi][1]
            (out / "student_best.json").write_text(json.dumps(best_model))
        row = {"gen": gen, "kind": "gen", "sigma": round(sigma, 4), "best": gen_best,
               "best_raw": raw_of[gi], "best_norm": {n: normalised(raw_of[gi][n], n) for n in names},
               "elite_mean": statistics.fmean(f for f, _ in elite),
               "first_median": statistics.median(s for s, _ in ranked), "first_worst": ranked[-1][0],
               "failed": scores.count(None) + sum(1 for i in top if fitness_of[i] is None),
               "best_ever": best_score, "seconds": round(time.time() - t)}
        log.write(json.dumps(row) + "\n"); log.flush()
        print(json.dumps(row), flush=True)
        for p in cands:                                   # keep the directory small
            if p != out / "student_best.json":
                p.unlink(missing_ok=True)
    print(f"done best_ever={best_score}", flush=True)


if __name__ == "__main__":
    main()
