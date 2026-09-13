"""Train the Student on teacher trajectories. numpy only, CPU only, seconds not hours.

    python -m player.train_imitation traj/*.jsonl -o player/weights/student.json

A multi-label classifier: each of the teacher's distinct actions is one output, and the
Student later emits every action whose probability clears a threshold. The default is a
one-hidden-layer MLP because the teacher IS a small set of rules over these features and
anything larger would be memorising the episode rather than the policy -- but that is a
claim, so `--layers` takes any shape ("" for linear, "64", "64,64") and `--sweep` fits
the usual shortlist on the same held-out episodes and prints one line each, so the claim
is measured rather than repeated.

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

from player.imitation import COUNT_MARK, FEATURE_NAMES, split_count


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


def factor(Y: list[list[str]]) -> tuple[list[list[str]], list[dict[str, int]]]:
    """Per row: the factored labels, and {label: count} for the ones that carry one."""
    labels_rows, count_rows = [], []
    for ys in Y:
        ls, cs = [], {}
        for y in ys:
            k, c = split_count(y)
            ls.append(k)
            if c is not None:
                cs[k] = c
        labels_rows.append(sorted(set(ls))); count_rows.append(cs)
    return labels_rows, count_rows


def train(X, Y, labels, layers=(64,), epochs=400, lr=1e-2, seed=0, l2=1e-4, factored=True):
    """Any depth; `layers=()` is a linear model. Adam on weighted BCE, full batch.

    factored=True splits count-carrying verbs into a fire/no-fire label and a log1p(count)
    regression, appended as extra linear output rows (see imitation.COUNT_VERBS). The
    regression is fit only on rows where the verb fired.
    """
    rng = np.random.default_rng(seed)
    Yl, Yc = factor(Y) if factored else (Y, [{} for _ in Y])
    counts = [k for k in labels if COUNT_MARK in k] if factored else []
    idx = {k: i for i, k in enumerate(labels)}; cidx = {k: i for i, k in enumerate(counts)}
    T = np.zeros((len(Yl), len(labels)))
    for r, ys in enumerate(Yl):
        for y in ys:
            T[r, idx[y]] = 1.0
    C = np.zeros((len(Yl), len(counts))); M = np.zeros_like(C)          # log1p targets, mask
    for r, cs in enumerate(Yc):
        for k, c in cs.items():
            C[r, cidx[k]] = np.log1p(c); M[r, cidx[k]] = 1.0
    cmean = np.array([C[:, j][M[:, j] > 0].mean() if M[:, j].any() else 0.0 for j in range(len(counts))])
    cstd = np.array([C[:, j][M[:, j] > 0].std() + 1e-3 if M[:, j].any() else 1.0 for j in range(len(counts))])
    Cn = (C - cmean) / cstd
    mean, std = X.mean(0), X.std(0) + 1e-9
    Xn = (X - mean) / std
    n_lab, n_cnt = len(labels), len(counts)
    sizes = [Xn.shape[1], *layers, n_lab + n_cnt]
    Ws = [rng.normal(0, 1 / np.sqrt(a), (b, a)) for a, b in zip(sizes, sizes[1:])]
    bs = [np.zeros(b) for b in sizes[1:]]
    # positive labels are rare (one action in ~24 rounds); weight them so the net does
    # not learn that "never act" is 95% accurate
    pos = T.mean(0); pw = np.clip((1 - pos) / (pos + 1e-6), 1, 30)
    params = [*Ws, *bs]
    m = [np.zeros_like(p) for p in params]; v = [np.zeros_like(p) for p in params]
    for ep in range(1, epochs + 1):
        acts = [Xn]
        for W, b in zip(Ws, bs):
            z = acts[-1] @ W.T + b
            acts.append(np.maximum(0, z) if len(acts) < len(Ws) else z)
        Z = acts[-1]
        P = 1 / (1 + np.exp(-Z[:, :n_lab]))
        G_lab = (P - T) * (T * pw + (1 - T)) / len(Xn)                     # weighted BCE gradient
        G_cnt = (Z[:, n_lab:] - Cn) * M / max(1.0, M.sum())                # masked MSE gradient
        G = np.concatenate([G_lab, G_cnt], axis=1)
        gWs, gbs = [None] * len(Ws), [None] * len(Ws)
        for i in range(len(Ws) - 1, -1, -1):
            gWs[i] = G.T @ acts[i] + l2 * Ws[i]; gbs[i] = G.sum(0)
            if i:
                G = (G @ Ws[i]) * (acts[i] > 0)
        for i, (p, g) in enumerate(zip(params, [*gWs, *gbs])):
            m[i] = 0.9 * m[i] + 0.1 * g; v[i] = 0.999 * v[i] + 0.001 * g * g
            p -= lr * (m[i] / (1 - 0.9 ** ep)) / (np.sqrt(v[i] / (1 - 0.999 ** ep)) + 1e-8)
    return {"features": list(FEATURE_NAMES), "labels": labels, "counts": counts,
            "count_norm": {"mean": cmean.tolist(), "std": cstd.tolist()},
            "norm": {"mean": mean.tolist(), "std": std.tolist()},
            "layers": [{"W": W.tolist(), "b": b.tolist()} for W, b in zip(Ws, bs)],
            "threshold": 0.5, "hidden": list(layers), "epochs": epochs, "rows": int(len(Xn))}


def forward(model, X):
    mean, std = np.array(model["norm"]["mean"]), np.array(model["norm"]["std"])
    x = (X - mean) / std
    for i, L in enumerate(model["layers"]):
        x = x @ np.array(L["W"]).T + np.array(L["b"])
        if i < len(model["layers"]) - 1:
            x = np.maximum(0, x)
    return x


def predict(model, X):
    """Label probabilities only (the count rows are separate, see predict_counts)."""
    return 1 / (1 + np.exp(-forward(model, X)[:, : len(model["labels"])]))


def predict_counts(model, X):
    """label -> predicted count per row, on the natural scale."""
    z = forward(model, X)[:, len(model["labels"]):]
    cm, cs = np.array(model["count_norm"]["mean"]), np.array(model["count_norm"]["std"])
    return {k: np.expm1(z[:, j] * cs[j] + cm[j]) for j, k in enumerate(model.get("counts") or [])}


def targets(Y, labels):
    idx = {k: i for i, k in enumerate(labels)}
    T = np.zeros((len(Y), len(labels)), dtype=bool)
    for r, ys in enumerate(factor(Y)[0]):
        for y in ys:
            T[r, idx[y]] = True
    return T


def summary(model, X, Y, labels) -> dict:
    """Macro F1 over labels present in the held-out set, plus exact-set match."""
    P = predict(model, X) >= model["threshold"]; T = targets(Y, labels)
    f1s = []
    for i in range(len(labels)):
        tp = int((P[:, i] & T[:, i]).sum()); fp = int((P[:, i] & ~T[:, i]).sum()); fn = int((~P[:, i] & T[:, i]).sum())
        if tp + fn:
            f1s.append(2 * tp / (2 * tp + fp + fn))
    return {"macro_f1": float(np.mean(f1s)) if f1s else float("nan"),
            "exact": float((P == T).all(1).mean()), "params": sum(np.array(L["W"]).size + len(L["b"]) for L in model["layers"])}


def report(model, X, Y, labels):
    P = predict(model, X) >= model["threshold"]; T = targets(Y, labels)
    Yl, Yc = factor(Y)
    if model.get("counts"):
        Q = predict_counts(model, X)
        print(f"{'count':44} {'n':>4} {'teacher':>8} {'student':>8}   (mean where the verb fired)")
        for k in model["counts"]:
            rows_ = [(cs[k], q) for cs, q in zip(Yc, Q[k]) if k in cs]
            if rows_:
                print(f"{k:44} {len(rows_):4} {np.mean([a for a, _ in rows_]):8.1f} {np.mean([b for _, b in rows_]):8.1f}")
    print(f"{'action':44} {'n':>4} {'prec':>6} {'rec':>6}")
    for i, k in enumerate(labels):
        tp = int((P[:, i] & T[:, i]).sum()); fp = int((P[:, i] & ~T[:, i]).sum()); fn = int((~P[:, i] & T[:, i]).sum())
        prec = tp / (tp + fp) if tp + fp else float("nan"); rec = tp / (tp + fn) if tp + fn else float("nan")
        print(f"{k:44} {int(T[:, i].sum()):4} {prec:6.2f} {rec:6.2f}")
    s = summary(model, X, Y, labels)
    print(f"rows={len(X)} exact-set match={s['exact']:.3f} macro-F1={s['macro_f1']:.3f} params={s['params']}")


def parse_layers(text: str) -> tuple:
    return tuple(int(t) for t in text.split(",") if t.strip())


SWEEP = ("", "32", "64", "128", "64,64")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("traj", nargs="+"); ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--layers", default="64", help='hidden sizes, e.g. "" (linear), "64", "64,64"')
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--holdout", type=float, default=0.2); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sweep", action="store_true", help="fit %s on the same split and report each" % (SWEEP,))
    a = ap.parse_args()
    X, Y, rows = load(a.traj)
    labels = sorted({split_count(y)[0] for ys in Y for y in ys})
    # hold out whole EPISODES, not rows: rows of one episode are near-duplicates
    eps = sorted({(r["_src"], r["episode"]) for r in rows})
    random.Random(a.seed).shuffle(eps)
    held = set(eps[: max(1, int(len(eps) * a.holdout))])
    tr = np.array([(r["_src"], r["episode"]) not in held for r in rows])
    Ytr = [y for y, t in zip(Y, tr) if t]; Yte = [y for y, t in zip(Y, tr) if not t]
    print(f"episodes={len(eps)} held-out={len(held)} rows train={tr.sum()} test={(~tr).sum()} labels={len(labels)}")
    if a.sweep:
        # leave-one-EPISODE-out: with nine episodes a single held-out split is one fort's
        # one run, and a label that only fires on the hungry month is either all in the
        # training set or all in the test set. Pool the out-of-fold predictions instead.
        print(f"\n{'layers':>8} {'params':>7} {'macroF1':>8} {'exact':>6}   (leave-one-episode-out, pooled)")
        ep_of = np.array([eps.index((r["_src"], r["episode"])) for r in rows])
        for shape in SWEEP:
            P = np.zeros((len(rows), len(labels)), dtype=bool); params = 0
            for e in range(len(eps)):
                fold = ep_of != e
                m = train(X[fold], [y for y, t in zip(Y, fold) if t], labels, parse_layers(shape), a.epochs, seed=a.seed)
                P[~fold] = predict(m, X[~fold]) >= m["threshold"]
                params = sum(np.array(L["W"]).size + len(L["b"]) for L in m["layers"])
            T = targets(Y, labels); f1s = []
            for i in range(len(labels)):
                tp = int((P[:, i] & T[:, i]).sum()); fp = int((P[:, i] & ~T[:, i]).sum()); fn = int((~P[:, i] & T[:, i]).sum())
                if tp + fn:
                    f1s.append(2 * tp / (2 * tp + fp + fn))
            print(f"{shape or 'linear':>8} {params:7} {np.mean(f1s):8.3f} {(P == T).all(1).mean():6.3f}")
    layers = parse_layers(a.layers)
    model = train(X[tr], Ytr, labels, layers, a.epochs, seed=a.seed)
    print(f"\n--- held-out episodes, layers={list(layers)} ---")
    report(model, X[~tr], Yte, labels)
    final = train(X, Y, labels, layers, a.epochs, seed=a.seed)      # refit on everything to ship
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(final), encoding="utf-8")
    print(f"\nwrote {a.out} ({Path(a.out).stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
