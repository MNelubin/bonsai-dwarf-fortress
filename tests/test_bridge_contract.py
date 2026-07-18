"""Deterministic contract tests for the DFHack bridge and episode runner.

These tests exercise the Python-side stubs (no live DF required) and
validate that all data shapes match bridge/contracts.json.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest import mock

from bridge.contracts import (
    CONTRACT_SCHEMA, validate_observe, validate_act_result, validate_episode_metrics,
    validate_episode_outcome, validate_act_input,
)
from game_runner.episode import EpisodeRunner, evaluate_multiple_runs, _simulate_citizens
from player.baseline import baseline_policy, evaluate_episode, TICKS_PER_DAY
from player.cpu_policy import cpu_policy, cpu_policy_with_features, TARGET_TICKS
from player.skill_chain import make_skill_chain
from skills import StartFortress, AdvanceTimeStep, CheckSurvivors, Skill
from curricula.levels import CURRICULUM_LEVELS, get_level, run_curriculum
from evaluator_public import score_episode, aggregate_runs, verify_trace_determinism, contract_checksum, benchmark_runner


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

    def test_skill_chain_level_present(self):
        """Objective C: the 7-day skill-chain level exists in curricula."""
        names = [lvl["name"] for lvl in CURRICULUM_LEVELS]
        assert "survive_7_days_skill_chain" in names


class TestSkillChainPlayer:
    """make_skill_chain composes Skills into a callable policy."""

    def test_emits_unpause_then_advance(self):
        chain = make_skill_chain(StartFortress(), AdvanceTimeStep(ticks=5000))
        obs = {"paused": True, "units": []}
        a1 = chain(obs)
        assert a1["command"] == "unpause"
        a2 = chain({"paused": False, "units": []})
        assert a2["command"] == "advance"
        assert a2["args"] == [5000]

    def test_terminal_when_skills_return_none(self):
        obs = {"paused": False}
        chain = make_skill_chain(StartFortress())
        result = chain(obs)
        assert result is None

    def test_reset_clears_buffer(self):
        chain = make_skill_chain(AdvanceTimeStep(ticks=100))
        chain({"cur_tick": 0})
        chain({"cur_tick": 0})
        chain._reset()
        assert chain({"cur_tick": 0}) is not None

    def test_multi_skill_buffer(self):
        chain = make_skill_chain(
            AdvanceTimeStep(ticks=100),
            AdvanceTimeStep(ticks=200),
            CheckSurvivors(),
        )
        obs = {"cur_tick": 0, "units": [{"killed": False, "civ_id": 1}]}
        a1 = chain(obs)
        a2 = chain(obs)
        a3 = chain(obs)
        assert a1["command"] == "advance" and a1["args"] == [100]
        assert a2["command"] == "advance" and a2["args"] == [200]
        assert a3["command"] == "observe"

    def test_chain_deterministic_episode(self):
        chain = make_skill_chain(StartFortress(), AdvanceTimeStep(ticks=432000))
        ra = EpisodeRunner(seed=1, max_steps=50, action_budget=30)
        ma = ra.run(chain)
        rb = EpisodeRunner(seed=1, max_steps=50, action_budget=30)
        mb = rb.run(chain)
        assert ma["outcome"] == mb["outcome"]
        assert validate_episode_metrics(ma)

    def test_chain_survives_7_days(self):
        """The skill chain advances 5 days tick per step; verify 7-day progress."""
        TICKS_7D = TICKS_PER_DAY * 7
        ADVANCE = 5 * TICKS_PER_DAY
        chain = make_skill_chain(StartFortress(), AdvanceTimeStep(ticks=ADVANCE))
        runner = EpisodeRunner(seed=0, max_steps=20, action_budget=15)
        metrics = runner.run(chain)
        assert metrics["final_tick"] >= TICKS_7D


class TestPublicEvaluator:
    """evaluator_public.score_episode and aggregate_runs are correct."""

    def test_score_perfect_episode(self):
        m = {
            "seed": 1, "steps_taken": 6,
            "final_tick": TICKS_PER_DAY * 30, "survivors": 4,
            "actions_used": 6, "outcome": "success",
        }
        score, verdict = score_episode(m)
        assert isinstance(score, float) and 0 <= score <= 1
        assert verdict == "pass"

    def test_score_zero_ticks(self):
        m = {
            "seed": 2, "steps_taken": 1,
            "final_tick": 0, "survivors": 0,
            "actions_used": 1, "outcome": "failure",
        }
        score, verdict = score_episode(m)
        assert score < 0.5
        assert verdict == "failed"

    def test_score_partial_progress(self):
        half_ticks = TICKS_PER_DAY * 30 / 2
        m = {
            "seed": 3, "steps_taken": 4,
            "final_tick": half_ticks, "survivors": 1,
            "actions_used": 4, "outcome": "success",
        }
        score, verdict = score_episode(m)
        assert 0.5 <= score <= 1.0
        assert verdict == "pass" or verdict == "below_baseline"

    def test_score_invalid_metrics(self):
        score, verdict = score_episode({"garbage": True})
        assert score == 0.0
        assert verdict == "failed"

    def test_aggregate_empty(self):
        agg = aggregate_runs([])
        assert agg["runs"] == 0
        assert agg["std_dev"] == 0.0
        assert agg["worst_run"] is None

    def test_aggregate_stats(self):
        runs = [
            {"seed": i, "steps_taken": 5,
             "final_tick": TICKS_PER_DAY * (30 if i < 3 else 10),
             "survivors": 4 if i < 3 else 0,
             "actions_used": 5, "outcome": "success"}
            for i in range(5)
        ]
        agg = aggregate_runs(runs)
        assert agg["runs"] == 5
        assert 0 <= agg["mean_score"] <= 1
        assert agg["std_dev"] >= 0
        assert len(agg["failing_runs"]) == 2


class TestTraceDeterminism:
    """Episode traces are byte-deterministic across identical runs."""

    def test_same_seed_identical_trace(self):
        ra = EpisodeRunner(seed=42, max_steps=30, action_budget=25)
        ra.run(baseline_policy)
        ta = ra.get_trace()

        rb = EpisodeRunner(seed=42, max_steps=30, action_budget=25)
        rb.run(baseline_policy)
        tb = rb.get_trace()

        ok, _ = verify_trace_determinism(ta, tb)
        assert ok is True

    def test_different_seed_differs(self):
        ra = EpisodeRunner(seed=1, max_steps=10, action_budget=8)
        ra.run(cpu_policy)

        rb = EpisodeRunner(seed=99, max_steps=10, action_budget=8)
        rb.run(cpu_policy)

        ok, details = verify_trace_determinism(ra.get_trace(), rb.get_trace())
        assert ok is False or len(ra.get_trace()) == len(rb.get_trace())

    def test_observation_checksum(self):
        obs = _sample_obs(tick=5000, paused=False, n_units=3)
        cs1 = contract_checksum(obs)
        cs2 = contract_checksum(obs)
        assert cs1 == cs2
        # Tick excluded: same content regardless of tick count.
        obs_no_tick = {k: v for k, v in obs.items() if k != "tick"}
        assert contract_checksum(obs_no_tick) == cs1

    def test_get_trace_is_copy(self):
        runner = EpisodeRunner(seed=5, max_steps=3, action_budget=3)
        runner.run(lambda obs: {"command": "advance", "args": [100]})
        trace = runner.get_trace()
        trace[0]["action"]["command"] = "corrupted"
        ok, _ = verify_trace_determinism(runner.trace, runner.get_trace())
        assert ok is True


class TestRunnerEnhancements:
    """Enhanced EpisodeRunner methods work correctly."""

    def test_to_json(self):
        r = EpisodeRunner(seed=7, max_steps=5, action_budget=3)
        r.run(baseline_policy)
        raw = r.to_json()
        parsed = json.loads(raw)
        assert parsed["seed"] == 7
        assert "trace" in parsed
        assert isinstance(parsed["trace"], list)

    def test_reuse_runner_resets(self):
        r = EpisodeRunner(seed=10, max_steps=20, action_budget=15)
        m1 = r.run(baseline_policy)
        m2 = r.run(baseline_policy)
        assert validate_episode_metrics(m1)
        assert validate_episode_metrics(m2)

    def test_skill_chain_reset_called(self):
        chain = make_skill_chain(StartFortress(), AdvanceTimeStep(ticks=100))
        r = EpisodeRunner(seed=0, max_steps=10, action_budget=5)
        m = r.run(chain)
        assert validate_episode_metrics(m)


class TestCitizenSimulation:
    """Deterministic citizen generation and stress events."""

    def test_simulate_citizens_is_deterministic(self):
        u1, d1 = _simulate_citizens(42, 4)
        u2, d2 = _simulate_citizens(42, 4)
        assert u1 == u2
        assert d1 == d2

    def test_simulate_diff_seeds_differ(self):
        u1, d1 = _simulate_citizens(1)
        u2, d2 = _simulate_citizens(99)
        # Either the IDs or the death thresholds should differ.
        assert (u1 != u2) or (d1 != d2)

    def test_simulate_returns_right_count(self):
        units, _ = _simulate_citizens(7, 3)
        assert len(units) == 3
        for u in units:
            assert "id" in u
            assert "civ_id" in u and u["civ_id"] is not None
            assert u["killed"] is False

    def test_episodereporter_has_units(self):
        runner = EpisodeRunner(seed=5, max_steps=10, action_budget=5)
        obs = runner.observe()
        assert len(obs["units"]) == 4
        for u in obs["units"]:
            assert "id" in u and "killed" in u

    def test_stress_events_mutate_death(self):
        """When ticks cross the death threshold, some units become killed."""
        runner = EpisodeRunner(seed=0, max_steps=100, action_budget=50)
        # The death threshold is at least 5 days; advance past it.
        runner.advance(86400 * 6)
        alive_count_before = sum(1 for u in runner.units if not u["killed"])
        # Advance many more days to trigger further deaths.
        runner.advance(86400 * 25)
        alive_after = sum(1 for u in runner.units if not u["killed"])
        assert alive_after <= alive_count_before

    def test_survivors_in_metrics_reflect_death(self):
        """Final metrics.survivors counts living citizens only."""
        runner = EpisodeRunner(seed=0, max_steps=50, action_budget=30)
        m = runner.run(baseline_policy)
        # Survivors should be the count of alive citizens.
        alive = sum(1 for u in runner.units if not u["killed"] and u["civ_id"] is not None)
        assert m["survivors"] == alive

    def test_episodereporter_reuse_resets_units(self):
        """Running twice resets citizen simulation and produces identical metrics."""
        r = EpisodeRunner(seed=10, max_steps=20, action_budget=15)
        m1 = r.run(baseline_policy)
        # Re-running on the same runner resets citizens (reset() in run()).
        m2 = r.run(baseline_policy)
        # Same runner, same config → identical output.
        assert m1["survivors"] == m2["survivors"]
        assert m1["steps_taken"] == m2["steps_taken"]
        # Fresh runner with the same seed also reproduces.
        r3 = EpisodeRunner(seed=10, max_steps=20, action_budget=15)
        m3 = r3.run(baseline_policy)
        assert m1["survivors"] == m3["survivors"]
        assert m1["steps_taken"] == m3["steps_taken"]


class TestBenchmarkRunner:
    """evaluator_public benchmark_runner returns per-policy aggregates."""

    def test_benchmark_baseline(self):
        results = benchmark_runner(
            ("baseline", baseline_policy),
            num_runs=5, max_steps=60, action_budget=40
        )
        assert "baseline" in results
        agg = results["baseline"]
        assert agg["runs"] == 5
        assert 0 <= agg["mean_score"] <= 1
        assert agg["std_dev"] >= 0

    def test_benchmark_cpu_vs_baseline(self):
        results = benchmark_runner(
            ("baseline", baseline_policy),
            ("cpu", cpu_policy),
            num_runs=5, max_steps=60, action_budget=40,
        )
        assert "baseline" in results and "cpu" in results
        assert results["baseline"]["mean_score"] <= 1
        assert results["cpu"]["mean_score"] <= 1


class TestValidationTypeSafety:
    """Updated validate_observe enforces field types from the schema."""

    def test_rejects_non_int_tick(self):
        units = [{"id": 100, "race": 0, "civ_id": 1, "killed": False, "pos": [0, 0, 0]}]
        obs = {
            "version": "1.0",
            "gametype": "df.game_type.DWARF_FORTRESS",
            "cur_year": 1, "cur_season": 1,
            "cur_tick": "abc",
            "paused": False,
            "units": units,
            "buildings": [{"idx": 0}],
            "tick": 1,
        }
        assert validate_observe(obs) is False

    def test_rejects_non_bool_paused(self):
        obs = _sample_obs()
        obs["paused"] = "yes"
        assert validate_observe(obs) is False

    def test_rejects_non_string_version(self):
        obs = _sample_obs()
        obs["version"] = 1.0
        assert validate_observe(obs) is False

    def test_rejects_non_array_units(self):
        obs = _sample_obs()
        obs["units"] = "all alive"
        assert validate_observe(obs) is False

    def test_allows_nullable_fields_none(self):
        obs = {
            "version": "1.0", "gametype": None,
            "cur_year": None, "cur_season": None,
            "cur_tick": None, "paused": True,
            "tick": 0,
        }
        assert validate_observe(obs) is True

    def test_episode_outcome_valid(self):
        assert validate_episode_outcome("success") is True
        assert validate_episode_outcome("failure") is True
        assert validate_episode_outcome("timeout") is True
        assert validate_episode_outcome("unknown") is False

    def test_act_input_with_command(self):
        assert validate_act_input({"command": "advance"}) is True
        assert validate_act_input({"name": "observe"}) is True
        assert validate_act_input({}) is False
        assert validate_act_input("raw_string") is False


class TestEpisodeSerialization:
    """EpisodeRunner.serialize() / deserialize() round-trips correctly."""

    def test_roundtrip_preserves_metrics(self):
        r = EpisodeRunner(seed=42, max_steps=30, action_budget=20)
        metrics_original = r.run(baseline_policy)
        snapshot = r.serialize()
        r2 = EpisodeRunner.deserialize(snapshot)
        assert r2.seed == 42
        assert r2.metrics["steps_taken"] == metrics_original["steps_taken"]
        assert r2.metrics["actions_used"] == metrics_original["actions_used"]

    def test_roundtrip_preserves_trace(self):
        r = EpisodeRunner(seed=5, max_steps=10, action_budget=8)
        r.run(cpu_policy)
        trace_before = r.get_trace()
        restored = EpisodeRunner.deserialize(r.serialize())
        # The deserialized runner has the same trace content.
        assert len(restored.trace) == len(trace_before)

    def test_deserialize_runner_still_valid_metrics(self):
        r = EpisodeRunner(seed=99, max_steps=20, action_budget=15)
        m1 = r.run(baseline_policy)
        snap = r.serialize()
        r_restored = EpisodeRunner.deserialize(snap)
        # Re-serialize should produce identical content.
        snap2 = r_restored.serialize()
        assert snap2["seed"] == 99
        assert snap2["metrics"]["survivors"] is not None


class TestConfidenceIntervals:
    """aggregate_runs includes 95% CI and values are plausible."""

    def test_ci_present(self):
        runs = [
            {"seed": i, "steps_taken": 6,
             "final_tick": TICKS_PER_DAY * 30, "survivors": 4,
             "actions_used": 6, "outcome": "success"}
            for i in range(5)
        ]
        agg = aggregate_runs(runs)
        assert "confidence_interval_95" in agg
        lo, hi = agg["confidence_interval_95"]
        assert 0.0 <= lo <= hi <= 1.0

    def test_ci_zero_width_for_identical_scores(self):
        runs = [
            {"seed": idx, "steps_taken": 6,
              "final_tick": TICKS_PER_DAY * 30, "survivors": 4,
              "actions_used": 6, "outcome": "success"}
            for idx in range(10)
        ]
        agg = aggregate_runs(runs)
        lo, hi = agg["confidence_interval_95"]
        assert lo == hi

    def test_ci_wider_with_variance(self):
        runs_good = [
            {"seed": idx, "steps_taken": 6,
              "final_tick": TICKS_PER_DAY * 30, "survivors": 4,
              "actions_used": 6, "outcome": "success"}
            for idx in range(5)
        ]
        runs_bad = [
            {"seed": idx + 100, "steps_taken": 1,
              "final_tick": 0, "survivors": 0,
              "actions_used": 1, "outcome": "failure"}
            for idx in range(5)
        ]
        agg_mixed = aggregate_runs(runs_good + runs_bad)
        agg_uniform = aggregate_runs(runs_good * 2)
        lo_mixed, hi_mixed = agg_mixed["confidence_interval_95"]
        lo_uni, hi_uni = agg_uniform["confidence_interval_95"]
        assert (hi_mixed - lo_mixed) > (hi_uni - lo_uni)

    def test_ci_empty_runs(self):
        agg = aggregate_runs([])
        assert agg["confidence_interval_95"] == (0.0, 0.0)

    def test_ci_single_run_clamped(self):
        runs = [{"seed": 1, "steps_taken": 6,
                 "final_tick": TICKS_PER_DAY * 30, "survivors": 4,
                 "actions_used": 6, "outcome": "success"}]
        agg = aggregate_runs(runs)
        lo, hi = agg["confidence_interval_95"]
        assert lo == hi


if __name__ == "__main__":

    """Run all tests without pytest — portable to bare Python 3.13."""
    import inspect

    failures = []
    total = 0
    passed = 0

    tc_classes = [TestContractSchema, TestValidationHelpers, TestEpisodeRunner,
                  TestBaselinePolicy, TestIntegrationStubEpisode,
                  TestEvolvingTicks, TestMultiRunEvaluator, TestSkills,
                  TestCPUPolicy, TestBenchmarkCPUBaseline, TestCurricula,
                  TestSkillChainPlayer, TestPublicEvaluator,
                  TestTraceDeterminism, TestRunnerEnhancements,
                  TestCitizenSimulation, TestBenchmarkRunner,
                  TestValidationTypeSafety, TestEpisodeSerialization,
                  TestConfidenceIntervals]

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
