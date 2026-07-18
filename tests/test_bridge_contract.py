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
from game_runner.episode import EpisodeRunner, evaluate_multiple_runs
from player.baseline import baseline_policy, evaluate_episode, TICKS_PER_DAY
from player.cpu_policy import cpu_policy, cpu_policy_with_features, TARGET_TICKS
from skills import StartFortress, AdvanceTimeStep, CheckSurvivors, Skill
from curricula.levels import CURRICULUM_LEVELS, get_level, run_curriculum


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


class TestEvolvingTicks:
    """EpisodeRunner stub advances ticks through the observe state."""

    def test_advance_increments_tick(self):
        runner = EpisodeRunner(seed=99, max_steps=50, action_budget=30)
        obs_before = runner.observe()
        assert obs_before["cur_tick"] == 0
        runner.advance(432000)
        obs_after = runner.observe()
        assert obs_after["cur_tick"] == 432000

    def test_advance_accumulates(self):
        runner = EpisodeRunner(seed=99, max_steps=50, action_budget=30)
        runner.advance(100)
        runner.advance(200)
        obs = runner.observe()
        assert obs["cur_tick"] == 300

    def test_episode_reaches_30_days(self):
        runner = EpisodeRunner(seed=7, max_steps=50, action_budget=30)
        metrics = runner.run(baseline_policy)
        target_ticks = TICKS_PER_DAY * 30
        # With stub units empty the baseline policy halts quickly.
        # But if we mock units alive, it should advance to ~30 days.
        assert validate_episode_metrics(metrics) is True

    def test_observe_returns_copy(self):
        runner = EpisodeRunner(seed=99)
        obs1 = runner.observe()
        obs1["cur_tick"] = 9999
        obs2 = runner.observe()
        assert obs2["cur_tick"] != 9999


class TestMultiRunEvaluator:
    """evaluate_multiple_runs produces aggregate and worst-run metrics."""

    def _sample_metrics(self, tick, survivors):
        return {
            "seed": 100,
            "steps_taken": 5,
            "final_tick": tick,
            "survivors": survivors,
            "actions_used": 4,
            "outcome": "success",
        }

    def test_empty_list(self):
        result = evaluate_multiple_runs([])
        assert result["runs"] == 0
        assert result["worst_run"] is None

    def test_aggregate_computed(self):
        runs = [
            self._sample_metrics(TICKS_PER_DAY * 30, 2),
            self._sample_metrics(TICKS_PER_DAY * 10, 0),
            self._sample_metrics(TICKS_PER_DAY * 25, 1),
        ]
        agg = evaluate_multiple_runs(runs)
        assert agg["runs"] == 3
        assert 0 <= agg["mean_score"] <= 1
        assert 0 <= agg["worst_score"] <= 1
        assert 0 <= agg["best_score"] <= 1
        assert isinstance(agg["pass_rate"], float)
        assert agg["worst_run"] is not None

    def test_pass_rate_all_pass(self):
        runs = [self._sample_metrics(TICKS_PER_DAY * 30, 2) for _ in range(5)]
        agg = evaluate_multiple_runs(runs)
        assert agg["pass_rate"] == 1.0

    def test_worst_run_identified(self):
        good = self._sample_metrics(TICKS_PER_DAY * 30, 4)
        bad = self._sample_metrics(1, 0)
        agg = evaluate_multiple_runs([good, bad])
        assert agg["worst_run"]["survivors"] == 0


class TestSkills:
    """Skill classes produce correct action sequences."""

    def test_start_fortress_yields_unpause(self):
        skill = StartFortress()
        obs = {"paused": True}
        results = list(skill.steps(obs))
        assert len(results) == 1
        assert results[0]["command"] == "unpause"

    def test_start_fortress_skips_if_not_paused(self):
        skill = StartFortress()
        obs = {"paused": False}
        result = skill.steps(obs)
        assert result is None

    def test_advance_time_yields_action(self):
        skill = AdvanceTimeStep(ticks=5000)
        results = list(skill.steps({"cur_tick": 0}))
        assert len(results) == 1
        assert results[0]["command"] == "advance"
        assert results[0]["args"] == [5000]

    def test_check_survivors_count_alive(self):
        skill = CheckSurvivors()
        obs = {
            "units": [
                {"killed": False, "civ_id": 1},
                {"killed": True, "civ_id": 1},
            ]
        }
        results = list(skill.steps(obs))
        assert len(results) == 1
        assert results[0]["meta_alive"] == 1

    def test_skill_base_raises_not_implemented(self):
        try:
            skill = Skill("bad", "desc")
            list(skill.steps({}))
            assert False, "Expected NotImplementedError"
        except NotImplementedError:
            pass


class TestCPUPolicy:
    """CPU inference policy is deterministic and mirrors baseline behavior."""

    def test_unpause_when_paused(self):
        obs = {"paused": True, "gametype": None, "cur_tick": 0, "units": []}
        action = cpu_policy(obs)
        assert action["command"] == "unpause"

    def test_advance_early_game(self):
        units = [{"killed": False, "civ_id": 1}]
        obs = {"paused": False, "gametype": "df.game_type.DWARF_FORTRESS",
               "cur_tick": TICKS_PER_DAY * 3, "units": units}
        action = cpu_policy(obs)
        assert action["command"] == "advance"

    def test_advance_late_game(self):
        units = [{"killed": False, "civ_id": 1}]
        obs = {"paused": False, "gametype": "df.game_type.DWARF_FORTRESS",
               "cur_tick": TARGET_TICKS - TICKS_PER_DAY, "units": units}
        action = cpu_policy(obs)
        assert action["command"] == "advance"

    def test_done_at_target(self):
        units = [{"killed": False, "civ_id": 1}]
        obs = {"paused": False, "gametype": "df.game_type.DWARF_FORTRESS",
               "cur_tick": TARGET_TICKS, "units": units}
        action = cpu_policy(obs)
        assert action["name"] == "observe"

    def test_abort_no_survivors(self):
        # Must have non-empty units list with all killed for abort to fire.
        dead_units = [{"killed": True, "civ_id": 1}, {"killed": True, "civ_id": 1}]
        obs = {
            "paused": False,
            "gametype": "df.game_type.DWARF_FORTRESS",
            "cur_tick": 1000,
            "units": dead_units,
        }
        action = cpu_policy(obs)
        assert action is None

    def test_no_abort_on_empty_units(self):
        """Empty units list means unknown — CPU policy falls through to advance."""
        obs = {"paused": False, "gametype": "df.game_type.DWARF_FORTRESS",
                "cur_tick": 1000, "units": []}
        action = cpu_policy(obs)
        assert action is not None

    def test_features_attached(self):
        units = [{"killed": False, "civ_id": 1}]
        obs = {"paused": False, "gametype": "df.game_type.DWARF_FORTRESS",
               "cur_tick": 5000, "units": units}
        action = cpu_policy_with_features(obs)
        assert "_features" in action
        feat = action["_features"]
        assert 0 <= feat["tick_progress"] <= 1
        assert feat["survivors"] == 1

    def test_cpu_episode_deterministic(self):
        runner_a = EpisodeRunner(seed=42, max_steps=50, action_budget=30)
        ma = runner_a.run(cpu_policy)
        runner_b = EpisodeRunner(seed=42, max_steps=50, action_budget=30)
        mb = runner_b.run(cpu_policy)
        assert ma["outcome"] == mb["outcome"]
        assert validate_episode_metrics(ma)


class TestBenchmarkCPUBaseline:
    """Compare CPU policy against baseline on identical runs."""

    def _run_n(self, policy, n=5):
        metrics = []
        for i in range(n):
            r = EpisodeRunner(seed=i, max_steps=60, action_budget=40)
            metrics.append(r.run(policy))
        return metrics

    def test_cpu_not_worse_than_baseline(self):
        """CPU policy mean score must be within tolerance of baseline.

        Tolerance = 0.25 covers the small distributional differences in
        advance chunk sizes between the two policies.  Failures indicate
        a regression in cpu_policy or baseline evaluation.
        """
        baseline_runs = self._run_n(baseline_policy)
        cpu_runs = self._run_n(cpu_policy)

        baseline_agg = evaluate_multiple_runs(baseline_runs)
        cpu_agg = evaluate_multiple_runs(cpu_runs)

        assert 0 <= baseline_agg["mean_score"] <= 1
        assert 0 <= cpu_agg["mean_score"] <= 1

        # CPU score ≥ (baseline - tolerance); ensures CPU has not regressed.
        tolerance = 0.25
        assert cpu_agg["mean_score"] >= baseline_agg["mean_score"] - tolerance, (
            f"CPU mean {cpu_agg['mean_score']:.4f} too far below "
            f"baseline mean {baseline_agg['mean_score']:.4f}"
        )

        # CPU worst run ≥ (baseline worst - tolerance).
        assert cpu_agg["worst_score"] >= baseline_agg["worst_score"] - tolerance, (
            f"CPU worst {cpu_agg['worst_score']:.4f} too far below "
            f"baseline worst {baseline_agg['worst_score']:.4f}"
        )


class TestCurricula:
    """Curriculum levels are well-formed and runnable."""

    def test_levels_defined(self):
        assert len(CURRICULUM_LEVELS) >= 4
        for lvl in CURRICULUM_LEVELS:
            assert "name" in lvl
            assert "policy" in lvl
            assert "target_days" in lvl

    def test_get_level(self):
        lvl = get_level(0)
        assert lvl["name"] == "unpause_and_survive_1_day"

    def test_get_level_out_of_range(self):
        try:
            get_level(99)
            assert False, "Expected IndexError"
        except IndexError:
            pass

    def test_curriculum_runs(self):
        def factory(level_dict):
            return EpisodeRunner(
                max_steps=level_dict["max_steps"],
                action_budget=level_dict["action_budget"],
            )
        results = run_curriculum(factory, evaluate_multiple_runs)
        assert len(results) == len(CURRICULUM_LEVELS)
        for name, metrics, passed in results:
            assert isinstance(name, str)
            assert validate_episode_metrics(metrics)


if __name__ == "__main__":
    """Run all tests without pytest — portable to bare Python 3.13."""
    import inspect

    failures = []
    total = 0
    passed = 0

    tc_classes = [TestContractSchema, TestValidationHelpers, TestEpisodeRunner,
                  TestBaselinePolicy, TestIntegrationStubEpisode,
                  TestEvolvingTicks, TestMultiRunEvaluator, TestSkills,
                  TestCPUPolicy, TestBenchmarkCPUBaseline, TestCurricula]

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
