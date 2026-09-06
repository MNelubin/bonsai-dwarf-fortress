"""Tests for the drop-in v4 evaluate_job. The server-only evaluator (prepare_checkout,
controller_command) is injected as a fake module so this is testable without the
server. score_submission is mocked (no live DF)."""

import sys
import types

from bonsai_lab_agent import game_evaluate, game_scorer


class FakeConfig:
    controller_timeout_seconds = 30


def _fake_evaluator(monkeypatch):
    fake = types.ModuleType("bonsai_lab_agent.evaluator")
    fake.prepare_checkout = lambda config, job: "/tmp/repo"
    fake.controller_command = lambda repo, manifest: ["python", "-c", "pass"]
    monkeypatch.setitem(sys.modules, "bonsai_lab_agent.evaluator", fake)


def test_uncalibrated_horizon_returns_config_failure(monkeypatch):
    _fake_evaluator(monkeypatch)
    job = {"payload": {"submission_id": "s1", "horizon_ticks": 9999}}  # not in CALIBRATION
    res = game_evaluate.evaluate_job_v4(FakeConfig(), job)
    assert res["verdict"] == "uncalibrated_horizon"
    assert res["failure_kind"] == "config"
    assert res["score"] == 0.0


def test_scored_job_attaches_regime_key_and_hash(monkeypatch):
    _fake_evaluator(monkeypatch)
    monkeypatch.setattr(
        game_scorer, "score_submission",
        lambda cf, **kw: {"suite_name": game_scorer.SUITE_NAME, "suite_version": "4",
                          "score": 0.7, "verdict": "gameplay_scored", "failure_kind": None,
                          "summary": {"trustworthy": True, "episodes_run": kw["k"]},
                          "metrics": []})
    job = {"payload": {"submission_id": "s2", "horizon_ticks": 3600, "k": 4}}  # calibrated
    res = game_evaluate.evaluate_job_v4(FakeConfig(), job)
    assert res["score"] == 0.7
    assert res["submission_id"] == "s2"
    assert len(res["regime_key"]) == 16
    assert len(res["result_hash"]) == 64
    assert res["summary"]["episodes_run"] == 4


def test_default_horizon_and_k(monkeypatch):
    _fake_evaluator(monkeypatch)
    captured = {}

    def fake_score(cf, **kw):
        captured.update(kw)
        return {"suite_name": "x", "suite_version": "4", "score": 0.0, "verdict": "v",
                "failure_kind": None, "summary": {}, "metrics": []}

    monkeypatch.setattr(game_scorer, "score_submission", fake_score)
    game_evaluate.evaluate_job_v4(FakeConfig(), {"payload": {"submission_id": "s3"}})
    assert captured["horizon_ticks"] == game_evaluate.DEFAULT_HORIZON  # 3600 (calibrated)
    assert captured["k"] == game_evaluate.DEFAULT_K
    assert callable(captured["controller_factory"])


def test_evaluator_factory_builds_a_persistent_controller(monkeypatch):
    _fake_evaluator(monkeypatch)
    made = []

    def fake_make(command, repo, round_timeout):
        made.append((command, repo, round_timeout))
        return (lambda obs: []), object()

    def fake_score(cf, controller_factory=None, **kw):
        controller_factory()
        return {"suite_name": "x", "suite_version": "4", "score": 0.0, "verdict": "v",
                "failure_kind": None, "summary": {}, "metrics": []}

    monkeypatch.setattr(game_evaluate, "make_persistent_controller_fn", fake_make)
    monkeypatch.setattr(game_scorer, "score_submission", fake_score)
    game_evaluate.evaluate_job_v4(FakeConfig(), {"payload": {"submission_id": "s3"}})
    assert made == [(["python", "-c", "pass"], "/tmp/repo", 30)]


def test_evaluate_job_v4_heartbeats_between_episodes(monkeypatch):
    _fake_evaluator(monkeypatch)
    beats = []

    class FakeApi:
        def heartbeat(self, job, progress):
            beats.append(progress)

    def fake_score(cf, on_episode=None, **kw):
        if on_episode:
            on_episode(1, kw["k"])            # simulate one episode completing
        return {"suite_name": "x", "suite_version": "4", "score": 0.5, "verdict": "v",
                "failure_kind": None, "summary": {}, "metrics": []}

    monkeypatch.setattr(game_scorer, "score_submission", fake_score)
    game_evaluate.evaluate_job_v4(
        FakeConfig(), {"payload": {"submission_id": "s", "horizon_ticks": 3600, "k": 5}},
        api=FakeApi())
    assert len(beats) == 1
    assert beats[0]["phase"] == "gameplay" and beats[0]["of"] == 5


def test_evaluate_job_v4_keepalive_thread_renews_lease(monkeypatch):
    """A background thread heartbeats every HEARTBEAT_INTERVAL for the whole eval so a
    long episode (> the 120s lease) does not let the lease expire."""
    import time as _t
    _fake_evaluator(monkeypatch)
    monkeypatch.setattr(game_evaluate, "HEARTBEAT_INTERVAL", 0.05)
    beats = []

    class FakeApi:
        def heartbeat(self, job, progress):
            beats.append(progress)

    def slow_score(cf, on_episode=None, **kw):
        _t.sleep(0.3)                       # simulate a long eval (several keepalives)
        return {"suite_name": "x", "suite_version": "4", "score": 0.5, "verdict": "v",
                "failure_kind": None, "summary": {}, "metrics": []}

    monkeypatch.setattr(game_scorer, "score_submission", slow_score)
    game_evaluate.evaluate_job_v4(
        FakeConfig(), {"payload": {"submission_id": "s", "horizon_ticks": 36000}},
        api=FakeApi())
    assert sum(1 for b in beats if b.get("keepalive")) >= 1


def test_calibration_is_keyed_by_save_and_horizon():
    from bonsai_lab_agent.scoring import CALIBRATION, calibration_for

    assert all(isinstance(k, tuple) and len(k) == 2 for k in CALIBRATION), (
        "endpoints keyed by horizon alone score one fort against another fort's baseline"
    )
    assert calibration_for("bonsaifort2", 3600)["noop"] == 0.267857
    # A horizon measured for one fort is not thereby measured for another.
    assert calibration_for("bonsaifort2", 99) is None
    assert calibration_for("a-fort-nobody-measured", 3600) is None
    # Withdrawn on 2026-09-06 because comfort was arithmetically zero when they were
    # taken, then re-measured on the repaired action layer and restored. Each fort keeps
    # its own no-op: the mature one is higher because a running fort works its own order
    # queue even when the policy does nothing. `ref` is the BEST measured tier for that
    # fort, which is not the same tier on both: the survival policy is the ceiling on the
    # fresh embark and falls below idling on the mature one, where Forgotten Beasts kill
    # anyone sent to work above ground.
    assert calibration_for("ourfort16-final", 3600) == {"noop": 0.467857, "ref": 0.587811}
    assert calibration_for("region3-lab", 3600) == {"noop": 0.507812, "ref": 0.635772}
    assert (calibration_for("region3-lab", 3600)
            != calibration_for("ourfort16-final", 3600))


def test_an_unmeasured_save_refuses_instead_of_scoring(monkeypatch):
    # A number produced against the wrong fort looks exactly like a real score. The only
    # safe answer for an unmeasured (save, horizon) pair is to refuse.
    from bonsai_lab_agent import game_evaluate

    monkeypatch.setenv("BONSAI_EPISODE_SAVE", "a-fort-nobody-measured")
    result = game_evaluate.evaluate_job_v4(
        object(), {"payload": {"submission_id": "s1", "horizon_ticks": 3600}})

    assert result["verdict"] == "uncalibrated_horizon"
    assert result["failure_kind"] == "config"
    assert result["summary"]["save"] == "a-fort-nobody-measured"
    assert "a-fort-nobody-measured" in result["summary"]["reason"]


def test_a_calibrated_save_at_an_unmeasured_horizon_also_refuses(monkeypatch):
    from bonsai_lab_agent import game_evaluate

    monkeypatch.setenv("BONSAI_EPISODE_SAVE", "region3-lab")
    result = game_evaluate.evaluate_job_v4(
        object(), {"payload": {"submission_id": "s1", "horizon_ticks": 12000}})
    assert result["verdict"] == "uncalibrated_horizon"
    assert result["summary"]["save"] == "region3-lab"


def test_the_scenario_id_in_the_payload_wins_over_the_environment(monkeypatch):
    from bonsai_lab_agent import game_evaluate

    monkeypatch.setenv("BONSAI_EPISODE_SAVE", "region3-lab")
    result = game_evaluate.evaluate_job_v4(
        object(),
        {"payload": {"submission_id": "s1", "horizon_ticks": 3600,
                     "scenario_id": "a-fort-nobody-measured"}})
    assert result["summary"]["save"] == "a-fort-nobody-measured"


def test_episode_save_falls_back_to_the_pinned_default(monkeypatch):
    from bonsai_lab_agent import game_evaluate
    from bonsai_lab_agent.scoring import DEFAULT_SAVE

    monkeypatch.delenv("BONSAI_EPISODE_SAVE", raising=False)
    assert game_evaluate.episode_save() == DEFAULT_SAVE
