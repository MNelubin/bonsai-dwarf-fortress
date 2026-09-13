"""Give an older Student the columns a newer featurizer emits, without changing what it does.

Features are only ever APPENDED (player/imitation.py), so a model trained on the first N
can be widened to N+k by adding k zero columns to its first layer and k zero-mean/unit-std
entries to its normaliser. Every forward pass then computes exactly what it did before --
the new inputs are multiplied by zero -- and evolution is free to learn to use them.

    python -m player.widen player/weights/student_evolved_v1.json -o student_evolved_v1_46.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from player.imitation import FEATURE_NAMES


def widen(model: dict) -> dict:
    have = list(model["features"])
    want = list(FEATURE_NAMES)
    if have == want:
        return model
    if want[: len(have)] != have:
        raise ValueError("feature order changed, not just extended; a model cannot be widened across that")
    k = len(want) - len(have)
    m = json.loads(json.dumps(model))
    m["features"] = want
    m["norm"]["mean"] += [0.0] * k
    m["norm"]["std"] += [1.0] * k
    for row in m["layers"][0]["W"]:
        row += [0.0] * k
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model"); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    m = widen(json.loads(Path(a.model).read_text(encoding="utf-8")))
    Path(a.out).write_text(json.dumps(m), encoding="utf-8")
    print(f"{Path(a.model).name}: {len(json.loads(Path(a.model).read_text())['features'])} -> {len(m['features'])} features, wrote {a.out}")


if __name__ == "__main__":
    main()
