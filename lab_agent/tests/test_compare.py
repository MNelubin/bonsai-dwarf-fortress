"""Tests for the face-to-face comparison. The two guardrails — regime equality and
"one run is not a result" — are the whole point of this module, so most of these
tests are about refusing to draw a conclusion rather than drawing one."""

import pytest

from bonsai_lab_agent import compare
from bonsai_lab_agent import recorder as rec
from bonsai_lab_agent import stepped_episode as se

from tests.test_stepped_episode import FakeSession


def make_rec(tmp_path, name, *, regime="r1", horizon=1200, rounds=4,
             policy=None, cohort=("11", "12", "13"), die_after=None):
    path = str(tmp_path / f"{name}.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path, meta={"episode_id": name, "regime_key": regime})
    se.run_stepped_episode(policy or (lambda o: []), horizon_ticks=horizon, rounds=rounds,
                           session=FakeSession(cohort=cohort, die_after=die_after),
                           recorder=r)
    r.close()
    return path


DEVELOPER = lambda o: [{"command": "create_stockpile", "args": [1]}]        # noqa: E731
IDLER = lambda o: [{"command": "advance"}]                                   # noqa: E731


# ------------------------------------------------------------------ guardrail 1
def test_refuses_to_compare_across_regimes(tmp_path):
    a = make_rec(tmp_path, "a", regime="r1")
    b = make_rec(tmp_path, "b", regime="r2")
    with pytest.raises(compare.RegimeMismatch) as e:
        compare.compare_runs(a, b)
    assert "r1" in str(e.value) and "r2" in str(e.value)


def test_regime_check_can_be_overridden_deliberately(tmp_path):
    a = make_rec(tmp_path, "a", regime="r1")
    b = make_rec(tmp_path, "b", regime="r2")
    out = compare.compare_runs(a, b, require_same_regime=False)
    assert out["a"]["regime_key"] == "r1" and out["b"]["regime_key"] == "r2"


# ------------------------------------------------------------------ guardrail 2
def test_without_k_run_scores_the_result_is_marked_anecdotal(tmp_path):
    """A single episode of a stochastic game must never present as a measurement."""
    a = make_rec(tmp_path, "a", policy=DEVELOPER)
    b = make_rec(tmp_path, "b", policy=IDLER)
    out = compare.compare_runs(a, b)
    assert out["distribution"]["comparable"] is False
    assert "anecdote" in out["distribution"]["reason"]
    assert "winner" not in out["distribution"]


def test_overlapping_distributions_declare_no_winner(tmp_path):
    """The gap is inside the noise — the honest answer is 'cannot tell', not a winner."""
    a = make_rec(tmp_path, "a", policy=DEVELOPER)
    b = make_rec(tmp_path, "b", policy=IDLER)
    out = compare.compare_runs(a, b, a_scores=[0.50, 0.62, 0.44],
                               b_scores=[0.48, 0.58, 0.41])
    d = out["distribution"]
    assert d["comparable"] and not d["separated"]
    assert d["winner"] is None
    assert "not distinguishable" in d["reason"] and "raise K" in d["reason"]


def test_clearly_separated_distributions_name_a_winner(tmp_path):
    a = make_rec(tmp_path, "a", policy=DEVELOPER)
    b = make_rec(tmp_path, "b", policy=IDLER)
    out = compare.compare_runs(a, b, a_scores=[0.90, 0.91, 0.89],
                               b_scores=[0.10, 0.12, 0.11],
                               a_label="k2-v7", b_label="baseline")
    d = out["distribution"]
    assert d["separated"] and d["winner"] == "k2-v7"
    assert d["gap"] > d["noise"]


def test_two_runs_are_not_enough_to_separate(tmp_path):
    """Even a wide gap needs at least 3 runs a side before we call it."""
    a = make_rec(tmp_path, "a")
    b = make_rec(tmp_path, "b")
    d = compare.compare_runs(a, b, a_scores=[0.9, 0.9], b_scores=[0.1, 0.1])["distribution"]
    assert not d["separated"] and d["winner"] is None


# ------------------------------------------------------------------ the content
def test_final_deltas_show_who_built_more(tmp_path):
    a = make_rec(tmp_path, "a", policy=DEVELOPER)
    b = make_rec(tmp_path, "b", policy=IDLER)
    out = compare.compare_runs(a, b)
    fd = out["final_deltas"]
    assert fd["buildings"]["a"] > fd["buildings"]["b"]
    assert fd["buildings"]["delta"] == fd["buildings"]["a"] - fd["buildings"]["b"]


def test_divergence_points_at_when_they_parted(tmp_path):
    a = make_rec(tmp_path, "a", policy=DEVELOPER)
    b = make_rec(tmp_path, "b", policy=IDLER)
    div = compare.compare_runs(a, b)["divergence"]
    assert div["buildings"] is not None
    assert div["buildings"]["a"] != div["buildings"]["b"]
    assert div["buildings"]["sample"] >= 0


def test_identical_runs_show_no_divergence(tmp_path):
    a = make_rec(tmp_path, "a", policy=IDLER)
    b = make_rec(tmp_path, "b", policy=IDLER)
    div = compare.compare_runs(a, b)["divergence"]
    assert div["buildings"] is None and div["alive"] is None


def test_unequal_decision_counts_are_flagged_as_unfair(tmp_path):
    """More rounds means more agency — a real confound, not a skill difference."""
    a = make_rec(tmp_path, "a", rounds=8)
    b = make_rec(tmp_path, "b", rounds=4)
    out = compare.compare_runs(a, b)
    assert any("more agency" in w for w in out["warnings"])


def test_unequal_horizons_are_flagged(tmp_path):
    a = make_rec(tmp_path, "a", horizon=1200)
    b = make_rec(tmp_path, "b", horizon=2400)
    assert any("different horizons" in w for w in compare.compare_runs(a, b)["warnings"])


def test_death_shows_up_in_the_comparison(tmp_path):
    a = make_rec(tmp_path, "a", policy=DEVELOPER)
    b = make_rec(tmp_path, "b", policy=DEVELOPER, die_after=2)
    fd = compare.compare_runs(a, b)["final_deltas"]
    assert fd["alive"]["a"] == 3 and fd["alive"]["b"] == 2


def test_decisions_are_carried_for_the_diff_view(tmp_path):
    a = make_rec(tmp_path, "a", policy=lambda o: [
        {"command": "create_stockpile", "args": [1]}, {"command": "hack_the_score"}])
    out = compare.compare_runs(a, make_rec(tmp_path, "b"))
    d0 = out["a"]["decisions"][0]
    assert d0["dispatched"] == ["create_stockpile"]
    assert d0["dropped"] == ["hack_the_score"]


def test_unreadable_recording_is_a_clear_error(tmp_path):
    empty = tmp_path / "empty.rec.jsonl.gz"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="no readable events"):
        compare.load_summary(str(empty))


def test_format_report_is_printable(tmp_path):
    a = make_rec(tmp_path, "a", policy=DEVELOPER)
    b = make_rec(tmp_path, "b", policy=IDLER)
    txt = compare.format_report(compare.compare_runs(
        a, b, a_scores=[0.9, 0.9, 0.88], b_scores=[0.1, 0.1, 0.12],
        a_label="champion", b_label="challenger"))
    assert "champion" in txt and "buildings" in txt and "verdict" in txt
