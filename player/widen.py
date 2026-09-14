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

from player.imitation import widen_weights


def widen(model: dict) -> dict:
    return widen_weights(model)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model"); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    m = widen(json.loads(Path(a.model).read_text(encoding="utf-8")))
    Path(a.out).write_text(json.dumps(m), encoding="utf-8")
    print(f"{Path(a.model).name}: {len(json.loads(Path(a.model).read_text())['features'])} -> {len(m['features'])} features, wrote {a.out}")


if __name__ == "__main__":
    main()
