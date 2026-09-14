"""The player package (repo root /player) has no heavy dependencies at inference time and
these tests keep it that way: featurize, the label codec, the Student forward pass and
widen() all run on pure Python."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player import imitation, widen                                       # noqa: E402
from player.imitation import FEATURE_NAMES, Student, action_key, featurize, key_action  # noqa: E402

WEIGHTS = ROOT / "player" / "weights"


def test_featurize_is_the_length_of_feature_names_on_any_obs():
    assert len(featurize({})) == len(FEATURE_NAMES)
    obs = {"round": 3, "rounds_total": 24, "cohort_alive": 7, "cohort_size": 7,
           "food_count": 12, "drink_count": 12, "built_by_type": {"Butchers": 1}}
    x = featurize(obs)
    assert len(x) == len(FEATURE_NAMES)
    assert all(isinstance(v, float) for v in x)


def test_features_are_only_ever_appended():
    # widen() depends on this: older weights are extended, never re-ordered. The first
    # 44 are the 2026-09-12 set, then the dig backlog pair, then the three shop kinds,
    # then the hungry-year block; a saved model's feature list must be a prefix.
    names = list(FEATURE_NAMES)
    assert names.index("designated_log") == 44
    shops = [n for n in names if any(k in n for k in imitation.NEW_SHOP_KINDS)]
    assert names.index(shops[0]) == 46 and len(shops) == 6
    assert names[52:61] == ["hunger_per_dwarf", "thirst_per_dwarf", "livestock_log", "livestock_marked_log",
                            "season_spring", "season_summer", "season_autumn", "season_winter", "year_frac"]
    assert names[61] == "fish_raw_log"


def test_an_older_model_is_widened_on_load_and_unchanged():
    old_names = FEATURE_NAMES[:52]
    old = _tiny_model(old_names)
    s = Student(old)                                   # 52 -> 61 on load
    assert s.features == list(FEATURE_NAMES)
    obs = {"round": 5, "rounds_total": 24, "cohort_alive": 7, "cohort_size": 7, "season": 3,
           "hunger_sum": 300000, "livestock": 4, "food_count": 3, "built_by_type": {"Butchers": 2}}
    x_old = featurize(obs)[:52]
    import math

    def forward(model, x):
        for i, L in enumerate(model["layers"]):
            y = [sum(w * v for w, v in zip(row, x)) + b for row, b in zip(L["W"], L["b"])]
            x = [v if v > 0 else 0.0 for v in y] if i < len(model["layers"]) - 1 else y
        return x
    assert s.probabilities(obs) == pytest.approx([1 / (1 + math.exp(-v)) for v in forward(old, x_old)], abs=1e-12)


@pytest.mark.parametrize("action", [
    {"command": "set_labor", "args": ["MINE", True]},
    {"command": "designate_dig", "args": [24]},
    {"command": "slaughter_animal", "args": [3]},
    {"command": "build", "args": ["Butchers"]},
])
def test_action_key_round_trips(action):
    assert key_action(action_key(action)) == action


def _tiny_model(features):
    n = len(features)
    return {"features": list(features), "labels": ["designate_dig|24", "slaughter_animal|3"],
            "norm": {"mean": [0.0] * n, "std": [1.0] * n},
            "layers": [{"W": [[0.1 * (i + 1) for i in range(n)]] * 4, "b": [0.0] * 4},
                       {"W": [[0.5] * 4, [-0.5] * 4], "b": [0.2, -0.2]}]}


def test_widen_keeps_the_forward_pass_identical():
    old_names = FEATURE_NAMES[:49]
    old = _tiny_model(old_names)
    new = widen.widen(old)
    assert new["features"] == list(FEATURE_NAMES)
    # the widened model on a real observation equals the old model on the truncated vector
    obs = {"round": 5, "rounds_total": 24, "cohort_alive": 7, "cohort_size": 7,
           "food_count": 3, "drink_count": 0, "built_by_type": {"Butchers": 2, "Still": 1}}
    s_new = Student(new)
    x_old = featurize(obs)[:len(old_names)]

    def forward(model, x):
        for i, L in enumerate(model["layers"]):
            y = [sum(w * v for w, v in zip(row, x)) + b for row, b in zip(L["W"], L["b"])]
            x = [v if v > 0 else 0.0 for v in y] if i < len(model["layers"]) - 1 else y
        return x
    import math
    old_probs = [1 / (1 + math.exp(-v)) for v in forward(old, x_old)]
    assert s_new.probabilities(obs) == pytest.approx(old_probs, abs=1e-12)


def test_widen_refuses_a_reordered_feature_set():
    with pytest.raises(ValueError):
        widen.widen(_tiny_model(list(reversed(FEATURE_NAMES[:49]))))


@pytest.mark.skipif(not (WEIGHTS / "student_evolved_v1.json").exists(), reason="weights not checked in")
def test_the_committed_champion_still_loads_after_widening():
    model = json.loads((WEIGHTS / "student_evolved_v1.json").read_text(encoding="utf-8"))
    s = Student(widen.widen(model))
    acts = s({"round": 0, "rounds_total": 24, "cohort_alive": 7, "cohort_size": 7})
    assert isinstance(acts, list) and acts


def test_split_count_factors_only_count_verbs():
    from player.imitation import split_count
    assert split_count("designate_dig|120") == ("designate_dig|#", 120)
    assert split_count("slaughter_animal|3") == ("slaughter_animal|#", 3)
    assert split_count("set_labor|MINE|True") == ("set_labor|MINE|True", None)
    assert split_count("build_workshop|Butchers") == ("build_workshop|Butchers", None)


@pytest.mark.skipif(not (WEIGHTS / "student_v4.json").exists(), reason="weights not checked in")
def test_factored_student_emits_counts_inside_the_catalogue_and_matches_numpy():
    np = pytest.importorskip("numpy")
    from player import train_imitation as ti
    from player.imitation import COUNT_VERBS, widen_weights
    model = widen_weights(json.loads((WEIGHTS / "student_v4.json").read_text(encoding="utf-8")))
    s = Student(model)
    assert s.counts, "v4 is a factored model"
    rows = [json.loads(l) for l in (ROOT / "player" / "traj" / "fresh.jsonl").read_text(encoding="utf-8").splitlines()[:5]]
    n = len(FEATURE_NAMES)
    for r in rows:
        r["x"] = list(r["x"]) + [0.0] * (n - len(r["x"]))
    # the pure-Python forward pass and the numpy one agree on identical vectors
    X = np.array([r["x"] for r in rows])
    P = ti.predict(model, X)
    import math
    for r, p_np in zip(rows, P):
        x = [(v - m) / (sd if sd > 1e-9 else 1.0) for v, m, sd in zip(r["x"], s.mean, s.std)]
        for i, (W, b) in enumerate(s.layers):
            y = [sum(wi * xi for wi, xi in zip(row, x)) + bi for row, bi in zip(W, b)]
            x = [v if v > 0 else 0.0 for v in y] if i < len(s.layers) - 1 else y
        p_py = [1 / (1 + math.exp(-v)) for v in x[: len(s.labels)]]
        assert p_py == pytest.approx(list(p_np), abs=1e-9)
    # a count-carrying verb comes out as an integer inside the catalogue range
    obs = {"round": 0, "rounds_total": 24, "ticks_remaining": 3600, "cohort_alive": 7, "cohort_size": 7,
           "food_count": 12, "drink_count": 12}
    qty = s.quantities(obs)
    for label, n in qty.items():
        lo, hi = COUNT_VERBS[label.split("|")[0]]
        assert isinstance(n, int) and lo <= n <= hi
    acts = s(obs)
    for a in acts:
        if a["command"] in COUNT_VERBS:
            assert isinstance(a["args"][0], int) and a["args"][0] >= 1
