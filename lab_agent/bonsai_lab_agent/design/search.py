"""Simulated annealing over room layouts, with elitist restarts.

WHY ANNEALING, and not the genetic algorithm the owner also named. The state is a grid
with hard invariants — one door, an unbroken wall, a connected floor, no two pieces on a
tile — and crossing two valid rooms of different sizes produces an invalid room almost
surely, so a GA would spend its whole budget inside a repair operator. Local moves keep
the invariants by construction.

The owner's evolutionary idea earns its place as SELECTION rather than recombination: K
independent chains, and every so often the worst is reseeded from the archive's best. That
is an elitist restart, which buys the diversity annealing alone lacks without inventing a
crossover that breaks rooms.

DETERMINISM is a declared property, not a hope. One seeded Random per chain; no `set` and
no dict iteration anywhere on the decision path; an all-integer objective; ties broken by
`repr`, which is a total order; and the budget counted in evaluations, never in seconds.
`math.exp` in the acceptance test is the only float in the whole search.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .model import (FUNCTIONAL, PIECE_KEYS, Design, Requirement, TILE_VALUE, bare_room,
                    score)
from .validate import validate

# Move weights, in a module constant so a test can pin them: a search whose behaviour
# depends on undeclared magic is not reproducible in any useful sense.
MOVES = (
    ("toggle_smooth", 4),
    ("resize", 2),
    ("smooth_rect", 2),
    ("add_piece", 2),
    ("del_piece", 2),
    ("move_piece", 2),
    ("retype_piece", 2),
    ("smooth_all", 1),
    ("move_door", 1),
)

PLACEABLE = ("a", "b", "c", "f", "h", "n", "r", "s", "t")


def _rows_from(d: Design) -> list[list[str]]:
    return [list(row) for row in d.cells]


def _rebuild(d: Design, rows: list[list[str]], pieces) -> Design:
    return Design(kind=d.kind, w=len(rows[0]), h=len(rows),
                  cells=tuple("".join(r) for r in rows),
                  pieces=tuple(pieces), seed_name=d.seed_name)


def _interior(d: Design) -> list[tuple[int, int]]:
    return [(x, y) for y in range(d.h) for x in range(d.w) if d.cells[y][x] in TILE_VALUE]


def neighbour(d: Design, req: Requirement, rng: random.Random) -> Design | None:
    """One local move. Returns None when the move does not apply, which costs nothing."""
    names = [n for n, _ in MOVES]
    weights = [wt for _, wt in MOVES]
    move = rng.choices(names, weights=weights, k=1)[0]
    rows = _rows_from(d)
    pieces = list(d.pieces)
    inside = _interior(d)

    if move == "toggle_smooth":
        if not inside or not req.allow_smooth:
            return None
        x, y = inside[rng.randrange(len(inside))]
        rows[y][x] = "." if rows[y][x] == "s" else "s"

    elif move == "smooth_rect":
        if len(inside) < 2 or not req.allow_smooth:
            return None
        (x0, y0) = inside[rng.randrange(len(inside))]
        (x1, y1) = inside[rng.randrange(len(inside))]
        on = rng.random() < 0.5
        for y in range(min(y0, y1), max(y0, y1) + 1):
            for x in range(min(x0, x1), max(x0, x1) + 1):
                if rows[y][x] in TILE_VALUE:
                    rows[y][x] = "s" if on else "."

    elif move == "smooth_all":
        if not req.allow_smooth:
            return None
        on = rng.random() < 0.5
        for x, y in inside:
            rows[y][x] = "s" if on else "."

    elif move == "resize":
        side = rng.randrange(4)
        grow = rng.random() < 0.5
        nw = d.w + (1 if grow else -1) * (1 if side in (0, 2) else 0)
        nh = d.h + (1 if grow else -1) * (1 if side in (1, 3) else 0)
        if nw < 3 or nh < 3 or nw > req.max_w or nh > req.max_h:
            return None
        # rebuild from scratch at the new size, keeping the smoothing pattern where it
        # still lands inside and dropping pieces that no longer fit
        new_rows = []
        for y in range(nh):
            row = []
            for x in range(nw):
                if x in (0, nw - 1) or y in (0, nh - 1):
                    row.append("#")
                else:
                    old = d.at(x, y)
                    row.append("s" if old == "s" else ".")
            new_rows.append(row)
        doors = [(x, y) for y in range(d.h) for x in range(d.w) if d.cells[y][x] == "+"]
        dx = doors[0][0] if doors else nw // 2
        dx = min(max(1, dx), nw - 2)
        new_rows[0][dx] = "+"
        rows = new_rows
        pieces = [(x, y, k) for x, y, k in pieces if 1 <= x < nw - 1 and 1 <= y < nh - 1]

    elif move == "add_piece":
        free = [c for c in inside if c not in {(x, y) for x, y, _ in pieces}]
        if not free:
            return None
        x, y = free[rng.randrange(len(free))]
        pieces.append((x, y, PLACEABLE[rng.randrange(len(PLACEABLE))]))

    elif move == "del_piece":
        if not pieces:
            return None
        pieces.pop(rng.randrange(len(pieces)))

    elif move == "move_piece":
        if not pieces:
            return None
        free = [c for c in inside if c not in {(x, y) for x, y, _ in pieces}]
        if not free:
            return None
        i = rng.randrange(len(pieces))
        x, y = free[rng.randrange(len(free))]
        pieces[i] = (x, y, pieces[i][2])

    elif move == "retype_piece":
        if not pieces:
            return None
        i = rng.randrange(len(pieces))
        x, y, _ = pieces[i]
        pieces[i] = (x, y, PLACEABLE[rng.randrange(len(PLACEABLE))])

    elif move == "move_door":
        wall = [(x, y) for y in range(d.h) for x in range(d.w)
                if (x in (0, d.w - 1)) != (y in (0, d.h - 1))]
        if not wall:
            return None
        for y in range(d.h):
            for x in range(d.w):
                if rows[y][x] == "+":
                    rows[y][x] = "#"
        x, y = wall[rng.randrange(len(wall))]
        rows[y][x] = "+"

    try:
        return _rebuild(d, rows, pieces)
    except Exception:
        return None


# How many candidate moves may be tried per evaluation actually charged. Generous, but
# finite: without it the search can spin forever in a state no move improves.
ATTEMPTS_PER_EVAL = 40


@dataclass
class Result:
    best: Design
    best_score: int
    seed_score: int
    evaluations: int
    feasible: bool
    attempts: int = 0
    reasons: tuple[str, ...] = ()


def anneal(req: Requirement, seed: int = 0, max_evals: int = 4000,
           chains: int = 4, t0: int = 40, restart_every: int = 250) -> Result:
    """Search. `max_evals` is the budget and it is honoured exactly."""
    start = bare_room(req)
    seed_score = score(start, req)

    rngs = [random.Random(seed * 1000003 + i) for i in range(chains)]
    cur = [start] * chains
    cur_score = [seed_score] * chains
    best, best_score = start, seed_score

    # A move that does not apply, or one that breaks an invariant, costs no evaluation —
    # otherwise the budget would be spent on arithmetic rather than on designs. But that
    # makes the loop unbounded: from some states almost every move is invalid, and from a
    # few none is, and the search would spin forever without ever charging itself. So
    # ATTEMPTS are capped too. Measured: this hung the test suite outright before the cap.
    max_attempts = max_evals * ATTEMPTS_PER_EVAL
    evals = 0
    attempts = 0
    step = 0
    while evals < max_evals and attempts < max_attempts:
        for ci in range(chains):
            if evals >= max_evals or attempts >= max_attempts:
                break
            attempts += 1
            rng = rngs[ci]
            cand = neighbour(cur[ci], req, rng)
            if cand is None:
                continue
            if validate(cand, req):
                continue                      # shape invariants are HARD; do not charge
            evals += 1
            s = score(cand, req)
            temp = max(1, t0 - (step * t0) // max(1, max_evals // chains))
            delta = s - cur_score[ci]
            if delta >= 0 or rng.random() < math.exp(delta / temp):
                cur[ci], cur_score[ci] = cand, s
            # strictly better, or equal and lexicographically smaller: a total order, so
            # the winner never depends on which chain happened to get there first
            if s > best_score or (s == best_score and repr(cand) < repr(best)):
                best, best_score = cand, s
        step += 1
        if restart_every and step % restart_every == 0:
            worst = min(range(chains), key=lambda i: (cur_score[i], repr(cur[i])))
            cur[worst], cur_score[worst] = best, best_score

    reasons = tuple(validate(best, req))
    feasible = not reasons and best.value(req.material_value, req.quality) >= req.demand
    return Result(best=best, best_score=best_score, seed_score=seed_score,
                  evaluations=evals, attempts=attempts, feasible=feasible,
                  reasons=reasons)


def main(argv: list[str] | None = None) -> int:
    """`python -m bonsai_lab_agent.design.search --seed 7` — used by the determinism test,
    which runs it in a SUBPROCESS. That half is the one that matters: it is what catches
    set iteration and hash randomisation leaking into the result."""
    import argparse
    import hashlib

    from .emit import to_quickfort

    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--kind", default="Bedroom")
    ap.add_argument("--position", default="mayor")
    ap.add_argument("--evals", type=int, default=4000)
    ap.add_argument("--max-w", type=int, default=9)
    ap.add_argument("--max-h", type=int, default=9)
    a = ap.parse_args(argv)

    req = Requirement(kind=a.kind, position=a.position, max_w=a.max_w, max_h=a.max_h)
    r = anneal(req, seed=a.seed, max_evals=a.evals)
    csv = to_quickfort(r.best, name=f"{a.kind.lower()}_{a.position}_{a.seed}")
    print(f"seed={a.seed} score {r.seed_score} -> {r.best_score} "
          f"value={r.best.value()} cost={r.best.cost()} "
          f"feasible={r.feasible} evals={r.evaluations}")
    print("sha256=" + hashlib.sha256(csv.encode()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
