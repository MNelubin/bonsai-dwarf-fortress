"""Tests for the v4 gameplay scorer: action sanitation (anti-forgery) and the
K-run scoring/aggregation flow (episode driving mocked — no live DF needed)."""

from bonsai_lab_agent import game_scorer
from bonsai_lab_agent.scoring import EpisodeObs, raw_components


def test_sanitize_actions_allowlist():
    raw = [
        {"command": "set_labor", "args": ["MINE", True]},
        {"command": "designate_dig", "args": [30]},
        {"command": "rm -rf", "args": ["/"]},          # not allow-listed -> dropped
        {"name": "create_stockpile", "args": [3]},
        "not a dict",                                    # dropped
        {"command": "add_workorder"},                    # no args -> []
    ]
    clean = game_scorer.sanitize_actions(raw)
    assert [a["verb"] for a in clean] == \
        ["set_labor", "designate_dig", "create_stockpile", "add_workorder"]
    assert clean[-1]["args"] == []


def test_write_actions_format(tmp_path, monkeypatch):
    f = tmp_path / "actions.txt"
    monkeypatch.setattr(game_scorer, "ACTIONS_FILE", str(f))
    game_scorer._write_actions([
        {"verb": "set_labor", "args": ["MINE", True]},
        {"verb": "create_stockpile", "args": [5]},
    ])
    lines = f.read_text().splitlines()
    assert lines[0] == "set_labor\tMINE\tTrue"
    assert lines[1] == "create_stockpile\t5"


_GOOD_H = EpisodeObs(abs_tick=2052801, cohort_alive=7, cohort_size=7, hunger_sum=70000,
                     thirst_sum=50000, stress_danger=0, food_count=30, drink_count=30,
                     buildings=6, dug_tiles=150, workorders_done=15)


def test_score_submission_good_policy(monkeypatch):
    T0 = game_scorer.PINNED_T0

    def fake_ep(controller_fn, horizon, suppress=False):
        controller_fn(T0.__dict__)  # exercise the controller path
        return T0, _GOOD_H

    monkeypatch.setattr(game_scorer, "run_scored_episode", fake_ep)
    ref = raw_components(_GOOD_H, T0, 36000)["composite"]
    res = game_scorer.score_submission(
        lambda obs: [{"command": "create_stockpile", "args": [5]}],
        horizon_ticks=36000, k=5, noop_composite=0.26786, ref_composite=ref)
    assert res["suite_name"] == "gameplay_survival_development"
    assert res["suite_version"] == "4"
    assert res["summary"]["episodes_run"] == 5
    assert res["score"] == 1.0                    # good == ref -> normalized 1.0
    assert res["summary"]["trustworthy"]
    assert res["summary"]["all_cohort_survived"]


def test_score_submission_noop_scores_zero(monkeypatch):
    T0 = game_scorer.PINNED_T0
    noop_h = EpisodeObs(abs_tick=2052801, cohort_alive=7, cohort_size=7, hunger_sum=252007,
                        thirst_sum=104000, stress_danger=0, food_count=12, drink_count=12,
                        buildings=1, dug_tiles=0, workorders_done=0)
    monkeypatch.setattr(game_scorer, "run_scored_episode",
                        lambda cf, h, suppress=False: (T0, noop_h))
    noop = raw_components(noop_h, T0, 36000)["composite"]
    ref = raw_components(_GOOD_H, T0, 36000)["composite"]
    res = game_scorer.score_submission(lambda obs: [], horizon_ticks=36000, k=5,
                                       noop_composite=noop, ref_composite=ref)
    assert res["score"] == 0.0                     # no-op sits on the baseline


def test_score_submission_all_episodes_failed(monkeypatch):
    def boom(cf, h, suppress=False):
        raise RuntimeError("load failed")
    monkeypatch.setattr(game_scorer, "run_scored_episode", boom)
    res = game_scorer.score_submission(lambda obs: [], horizon_ticks=3600, k=3,
                                       noop_composite=0.2, ref_composite=0.6)
    assert res["verdict"] == "episode_failed"
    assert res["failure_kind"] == "runtime"
    assert not res["summary"]["trustworthy"]
