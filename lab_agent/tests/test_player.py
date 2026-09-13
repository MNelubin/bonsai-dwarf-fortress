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


def test_the_new_shop_kinds_are_appended_not_inserted():
    # widen() depends on this: older weights are extended, never re-ordered
    tail = FEATURE_NAMES[-len(imitation.NEW_SHOP_KINDS):]
    assert all(any(k in name for k in imitation.NEW_SHOP_KINDS) for name in tail)


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
    old_names = FEATURE_NAMES[:-len(imitation.NEW_SHOP_KINDS)]
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
        widen.widen(_tiny_model(list(reversed(FEATURE_NAMES[:-3]))))


@pytest.mark.skipif(not (WEIGHTS / "student_evolved_v1.json").exists(), reason="weights not checked in")
def test_the_committed_champion_still_loads_after_widening():
    model = json.loads((WEIGHTS / "student_evolved_v1.json").read_text(encoding="utf-8"))
    s = Student(widen.widen(model))
    acts = s({"round": 0, "rounds_total": 24, "cohort_alive": 7, "cohort_size": 7})
    assert isinstance(acts, list) and acts
