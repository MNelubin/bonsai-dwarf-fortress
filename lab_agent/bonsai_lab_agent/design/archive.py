"""The archive: what the search found, kept, and handed to the fort.

The owner asked for three things and the search on its own only does the first:

    дизайны генерировались с определёнными требованиями       — search.py
    потом мы смогли отследить, какой самый лучший             — this file
    отбор комнат уже вести вне обучения основного Агента      — this file

Without an archive a search result is a number in a terminal. This writes the winner where
quickfort can read it and registers it where `apply_template` can name it, so the agent can
ask for "bedroom_baron" the same way it asks for "tombs24" — and never sees a floor plan.

The archive is a JSON file rather than python source on purpose: it is DATA the search
writes, and a generated entry appended to a hand-written tuple is a merge conflict waiting
to happen and a thing somebody edits by hand.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from .emit import to_quickfort, to_surface_quickfort
from .model import Design, Requirement, score
from .search import Result, anneal

# Where the archive lives in the repo, and where the blueprints go on the lab host.
ARCHIVE = os.path.join(os.path.dirname(__file__), "archive.json")

# quickfort reads `dfhack-config/blueprints/<path>` relative to the DF process's working
# directory. `bonsai/` keeps ours out of DFHack's shipped `library/`.
BLUEPRINT_DIR = "bonsai"


@dataclass(frozen=True)
class Entry:
    """One archived design. Everything needed to rebuild it or to judge a rival."""

    name: str
    kind: str
    position: str
    demand: int
    value: int
    cost: int
    score: int
    seed_score: int
    w: int
    h: int
    seed: int
    evaluations: int
    csv_sha256: str
    cells: tuple[str, ...]
    pieces: tuple[tuple[int, int, str], ...]

    def to_design(self) -> Design:
        return Design(kind=self.kind, w=self.w, h=self.h, cells=tuple(self.cells),
                      pieces=tuple(tuple(p) for p in self.pieces))


def design_name(req: Requirement) -> str:
    return f"{req.kind.lower()}_{req.position.replace(' ', '_')}"


def load(path: str = ARCHIVE) -> list[Entry]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out = []
    for d in raw:
        out.append(Entry(
            name=d["name"], kind=d["kind"], position=d["position"],
            demand=d["demand"], value=d["value"], cost=d["cost"], score=d["score"],
            seed_score=d["seed_score"], w=d["w"], h=d["h"], seed=d["seed"],
            evaluations=d["evaluations"], csv_sha256=d["csv_sha256"],
            cells=tuple(d["cells"]),
            pieces=tuple(tuple(p) for p in d["pieces"]),
        ))
    return out


def save(entries: list[Entry], path: str = ARCHIVE) -> None:
    """Sorted by name so the file is stable: a diff should show what CHANGED, not what
    happened to be iterated first."""
    rows = []
    for e in sorted(entries, key=lambda x: x.name):
        rows.append({
            "name": e.name, "kind": e.kind, "position": e.position, "demand": e.demand,
            "value": e.value, "cost": e.cost, "score": e.score,
            "seed_score": e.seed_score, "w": e.w, "h": e.h, "seed": e.seed,
            "evaluations": e.evaluations, "csv_sha256": e.csv_sha256,
            "cells": list(e.cells), "pieces": [list(p) for p in e.pieces],
        })
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def entry_from(req: Requirement, r: Result, seed: int) -> Entry:
    name = design_name(req)
    csv = to_quickfort(r.best, name=name)
    return Entry(
        name=name, kind=req.kind, position=req.position, demand=req.demand,
        value=r.best.value(req.material_value, req.quality), cost=r.best.cost(),
        score=r.best_score, seed_score=r.seed_score, w=r.best.w, h=r.best.h,
        seed=seed, evaluations=r.evaluations,
        csv_sha256=hashlib.sha256(csv.encode()).hexdigest(),
        cells=tuple(r.best.cells), pieces=tuple(r.best.pieces))


def promote(req: Requirement, seeds=(1, 7, 13), max_evals: int = 4000,
            path: str = ARCHIVE) -> tuple[Entry, bool]:
    """Search across several seeds, keep the best, and archive it if it beats what is there.

    Returns the winning entry and whether the archive changed. A design is only replaced by
    a STRICTLY better score — a rerun that ties must not churn the file, or every run would
    produce a diff and the archive would stop meaning anything.
    """
    best: Entry | None = None
    for seed in seeds:
        r = anneal(req, seed=seed, max_evals=max_evals)
        if not r.feasible:
            continue
        cand = entry_from(req, r, seed)
        if best is None or (cand.score, cand.csv_sha256) > (best.score, best.csv_sha256):
            best = cand
    if best is None:
        raise ValueError(f"no feasible design for {design_name(req)}; "
                         f"demand {req.demand} in {req.max_w}x{req.max_h}")

    entries = load(path)
    existing = next((e for e in entries if e.name == best.name), None)
    if existing is not None and existing.score >= best.score:
        return existing, False
    entries = [e for e in entries if e.name != best.name] + [best]
    save(entries, path)
    return best, True


def blueprint_path(entry: Entry) -> str:
    """What `apply_template` will hand quickfort. Not under `library/`: that prefix is for
    DFHack's own shipped blueprints, and ours are addressed by their plain path."""
    return f"{BLUEPRINT_DIR}/{entry.name}.csv"


def write_blueprints(dest: str, path: str = ARCHIVE) -> list[str]:
    """Write every archived design to a blueprints directory. `dest` is the DF instance's
    `dfhack-config/blueprints`."""
    out = []
    target = os.path.join(dest, BLUEPRINT_DIR)
    os.makedirs(target, exist_ok=True)
    for e in load(path):
        csv = to_quickfort(e.to_design(), name=e.name)
        fn = os.path.join(target, f"{e.name}.csv")
        with open(fn, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(csv)
        out.append(fn)
        surface_fn = os.path.join(target, f"{e.name}-surface.csv")
        with open(surface_fn, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(to_surface_quickfort(e.to_design(), name=e.name))
        out.append(surface_fn)
    return out
