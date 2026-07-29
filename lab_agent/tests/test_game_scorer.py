"""Tests for the v4 gameplay scorer: action sanitation (anti-forgery) and the
K-run scoring/aggregation flow (episode driving mocked — no live DF needed)."""

import pytest

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


@pytest.mark.parametrize("garbage", [None, 42, "not a list", 3.14, True, {"nope": 1}])
def test_sanitize_actions_survives_any_shape(garbage):
    """The controller is untrusted code — it can return literally anything. A bad shape
    must cost the agent its actions, never raise into the evaluator. (Regression: a bare
    int used to raise TypeError out of the anti-forgery gate.)"""
    assert game_scorer.sanitize_actions(garbage) == []


def test_sanitize_actions_accepts_a_bare_dict():
    """Returning one action unwrapped is natural for a policy; it must not be silently
    dropped, but the verb is still allow-listed."""
    assert game_scorer.sanitize_actions({"command": "set_labor", "args": ["MINE", True]}) == \
        [{"verb": "set_labor", "args": ["MINE", True]}]
    assert game_scorer.sanitize_actions({"command": "rm -rf", "args": ["/"]}) == []


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


def test_controller_observation_is_policy_compatible():
    obs = game_scorer.controller_observation(game_scorer.PINNED_T0)
    assert obs["cur_tick"] == game_scorer.PINNED_T0.abs_tick
    assert obs["gametype"] == "DWARF_FORTRESS"
    assert len(obs["units"]) == 7                     # legacy step-loop policies read units
    assert "create_stockpile" in obs["available_actions"]
    assert obs["hunger_sum"] == 7                     # v4 scored fields still present


def test_score_submission_calls_on_episode(monkeypatch):
    """on_episode(done, total) fires after every episode (evaluate_job_v4 wires it to
    the heartbeat so a long K-run eval keeps its job lease alive)."""
    T0 = game_scorer.PINNED_T0
    monkeypatch.setattr(game_scorer, "run_scored_episode",
                        lambda cf, h, suppress=False: (T0, _GOOD_H))
    calls = []
    game_scorer.score_submission(lambda o: [], horizon_ticks=36000, k=3,
                                 noop_composite=0.2, ref_composite=0.6,
                                 on_episode=lambda d, t: calls.append((d, t)))
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_regime_key_stable_and_sensitive():
    base = dict(scenario_id="s1", save_sha256="abc", df_version="53.15",
                dfhack_version="53.15-r2", plugin_set_hash="p1", horizon_ticks=3600, k=5)
    k0 = game_scorer.regime_key(**base)
    assert k0 == game_scorer.regime_key(**base)                                  # stable
    assert k0 != game_scorer.regime_key(**{**base, "horizon_ticks": 12000})      # horizon
    assert k0 != game_scorer.regime_key(**{**base, "scenario_id": "s2"})         # scenario
    assert k0 != game_scorer.regime_key(**{**base, "df_version": "54.0"})        # engine
    assert k0 != game_scorer.regime_key(
        **{**base, "weights": {"provisioning": 0.5, "comfort": 0.2, "development": 0.3}})  # weights
