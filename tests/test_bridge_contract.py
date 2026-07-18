"""Deterministic contract tests for the DFHack bridge and episode runner.

These tests exercise the Python-side stubs (no live DF required) and
validate that all data shapes match bridge/contracts.json.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest import mock

from bridge.contracts import CONTRACT_SCHEMA, validate_observe, validate_act_result, validate_episode_metrics
from game_runner.episode import EpisodeRunner
from player.baseline import baseline_policy, evaluate_episode, TICKS_PER_DAY


def _sample_obs(tick=0, paused=True, n_units=4):
    """Return a synthetic observation matching the observe contract."""
    units = [
        {"id": 100 + i, "race": i % 3, "civ_id": 1, "killed": False, "pos": [0, 0, 0]}
        for i in range(n_units)
    ]
    return {
        "version": "1.0",
        "gametype": "df.game_type.DWARF_FORTRESS" if tick > 0 else None,
        "cur_year": 1,
        "cur_season": 1,
        "cur_tick": tick,
        "paused": paused,
        "units": units,
        "buildings": [{"idx": j} for j in range(3)],
        "tick": len(units),
    }


class TestContractSchema:
    """Validate the JSON contract itself is well-formed."""

    def test_observe_required_keys(self):
        observe = CONTRACT_SCHEMA["bridge_api"]["observe"]
        assert isinstance(observe["output"]["required"], list)
        for key in ["version", "cur_tick", "paused"]:
            assert key in observe["output"]["required"]

    def test_act_has_input_and_output(self):
        act = CONTRACT_SCHEMA["bridge_api"]["act"]
        assert "input" in act
        assert "output" in act
        assert "command" in act["input"]
        assert "ok" in act["output"]

    def test_episode_contract_defined(self):
        ec = CONTRACT_SCHEMA["episode_contract"]
        assert "input" in ec
        assert "output_metrics" in ec
        for f in ["seed", "steps_taken", "outcome"]:
            assert f in ec["output_metrics"]


class TestValidationHelpers:
    """The validate_* helpers accept conformant data."""

    def test_validate_observe_passes(self):
        obs = _sample_obs()
        assert validate_observe(obs) is True

    def test_validate_observe_fails_no_paused(self):
        obs = _sample_obs()
        del obs["paused"]
        assert validate_observe(obs) is False

    def test_validate_act_result_passes(self):
        result = {"ok": True, "message": "done"}
        assert validate_act_result(result) is True

    def test_validate_act_result_fails_no_ok(self):
        result = {"message": "x"}
        assert validate_act_result(result) is False

    def test_validate_episode_metrics_passes(self):
        m = {
            "seed": 42,
            "steps_taken": 10,
            "final_tick": 5000,
            "survivors": 3,
            "actions_used": 8,
            "outcome": "success",
        }
        assert validate_episode_metrics(m) is True

    def test_validate_episode_metrics_fails(self):
        assert validate_episode_metrics({"seed": 1}) is False


class TestEpisodeRunner:
    """Stub episode runner produces contract-compliant output."""

    def test_run_produces_valid_metrics(self):
        runner = EpisodeRunner(seed=7, max_steps=20, action_budget=10)
        metrics = runner.run(baseline_policy)
        assert validate_episode_metrics(metrics) is True

    def test_reset_clears_trace(self):
        runner = EpisodeRunner()
        runner.reset()
        assert runner.metrics["seed"] == runner.seed
        assert runner.trace == []

    def test_steps_bounded_by_max(self):
        always_act = lambda obs: {"command": "advance", "args": [100]}
        runner = EpisodeRunner(max_steps=5, action_budget=20)
        m = runner.run(always_act)
        assert m["steps_taken"] <= 5

    def test_actions_bounded_by_budget(self):
        always_act = lambda obs: {"command": "advance", "args": [100]}
        runner = EpisodeRunner(max_steps=200, action_budget=3)
        m = runner.run(always_act)
        assert m["actions_used"] <= 3

    def test_survivors_count(self):
        runner = EpisodeRunner(seed=1)
        obs = runner.observe()
        assert isinstance(obs["units"], list)


class TestBaselinePolicy:
    """Rules-based policy is deterministic and halts correctly."""

    def test_returns_advance_early_game(self):
        obs = _sample_obs(tick=TICKS_PER_DAY * 5, paused=False, n_units=4)
        action = baseline_policy(obs)
        assert action is not None
        assert action["command"] == "advance"

    def test_returns_observe_at_30_days(self):
        obs = _sample_obs(tick=TICKS_PER_DAY * 31, paused=False, n_units=4)
        action = baseline_policy(obs)
        # The policy should signal done when >= 30 days have elapsed.
        assert action["name"] == "observe"

    def test_returns_none_when_no_citizens(self):
        obs = _sample_obs(tick=TICKS_PER_DAY * 5, paused=False, n_units=0)
        action = baseline_policy(obs)
        assert action is None

    def test_score_at_30_days(self):
        metrics = {
            "seed": 1,
            "steps_taken": 6,
            "final_tick": TICKS_PER_DAY * 30,
            "survivors": 2,
            "actions_used": 6,
            "outcome": "success",
        }
        score, verdict = evaluate_episode(metrics)
        assert isinstance(score, float)
        assert 0 <= score <= 1

    def test_score_below_baseline(self):
        metrics = {
            "seed": 2, "steps_taken": 1,
            "final_tick": 100, "survivors": 0,
            "actions_used": 1, "outcome": "failure",
        }
        score, verdict = evaluate_episode(metrics)
        assert score < 0.4


class TestIntegrationStubEpisode:
    """Full episode loop produces deterministic, contract-valid output."""

    def test_seeded_run_is_deterministic(self):
        runner_a = EpisodeRunner(seed=42, max_steps=15, action_budget=10)
        metrics_a = runner_a.run(baseline_policy)

        runner_b = EpisodeRunner(seed=42, max_steps=15, action_budget=10)
        metrics_b = runner_b.run(baseline_policy)

        assert metrics_a["steps_taken"] == metrics_b["steps_taken"]
        assert metrics_a["outcome"] == metrics_b["outcome"]
        assert validate_episode_metrics(metrics_a) is True


if __name__ == "__main__":
    """Run all tests without pytest — portable to bare Python 3.13."""
    import inspect

    failures = []
    total = 0
    passed = 0

    tc_classes = [TestContractSchema, TestValidationHelpers, TestEpisodeRunner,
                  TestBaselinePolicy, TestIntegrationStubEpisode]

    for cls in tc_classes:
        inst = cls()
        for name in dir(inst):
            if not name.startswith("test_"):
                continue
            total += 1
            method = getattr(inst, name)
            try:
                method()
                passed += 1
                print(f"  PASS {cls.__name__}.{name}")
            except Exception as exc:
                failures.append((f"{cls.__name__}.{name}", str(exc)))
                print(f"  FAIL {cls.__name__}.{name}: {exc}")

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {len(failures)} failed")
    for name, msg in failures:
        print(f"  FAILED {name}: {msg}")
    sys.exit(1 if failures else 0)
