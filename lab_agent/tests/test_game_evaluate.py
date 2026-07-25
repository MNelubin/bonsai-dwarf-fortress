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
