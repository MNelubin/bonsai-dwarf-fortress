"""Train the Student on teacher trajectories. numpy only, CPU only, seconds not hours.

    python -m player.train_imitation traj/*.jsonl -o player/weights/student.json

A multi-label classifier: each of the teacher's distinct actions is one output, and the
Student later emits every action whose probability clears a threshold. The model is a
one-hidden-layer MLP because the teacher IS a small set of rules over these features and
anything larger would be memorising the episode rather than the policy.

The report at the end is the thing to read: per-action precision/recall on a held-out
split, so a label the student never fires is visible before it costs an episode.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
from pathlib import Path

import numpy as np

from player.imitation import FEATURE_NAMES


def load(paths: list[str]) -> tuple[np.ndarray, list[list[str]], list[dict]]:
    rows = []
    for pattern in paths:
        for p in glob.glob(pattern):
            with open(p, encoding="utf-8") as f:
                for l in f:
                    if l.strip():
                        r = json.loads(l)
                        r["_src"] = p          # parallel collectors all number from 0
                        rows.append(r)
    X = np.array([r["x"] for r in rows], dtype=np.float64)
    Y = [r["y"] for r in rows]
    return X, Y, rows


def train(X, Y, labels, hidden=64, epochs=400, lr=1e-2, seed=0, l2=1e-4):
    rng = np.random.default_rng(seed)
    idx = {k: i for i, k in enumerate(labels)}
    T = np.zeros((len(Y), len(labels)))
    for r, ys in enumerate(Y):
        for y in ys:
            T[r, idx[y]] = 1.0
    mean, std = X.mean(0), X.std(0) + 1e-9
    Xn = (X - mean) / std
    n_in, n_out = Xn.shape[1], len(labels)
    W1 = rng.normal(0, 1 / np.sqrt(n_in), (hidden, n_in)); b1 = np.zeros(hidden)
    W2 = rng.normal(0, 1 / np.sqrt(hidden), (n_out, hidden)); b2 = np.zeros(n_out)
    # positive labels are rare (one action in ~24 rounds); weight them so the net does
    # not learn that "never act" is 95% accurate
    pos = T.mean(0); pw = np.clip((1 - pos) / (pos + 1e-6), 1, 30)
    m = [np.zeros_like(p) for p in (W1, b1, W2, b2)]; v = [np.zeros_like(p) for p in m]
    for ep in range(1, epochs + 1):
        H = np.maximum(0, Xn @ W1.T + b1)
        Z = H @ W2.T + b2
        P = 1 / (1 + np.exp(-Z))
        G = (P - T) * (T * pw + (1 - T)) / len(Xn)           # weighted BCE gradient
        gW2 = G.T @ H + l2 * W2; gb2 = G.sum(0)
        GH = (G @ W2) * (H > 0)
        gW1 = GH.T @ Xn + l2 * W1; gb1 = GH.sum(0)
        for i, (p, g) in enumerate(zip((W1, b1, W2, b2), (gW1, gb1, gW2, gb2))):
            m[i] = 0.9 * m[i] + 0.1 * g; v[i] = 0.999 * v[i] + 0.001 * g * g
            p -= lr * (m[i] / (1 - 0.9 ** ep)) / (np.sqrt(v[i] / (1 - 0.999 ** ep)) + 1e-8)
    return {"features": list(FEATURE_NAMES), "labels": labels,
            "norm": {"mean": mean.tolist(), "std": std.tolist()},
            "layers": [{"W": W1.tolist(), "b": b1.tolist()}, {"W": W2.tolist(), "b": b2.tolist()}],
            "threshold": 0.5, "hidden": hidden, "epochs": epochs, "rows": int(len(Xn))}


def predict(model, X):
    mean, std = np.array(model["norm"]["mean"]), np.array(model["norm"]["std"])
    x = (X - mean) / std
    for i, L in enumerate(model["layers"]):
        x = x @ np.array(L["W"]).T + np.array(L["b"])
        x = np.maximum(0, x) if i < len(model["layers"]) - 1 else 1 / (1 + np.exp(-x))
    return x


def report(model, X, Y, labels):
    P = predict(model, X) >= model["threshold"]
    idx = {k: i for i, k in enumerate(labels)}
    T = np.zeros_like(P)
    for r, ys in enumerate(Y):
        for y in ys:
            T[r, idx[y]] = True
    print(f"{'action':44} {'n':>4} {'prec':>6} {'rec':>6}")
    for k, i in idx.items():
        tp = int((P[:, i] & T[:, i]).sum()); fp = int((P[:, i] & ~T[:, i]).sum()); fn = int((~P[:, i] & T[:, i]).sum())
        prec = tp / (tp + fp) if tp + fp else float("nan"); rec = tp / (tp + fn) if tp + fn else float("nan")
        print(f"{k:44} {int(T[:, i].sum()):4} {prec:6.2f} {rec:6.2f}")
    exact = float((P == T).all(1).mean())
    print(f"rows={len(X)} exact-set match={exact:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("traj", nargs="+"); ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--hidden", type=int, default=64); ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--holdout", type=float, default=0.2); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    X, Y, rows = load(a.traj)
    labels = sorted({y for ys in Y for y in ys})
    # hold out whole EPISODES, not rows: rows of one episode are near-duplicates
    eps = sorted({(r["_src"], r["episode"]) for r in rows})
    random.Random(a.seed).shuffle(eps)
    held = set(eps[: max(1, int(len(eps) * a.holdout))])
    tr = np.array([(r["_src"], r["episode"]) not in held for r in rows])
    print(f"episodes={len(eps)} held-out={len(held)} rows train={tr.sum()} test={(~tr).sum()} labels={len(labels)}")
    model = train(X[tr], [y for y, t in zip(Y, tr) if t], labels, a.hidden, a.epochs, seed=a.seed)
    print("\n--- held-out episodes ---")
    report(model, X[~tr], [y for y, t in zip(Y, tr) if not t], labels)
    final = train(X, Y, labels, a.hidden, a.epochs, seed=a.seed)      # refit on everything to ship
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(final), encoding="utf-8")
    print(f"\nwrote {a.out} ({Path(a.out).stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
