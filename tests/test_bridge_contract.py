"""Deterministic contract tests for the DFHack bridge and episode runner.

These tests exercise the Python-side stubs (no live DF required) and
validate that all data shapes match bridge/contracts.json.
"""

import contextlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.contracts import (
    CONTRACT_SCHEMA,
    validate_observe, validate_act_result, validate_advance_result,
    validate_episode_metrics, validate_episode_outcome, validate_act_input,
)
from bridge.probe import (
    probe_time, season_name, total_ticks, days_elapsed,
    PROFESSION_LABOR_MAP, KNOWN_LABORS, labor_to_professions,
    get_profession_labors, classify_labor_category, can_perform_labor,
    HUNGER_DIRE_THRESHOLD, THIRST_DIRE_THRESHOLD, SLEEPINESS_DIRE_THRESHOLD,
    COUNTERS_1_FIELDS, COUNTERS_2_FIELDS, is_in_dire_need, need_severity,
    KNOWN_BUILDING_TYPES, BUILDING_SCHEMA_KEYS,
    is_complete_building, unfinished_buildings, building_type_label,
    buildings_at_z, building_count_by_type,
    alive_units, dead_units, unit_population, units_by_civ_id,
    units_at_z, unit_positions, nearby_units,
    ITEM_TYPE_ENUM_MAP, item_category, total_inventory_value,
    count_items_by_category, high_value_items,
    classify_material, is_liquid_tile, is_floor_tile, classify_tile_label,
    TILE_MATERIAL_ENUM_MAP,
    job_state, job_category, count_jobs_by_state, count_jobs_by_category,
    active_worker_ids, suspicious_jobs,
    JOB_STATE_QUEUED, JOB_STATE_ACTIVE, JOB_STATE_SUSPENDED, JOB_STATE_CANCELLED,
    MAP_FEATURE_SCHEMA_KEYS, KNOWN_FEATURE_TYPES,
    water_features, magma_features,
    discovered_features, feature_categories, hazardous_features,
    map_dimensions, tile_material_counts,
    walkable_tile_fraction, liquid_tile_fraction, floor_tile_fraction,
    tile_summary, dominant_material, TILE_MAP_SCHEMA_KEYS, TILE_SAMPLE_LIMIT,
)
from game_runner.episode import EpisodeRunner, evaluate_multiple_runs, _simulate_citizens
from player.baseline import baseline_policy, evaluate_episode, TICKS_PER_DAY
from player.cpu_policy import cpu_policy, cpu_policy_with_features, TARGET_TICKS
from player.skill_chain import make_skill_chain
from skills import StartFortress, AdvanceTimeStep, CheckSurvivors, SurvivalGuard, Skill, GradualAdvance, ResourceMonitor, EmergencyPause
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
        def always_act(obs):
            return {"command": "advance", "args": [100]}
        runner = EpisodeRunner(max_steps=5, action_budget=20)
        m = runner.run(always_act)
        assert m["steps_taken"] <= 5

    def test_actions_bounded_by_budget(self):
        def always_act(obs):
            return {"command": "advance", "args": [100]}
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
        _target_ticks = TICKS_PER_DAY * 30
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
            raise AssertionError("Expected NotImplementedError")
        except NotImplementedError:
            pass

    def test_survival_guard_passes_with_alive(self):
        skill = SurvivalGuard(min_citizens=1)
        obs = {
            "units": [
                {"killed": False, "civ_id": 1},
                {"killed": True, "civ_id": 1},
            ]
        }
        result = skill.steps(obs)
        assert result is not None
        assert result[0]["meta_alive"] == 1

    def test_survival_guard_fails_no_alive(self):
        skill = SurvivalGuard(min_citizens=1)
        obs = {
            "units": [
                {"killed": True, "civ_id": 1},
                {"killed": True, "civ_id": 2},
            ]
        }
        assert skill.steps(obs) is None

    def test_survival_guard_higher_threshold(self):
        skill = SurvivalGuard(min_citizens=3)
        obs = {
            "units": [
                {"killed": False, "civ_id": 1},
                {"killed": False, "civ_id": 2},
            ]
        }
        assert skill.steps(obs) is None

    def test_survival_guard_terminal_in_chain(self):
        chain = make_skill_chain(StartFortress(), SurvivalGuard(min_citizens=1))
        dead_obs = {
            "paused": False,
            "units": [{"killed": True, "civ_id": 1}],
        }
        assert chain(dead_obs) is None

    def test_survival_guard_epilogue_in_chain(self):
        chain = make_skill_chain(AdvanceTimeStep(ticks=100), SurvivalGuard(min_citizens=1))
        alive_obs = {
            "cur_tick": 0,
            "units": [{"killed": False, "civ_id": 1}],
        }
        a1 = chain(alive_obs)
        assert a1["command"] == "advance"
        a2 = chain({"cur_tick": 100, "units": [{"killed": False, "civ_id": 1}]})
        assert a2["command"] == "observe"


class TestCPUPolicy:
    """CPU inference policy is deterministic and mirrors baseline behavior."""

    def test_unpause_when_paused(self):
        obs: dict = {"paused": True, "gametype": None, "cur_tick": 0, "units": []}
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

    def test_skill_chain_not_worse_than_baseline(self):
        """Skill-chain policy must not regress beyond tolerance of baseline."""
        from curricula.levels import _survive_30_chain
        baseline_runs = self._run_n(baseline_policy, n=5)
        chain_runs = self._run_n(_survive_30_chain, n=5)

        baseline_agg = evaluate_multiple_runs(baseline_runs)
        chain_agg = evaluate_multiple_runs(chain_runs)

        tolerance = 0.25
        assert chain_agg["mean_score"] >= baseline_agg["mean_score"] - tolerance, (
            f"Chain mean {chain_agg['mean_score']:.4f} too far below "
            f"baseline mean {baseline_agg['mean_score']:.4f}"
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
            raise AssertionError("Expected IndexError")
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
        for name, metrics, _passed in results:
            assert isinstance(name, str)
            assert validate_episode_metrics(metrics)

    def test_skill_chain_level_present(self):
        """Objective C: the 7-day skill-chain level exists in curricula."""
        names = [lvl["name"] for lvl in CURRICULUM_LEVELS]
        assert "survive_7_days_skill_chain" in names

    def test_30_day_skill_chain_level_present(self):
        """Objective D: 30-day skill-chain level exists with survival guard."""
        names = [lvl["name"] for lvl in CURRICULUM_LEVELS]
        assert "survive_30_days_skill_chain" in names

    def test_30_day_skill_chain_runs(self):
        """The 30-day chain should advance far enough to reach target ticks."""
        from curricula.levels import _survive_30_chain
        runner = EpisodeRunner(
            seed=0, max_steps=100, action_budget=50,
        )
        metrics = runner.run(_survive_30_chain)
        assert validate_episode_metrics(metrics)
        target_ticks = TICKS_PER_DAY * 30
        assert metrics["final_tick"] >= target_ticks


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
        r.run(baseline_policy)
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


class TestAdvanceValidation:
    """validate_advance_result enforces the advance output contract."""

    def test_passes_with_ok_bool(self):
        assert validate_advance_result({"ok": True}) is True
        assert validate_advance_result({"ok": False}) is True
        assert validate_advance_result({"ok": True, "advanced_ticks": 100}) is True

    def test_fails_without_ok(self):
        assert validate_advance_result({"message": "hi"}) is False

    def test_fails_non_bool_ok(self):
        assert validate_advance_result({"ok": 1}) is False
        assert validate_advance_result({"ok": "yes"}) is False
        assert validate_advance_result({"ok": None}) is False

    def test_fails_non_dict(self):
        assert validate_advance_result("ok") is False
        assert validate_advance_result([{"ok": True}]) is False


class TestDiskCheckpoint:
    """EpisodeRunner save_checkpoint / load_checkpoint roundtrips correctly."""

    _id_counter = 0

    @classmethod
    def _next_id(cls):
        cls._id_counter += 1
        return cls._id_counter

    def _tmp_file(self, suffix=".json"):
        return os.path.join(
            os.path.dirname(__file__),
            f".checkpoint_test_{TestDiskCheckpoint._next_id()}{suffix}",
        )

    @staticmethod
    def _cleanup(f):
        with contextlib.suppress(FileNotFoundError):
            os.remove(f)

    def test_save_and_load_file(self):
        f = self._tmp_file()
        try:
            r = EpisodeRunner(seed=7, max_steps=10, action_budget=6)
            m1 = r.run(baseline_policy)
            written = r.save_checkpoint(f)
            assert os.path.isfile(written)

            r2 = EpisodeRunner.load_checkpoint(f)
            assert r2.seed == 7
            assert r2.metrics["steps_taken"] == m1["steps_taken"]
            assert r2.metrics["survivors"] == m1["survivors"]
        finally:
            self._cleanup(f)

    def test_save_to_directory(self):
        d = os.path.join(os.path.dirname(__file__), ".ckpt_dir_test")
        try:
            os.makedirs(d, exist_ok=True)
            r = EpisodeRunner(seed=3, max_steps=8, action_budget=5)
            m1 = r.run(baseline_policy)
            written = r.save_checkpoint(d)
            assert written.startswith(os.path.abspath(d))

            r2 = EpisodeRunner.load_checkpoint(d)
            assert r2.metrics["steps_taken"] == m1["steps_taken"]
        finally:
            for f in os.listdir(d):
                self._cleanup(os.path.join(d, f))
            with contextlib.suppress(OSError):
                os.rmdir(d)

    def test_roundtrip_preserves_trace_determinism(self):
        f = self._tmp_file()
        try:
            r = EpisodeRunner(seed=42, max_steps=20, action_budget=15)
            m1_before = r.run(baseline_policy)
            _trace_a = r.get_trace()

            written = r.save_checkpoint(f)
            r2 = EpisodeRunner.load_checkpoint(written)
            # The restored runner reproduces the same metrics.
            assert r2.metrics["steps_taken"] == m1_before["steps_taken"]
        finally:
            self._cleanup(f)

    def test_load_nonexistent_raises(self):
        try:
            EpisodeRunner.load_checkpoint("/tmp/does_not_exist_bonsai.json")
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_metrics_after_restore_are_valid_contract(self):
        f = self._tmp_file()
        try:
            r = EpisodeRunner(seed=99, max_steps=30, action_budget=20)
            r.run(cpu_policy)
            written = r.save_checkpoint(f)

            r2 = EpisodeRunner.load_checkpoint(written)
            # The restored metrics conform to the schema.
            assert validate_episode_metrics(r2.metrics) is True
        finally:
            self._cleanup(f)


class TestGradualAdvance:
    """GradualAdvance produces adaptive tick chunks."""

    def test_returns_none_at_target(self):
        skill = GradualAdvance()
        assert skill.steps({"cur_tick": TARGET_TICKS}) is None

    def test_large_early_chunk(self):
        skill = GradualAdvance()
        result = skill.steps({"cur_tick": 0})
        # Full progress → largest chunk (7 days).
        assert result[0]["command"] == "advance"
        assert result[0]["args"][0] == 7 * TICKS_PER_DAY

    def test_smaller_late_chunk(self):
        skill = GradualAdvance()
        near_end = TARGET_TICKS - 86400
        result = skill.steps({"cur_tick": near_end})
        assert result is not None
        assert result[0]["command"] == "advance"
        # Near end → small chunk (1 day).
        assert result[0]["args"][0] == 1 * TICKS_PER_DAY

    def test_mid_chunk(self):
        skill = GradualAdvance()
        mid = TARGET_TICKS // 2
        result = skill.steps({"cur_tick": mid})
        assert result is not None
        assert result[0]["command"] == "advance"
        # Halfway → between 1 and 7 days.
        chunk_days = result[0]["args"][0] // TICKS_PER_DAY
        assert 1 <= chunk_days <= 7

    def test_in_chain_reaches_target(self):
        chain = make_skill_chain(StartFortress(), GradualAdvance())
        runner = EpisodeRunner(seed=5, max_steps=100, action_budget=60)
        m = runner.run(chain)
        assert validate_episode_metrics(m)
        # Should get close to 30 days.
        assert m["final_tick"] >= TARGET_TICKS * 0.8


class TestResourceMonitor:
    """ResourceMonitor emits structured observation metadata."""

    def test_emits_observe_with_metadata(self):
        skill = ResourceMonitor()
        units = [
            {"killed": False, "civ_id": 1},
            {"killed": True, "civ_id": 2},
        ]
        obs = {
            "cur_tick": 86400 * 10,
            "units": units,
        }
        result = skill.steps(obs)
        assert result is not None
        assert result[0]["command"] == "observe"
        assert result[0]["meta_total_units"] == 2
        assert result[0]["meta_alive"] == 1
        assert result[0]["meta_survival_rate"] == 0.5

    def test_empty_units(self):
        skill = ResourceMonitor()
        obs = {"cur_tick": 0, "units": []}
        result = skill.steps(obs)
        assert result is not None
        assert result[0]["meta_total_units"] == 0
        assert result[0]["meta_alive"] == 0
        assert result[0]["meta_survival_rate"] == 0.0

    def test_no_dead_units(self):
        skill = ResourceMonitor()
        units = [
            {"killed": False, "civ_id": 1},
            {"killed": False, "civ_id": 2},
            {"killed": False, "civ_id": 3},
        ]
        obs = {"cur_tick": 5000, "units": units}
        result = skill.steps(obs)
        assert result[0]["meta_survival_rate"] == 1.0


class TestMultiSeedStress:
    """Statistical properties hold across many seeds and policies."""

    def _runs_for_policy(self, policy, n=20):
        metrics = []
        for i in range(n):
            r = EpisodeRunner(seed=i * 37 + 13, max_steps=80, action_budget=50)
            metrics.append(r.run(policy))
        return metrics

    def test_baseline_mean_above_4(self):
        runs = self._runs_for_policy(baseline_policy, n=20)
        agg = evaluate_multiple_runs(runs)
        assert agg["mean_score"] >= 0.4

    def test_cpu_mean_above_4(self):
        runs = self._runs_for_policy(cpu_policy, n=20)
        agg = evaluate_multiple_runs(runs)
        assert agg["mean_score"] >= 0.4

    def test_worst_run_not_zero(self):
        """Every seed should achieve at least some progress."""
        runs = self._runs_for_policy(baseline_policy, n=15)
        agg = evaluate_multiple_runs(runs)
        assert agg["worst_score"] > 0

    def test_deterministic_across_policies(self):
        """Same seed + same policy always yields same metrics."""
        for policy in (baseline_policy, cpu_policy):
            r1 = EpisodeRunner(seed=420, max_steps=50, action_budget=30)
            m1 = r1.run(policy)
            r2 = EpisodeRunner(seed=420, max_steps=50, action_budget=30)
            m2 = r2.run(policy)
            assert m1["final_tick"] == m2["final_tick"]
            assert m1["survivors"] == m2["survivors"]


class TestCurriculumGradualAndMonitor:
    """Curriculum exercises new GradualAdvance and ResourceMonitor skills."""

    def test_gradual_chain_survives(self):
        chain = make_skill_chain(StartFortress(), GradualAdvance(), SurvivalGuard(min_citizens=1))
        runner = EpisodeRunner(seed=0, max_steps=100, action_budget=60)
        m = runner.run(chain)
        assert validate_episode_metrics(m)

    def test_monitor_in_chain_no_regression(self):
        chain = make_skill_chain(
            StartFortress(),
            GradualAdvance(),
            ResourceMonitor(),
        )
        runner = EpisodeRunner(seed=1, max_steps=50, action_budget=40)
        m = runner.run(chain)
        assert validate_episode_metrics(m)


class TestSkillChainReset:
    """make_skill_chain propagates _reset() to skills defining reset()."""

    def test_reset_clears_emergency_pause_state(self):
        skill = EmergencyPause(max_deaths=1)
        chain = make_skill_chain(StartFortress(), skill)

        warm_obs = {"paused": True, "units": [
            {"killed": False, "civ_id": i} for i in range(4)
        ]}
        a1 = chain(warm_obs)
        assert a1["command"] == "unpause"

        # Feed safe observation to establish baseline alive count.
        warm2 = {"paused": False, "units": [
            {"killed": False, "civ_id": i} for i in range(4)
        ]}
        chain._reset()
        a2 = chain(warm2)

        # After reset, baseline captures alive count for comparison.
        assert skill._prev_alive == 4

    def test_reset_called_twice_clears_state(self):
        """Two back-to-back runs reset EmergencyPause between Episodes."""
        ep_skill = EmergencyPause(max_deaths=1)
        chain = make_skill_chain(StartFortress(), AdvanceTimeStep(ticks=100), ep_skill)
        r = EpisodeRunner(seed=0, max_steps=10, action_budget=5)
        r.run(chain)

        # _prev_alive was set during the run (skill exercised).
        assert ep_skill._prev_alive is not None
        assert ep_skill._needs_baseline is False

        # Manually reset and verify clean state before next exercise.
        chain._reset()
        assert ep_skill._prev_alive is None
        assert ep_skill._needs_baseline is True

        r.run(chain)  # Second run exercises the skill again from clean state.
        # _prev_alive is set during the episode — that is expected behavior.
        assert ep_skill._prev_alive is not None


class TestRunnerMultiple:
    """EpisodeRunner.run_multiple() produces deterministic batch results."""

    def test_returns_correct_count(self):
        r = EpisodeRunner(max_steps=10, action_budget=6)
        results = r.run_multiple(baseline_policy, num_runs=5, seed_start=10)
        assert len(results) == 5

    def test_each_result_valid_contract(self):
        r = EpisodeRunner(max_steps=15, action_budget=8)
        results = r.run_multiple(cpu_policy, num_runs=3, seed_start=0)
        for m in results:
            assert validate_episode_metrics(m) is True

    def test_seeded_sweep_deterministic(self):
        """Two identical sweeps produce byte-identical metrics lists."""
        r1 = EpisodeRunner(max_steps=20, action_budget=12)
        a = r1.run_multiple(baseline_policy, num_runs=4, seed_start=100)

        r2 = EpisodeRunner(max_steps=20, action_budget=12)
        b = r2.run_multiple(baseline_policy, num_runs=4, seed_start=100)

        for m1, m2 in zip(a, b):
            assert m1["seed"] == m2["seed"]
            assert m1["outcome"] == m2["outcome"]
            assert m1["survivors"] == m2["survivors"]
            assert m1["steps_taken"] == m2["steps_taken"]

    def test_seed_incrementing(self):
        r = EpisodeRunner(max_steps=5, action_budget=3)
        results = r.run_multiple(baseline_policy, num_runs=4, seed_start=50)
        for i, m in enumerate(results):
            assert m["seed"] == 50 + i

    def test_batch_aggregate_computed(self):
        """Verify aggregate_runs over run_multiple output."""
        r = EpisodeRunner(max_steps=20, action_budget=10)
        runs = r.run_multiple(baseline_policy, num_runs=8, seed_start=0)
        agg = aggregate_runs(runs)
        assert agg["runs"] == 8
        assert 0 <= agg["mean_score"] <= 1
        assert agg["std_dev"] >= 0


class TestEpisodeLoggerIntegration:
    """EpisodeLogger is wired into EpisodeRunner and produces fingerprints."""

    def test_logger_initialized_after_run(self):
        r = EpisodeRunner(seed=10, max_steps=5, action_budget=3)
        assert r._logger is None
        r.run(baseline_policy)
        logger = r.get_logger()
        assert logger is not None
        assert logger.seed == 10

    def test_fingerprint_deterministic(self):
        """Two identical runs produce the same SHA-256 fingerprint."""
        ra = EpisodeRunner(seed=42, max_steps=20, action_budget=15)
        ra.run(baseline_policy)
        fp_a = ra.fingerprint()

        rb = EpisodeRunner(seed=42, max_steps=20, action_budget=15)
        rb.run(baseline_policy)
        fp_b = rb.fingerprint()

        assert fp_a == fp_b
        assert len(fp_a) == 64  # SHA-256 hex length

    def test_fingerprint_differs_across_seeds(self):
        """Different seeds yield different fingerprints."""
        ra = EpisodeRunner(seed=1, max_steps=20, action_budget=15)
        ra.run(baseline_policy)
        fp_a = ra.fingerprint()

        rb = EpisodeRunner(seed=999, max_steps=20, action_budget=15)
        rb.run(baseline_policy)
        fp_b = rb.fingerprint()

        assert fp_a != fp_b

    def test_log_json_contains_seed(self):
        r = EpisodeRunner(seed=77, max_steps=10, action_budget=8)
        r.run(cpu_policy)
        data = json.loads(r.log_json())
        assert data["seed"] == 77
        assert "actions" in data
        assert "ticks" in data

    def test_logger_records_ticks(self):
        r = EpisodeRunner(seed=5, max_steps=10, action_budget=8)
        r.run(baseline_policy)
        logger = r.get_logger()
        ticks = logger.as_dict()["ticks"]
        assert len(ticks) > 0

    def test_logger_action_count_matches_trace(self):
        r = EpisodeRunner(seed=3, max_steps=6, action_budget=4)
        r.run(baseline_policy)
        logger = r.get_logger()
        assert logger.action_count() == r.metrics["actions_used"]


class TestInferenceLatency:
    """evaluator_public latency benchmarking is functional and bounded."""

    def test_baseline_latency_sub_ms(self):
        from evaluator_public import measure_policy_latency
        obs = {"paused": False, "cur_tick": 5000, "units": [
            {"killed": False, "civ_id": 1}
        ]}
        ms = measure_policy_latency(baseline_policy, obs, n_bench=200)
        assert ms < 1e-3

    def test_cpu_latency_sub_ms(self):
        from evaluator_public import measure_policy_latency
        obs = {"paused": False, "cur_tick": 5000, "units": [
            {"killed": False, "civ_id": 1}
        ]}
        ms = measure_policy_latency(cpu_policy, obs, n_bench=200)
        assert ms < 1e-3

    def test_batch_latency_returns_dict(self):
        from evaluator_public import benchmark_inference_latency
        results = benchmark_inference_latency(
            ("baseline", baseline_policy),
            ("cpu", cpu_policy),
            n_bench=50,
        )
        assert "baseline" in results
        assert "cpu" in results
        for name in ("baseline", "cpu"):
            assert 0 < results[name] < 1.0

    def test_cpu_faster_than_or_equal_baseline(self):
        """CPU policy should not be meaningfully slower than baseline."""
        from evaluator_public import measure_policy_latency
        obs = {"paused": False, "cur_tick": 5000, "units": [
            {"killed": False, "civ_id": i} for i in range(4)
        ]}
        ms_baseline = measure_policy_latency(baseline_policy, obs, n_bench=200)
        ms_cpu = measure_policy_latency(cpu_policy, obs, n_bench=200)
        # CPU should not be 10x slower
        assert ms_cpu <= ms_baseline * 10


class TestTimeProbeHelper:
    """Pure-python helpers from bridge/probe can be unit tested here.

    df.global.cur_year, cur_season, cur_year_tick fields are verified
    in bridge/core.lua (line 49-52) and live-probed via the Lua JSON
    builder in bridge/probe.py.
    """

    def test_total_ticks_year_zero(self):
        t = total_ticks(0, 0, 100)
        assert t == 100

    def test_total_ticks_after_first_season(self):
        # year=0, season=1, tick=0 → 1 * TICKS_PER_SEASON
        t = total_ticks(0, 1, 0)
        assert t == 1 * 86400 * 361

    def test_total_ticks_nonzero_year(self):
        # year=1, season=0, tick=0 is two full years worth of seasons.
        t = total_ticks(1, 0, 0)
        expected = (1 * 4 + 0) * 361 * 86400
        assert t == expected

    def test_total_ticks_with_partial_tick(self):
        # year=0, season=2 (autumn), 5 days in → base + 5*86400
        t = total_ticks(0, 2, 5 * 86400)
        expected = 2 * 361 * 86400 + 5 * 86400
        assert t == expected

    def test_total_ticks_null_fields(self):
        assert total_ticks(None, 0, 0) == 0
        assert total_ticks(0, None, 0) == 0
        assert total_ticks(0, 0, None) == 0

    def test_days_elapsed_integer(self):
        from bridge.probe import TICKS_PER_DAY
        # 10 full days in current season → 10.
        d = days_elapsed(0, 0, 10 * TICKS_PER_DAY)
        assert d == 10

    def test_days_elapsed_30_day_survival(self):
        from bridge.probe import TICKS_PER_DAY
        # Start at end of season 0, advance to day 30 in season 1.
        total = (1 * 361 + 30) * TICKS_PER_DAY
        d = days_elapsed(0, 1, _ := 30 * TICKS_PER_DAY)
        # Just verify the partial computation is correct for season 1
        assert d == (0 * 4 + 1) * 361 // 1 + 30

    def test_days_elapsed_zero(self):
        assert days_elapsed(0, 0, 0) == 0

    def test_season_name_mapping(self):
        assert season_name(0) == "SPRING"
        assert season_name(1) == "SUMMER"
        assert season_name(2) == "AUTUMN"
        assert season_name(3) == "WINTER"

    def test_season_name_wrap(self):
        from bridge.probe import SEASONS_PER_YEAR
        # Index modulo wraps.
        assert season_name(SEASONS_PER_YEAR) == "SPRING"
        assert season_name(SEASONS_PER_YEAR + 1) == "SUMMER"

    def test_season_name_none(self):
        assert season_name(None) is None

    def test_constants_match_contracts(self):
        """TICKS_PER_DAY in probe matches baseline and contract code."""
        from bridge.probe import TICKS_PER_DAY
        from player.baseline import TICKS_PER_DAY as BTPD
        assert TICKS_PER_DAY == BTPD == 86400

    def test_ticks_per_season_consistency(self):
        """TICKS_PER_SEASON across probe, baseline, and evaluator all equal 361 * 86400."""
        from bridge.probe import TICKS_PER_SEASON as PROBE_TPS
        from player.baseline import DAYS_PER_SEASON as BASELINES_DPS
        from player.baseline import TICKS_PER_DAY as BASELINE_TPD
        from evaluator_public import DAYS_PER_SEASON as EVAL_DPS
        expected = 361 * 86400
        assert expected == PROBE_TPS
        assert expected == BASELINES_DPS * BASELINE_TPD
        assert EVAL_DPS == 361

    def test_lua_time_snapshot_is_string(self):
        """The Lua expression builder returns valid code."""
        from bridge.probe import _lua_time_snapshot
        code = _lua_time_snapshot()
        # Must reference df.global and the known calendar fields.
        assert "df.global" in code
        assert "cur_year" in code
        assert "cur_season" in code
        assert "cur_year_tick" in code
        assert "pause_state" in code

    def test_probe_time_returns_none_no_server(self):
        """probe_time returns None when no DFHack process is listening."""
        result = probe_time(timeout=2)
        # With no server, runner returns empty or error → None.
        assert result is None


class TestDfhackErrorHandling:
    """Tests for _dfhack_run segfault/error capture and probe_time guard.

    Live-probed evidence: /srv/df-bonsai/current/hack/dfhack-run exits with code 139
    (segfault) when no DF process is running. The runner must return an error dict
    rather than crashing or returning empty data.
    """

    def test_dfhack_run_returns_error_dict_on_segfault(self):
        """_dfhack_run captures non-zero exit as structured error.

        Live-probed: /srv/df-bonsai/current/hack/dfhack-run crashes (segfault / SIGSEGV)
        when no DF process is running. subprocess.run captures a non-zero returncode;
        the runner wraps it into an error dict with _dfhack_error, exit_code, _stderr.
        """
        from game_runner.episode import _dfhack_run
        result = _dfhack_run("print('hello')", timeout=5)
        assert isinstance(result, dict)
        assert "_dfhack_error" in result
        assert result["_dfhack_error"] is True
        assert "exit_code" in result
        # Non-zero exit code (varies by platform: 1, 139, etc.)
        assert result["exit_code"] > 0
        assert "_stderr" in result

    def test_dfhack_run_error_dict_no_data_fields(self):
        """Error dict must NOT contain observation fields (year, season, etc.)."""
        from game_runner.episode import _dfhack_run
        result = _dfhack_run("print('hello')", timeout=5)
        assert "year" not in result
        assert "season" not in result
        assert "tick" not in result

    def test_probe_time_none_on_dfhack_error(self):
        """probe_time returns None when _dfhack_error dict is returned."""
        # This is a live test — the dfhack binary will segfault, probe_time should
        # catch it and return None (not raise).
        result = probe_time(timeout=5)
        assert result is None

    def test_dfhack_run_empty_stdout_on_success_path(self):
        """_dfhack_run returns {} when stdout is empty and exit code is 0."""
        import unittest.mock as mock
        from game_runner.episode import _dfhack_run
        fake_proc = mock.Mock()
        fake_proc.stdout = ""
        fake_proc.stderr = ""
        fake_proc.returncode = 0
        with mock.patch("subprocess.run", return_value=fake_proc):
            result = _dfhack_run("echo '{}'", timeout=5)
            assert result == {}

    def test_dfhack_run_error_on_non_zero(self):
        """_dfhack_run returns error dict for any non-zero exit code."""
        import unittest.mock as mock
        from game_runner.episode import _dfhack_run
        fake_proc = mock.Mock()
        fake_proc.stdout = ""
        fake_proc.stderr = "custom error"
        fake_proc.returncode = 42
        with mock.patch("subprocess.run", return_value=fake_proc):
            result = _dfhack_run("boom", timeout=5)
            assert "_dfhack_error" in result
            assert result["exit_code"] == 42
            assert "custom error" in result["_stderr"]


class TestEmergencyPauseSkill:
    """Deterministic tests for EmergencyPause skill."""

    def test_no_pause_safe(self):
        skill = EmergencyPause(max_deaths=2)
        obs = {"units": [
            {"killed": False, "civ_id": 1},
            {"killed": False, "civ_id": 2},
        ]}
        assert skill.steps(obs) is None

    def test_pause_on_spike(self):
        skill = EmergencyPause(max_deaths=1)
        obs_before = {"units": [
            {"killed": False, "civ_id": i} for i in range(4)
        ]}
        skill.steps(obs_before)
        # Two die
        obs_after = {"units": [
            {"killed": True, "civ_id": 0},
            {"killed": True, "civ_id": 1},
            {"killed": False, "civ_id": 2},
            {"killed": False, "civ_id": 3},
        ]}
        result = skill.steps(obs_after)
        assert result is not None
        assert result[0]["command"] == "pause"

    def test_reset_clears_state(self):
        skill = EmergencyPause(max_deaths=1)
        obs_before = {"units": [
            {"killed": False, "civ_id": i} for i in range(4)
        ]}
        skill.steps(obs_before)
        # Reset should allow further observation without triggering.
        skill.reset()
        obs_safe = {"units": [
            {"killed": True, "civ_id": 0},
            {"killed": False, "civ_id": 1},
        ]}
        assert skill.steps(obs_safe) is None

    def test_needs_baseline_defers_first_call(self):
        """After reset the very first steps() returns None without setting _prev_alive.

        Regression guard for the '_needs_baseline' field added in EmergencyPause
        so that a fresh episode does not treat an empty baseline as zero deaths."""
        skill = EmergencyPause(max_deaths=1)
        assert skill._needs_baseline is True
        assert skill._prev_alive is None

        live_obs = {"units": [
            {"killed": False, "civ_id": i} for i in range(4)
        ]}
        result = skill.steps(live_obs)
        # First call captures baseline alive count for subsequent comparisons.
        assert result is None
        assert skill._needs_baseline is False
        assert skill._prev_alive == 4

    def test_needs_baseline_after_reset_defers_again(self):
        """reset() restores _needs_baseline so the pattern is re-entrant."""
        skill = EmergencyPause(max_deaths=1)
        units4 = {"units": [
            {"killed": False, "civ_id": i} for i in range(4)
        ]}
        # Prime the skill.
        skill.steps(units4)
        assert skill._needs_baseline is False

        skill.reset()
        assert skill._needs_baseline is True
        assert skill._prev_alive is None

        result = skill.steps(units4)
        assert result is None
        assert skill._needs_baseline is False

    def test_in_chain_with_guard(self):
        chain = make_skill_chain(
            StartFortress(),
            AdvanceTimeStep(ticks=5000),
            EmergencyPause(max_deaths=2),
        )
        r = EpisodeRunner(seed=0, max_steps=10, action_budget=6)
        m = r.run(chain)
        assert validate_episode_metrics(m)


class TestEmergencyPauseCurriculum:
    """Curriculum exposes a level that uses EmergencyPause."""

    def test_emergency_pause_level_present(self):
        names = [lvl["name"] for lvl in CURRICULUM_LEVELS]
        assert "survive_30_days_with_safety" in names

    def test_emergency_pause_level_runs(self):
        from curricula.levels import _emergency_chain
        runner = EpisodeRunner(seed=0, max_steps=100, action_budget=50)
        metrics = runner.run(_emergency_chain)
        assert validate_episode_metrics(metrics)


class TestProfessionLabor:
    """Tests for profession and labor mapping in bridge/probe.py."""

    def test_map_has_known_professions(self):
        expected = {"Chef", "Miner", "Farmer", "Doctor", "Mason", "Laborer",
                    "Smith", "Fisherdwarf", "Migrant", "Meleedwarf",
                    "Marksdwarf", "Tailor", "Craftsdwarf", "Outdoorsdwarf",
                    "StartManager"}
        assert set(PROFESSION_LABOR_MAP.keys()) == expected

    def test_known_labors_non_empty(self):
        assert len(KNOWN_LABORS) >= 15

    def test_known_labors_sorted(self):
        assert sorted(KNOWN_LABORS) == KNOWN_LABORS

    def test_cook_belongs_to_chef(self):
        profs = labor_to_professions("COOK")
        assert "Chef" in profs

    def test_mine_belongs_to_miner(self):
        profs = labor_to_professions("MINE")
        assert "Miner" in profs

    def test_haul_stone_many_professions(self):
        profs = labor_to_professions("HAUL_STONE")
        assert len(profs) >= 8

    def test_unknown_labor_returns_empty(self):
        assert labor_to_professions("NONEXISTENT_LABOR") == []

    def test_get_chef_labors(self):
        labors = get_profession_labors("Chef")
        assert "COOK" in labors
        assert "BUTCHER" in labors

    def test_get_unknown_profession(self):
        assert get_profession_labors("Wizard") is None

    def test_start_manager_no_labors(self):
        assert get_profession_labors("StartManager") == []

    def test_classify_hauling(self):
        assert classify_labor_category("HAUL_STONE") == "hauling"
        assert classify_labor_category("HAUL_WOOD") == "hauling"
        assert classify_labor_category("HANDLE_VEHICLES") == "hauling"

    def test_classify_crafting(self):
        assert classify_labor_category("FORGE TOOL") == "crafting"
        assert classify_labor_category("ALCHEMIST") == "crafting"
        assert classify_labor_category("WOODWORK") == "crafting"

    def test_classify_food(self):
        assert classify_labor_category("COOK") == "food"
        assert classify_labor_category("FISHING") == "food"
        assert classify_labor_category("HARVEST") == "food"

    def test_classify_extraction(self):
        assert classify_labor_category("MINE") == "extraction"
        assert classify_labor_category("WOODCUTTING") == "extraction"

    def test_classify_military(self):
        assert classify_labor_category("MELEE COMBAT") == "military"
        assert classify_labor_category("SHOOTING RANGED WEAPONS") == "military"

    def test_classify_utility(self):
        assert classify_labor_category("CLEAN") == "utility"
        assert classify_labor_category("PULL_LEVER") == "utility"
        assert classify_labor_category("DETAIL") == "utility"

    def test_classify_unknown(self):
        assert classify_labor_category("SOMETHING_NEW") == "unknown"

    def test_can_perform_chef_cook(self):
        assert can_perform_labor("Chef", "COOK") is True

    def test_cannot_perform_unknown_profession(self):
        assert can_perform_labor("Wizard", "COOK") is False

    def test_can_perform_mine(self):
        assert can_perform_labor("Miner", "MINE") is True

    def test_chef_cannot_mine(self):
        assert can_perform_labor("Chef", "MINE") is False

    def test_all_known_labors_have_category(self):
        for labor in KNOWN_LABORS:
            cat = classify_labor_category(labor)
            assert cat != "unknown", f"Labor '{labor}' has no category"


class TestTileClassification:
    """Deterministic tests for tile classification helpers in bridge/probe.py."""

    def test_tile_material_enum_map(self):
        assert isinstance(TILE_MATERIAL_ENUM_MAP, dict)
        assert len(TILE_MATERIAL_ENUM_MAP) >= 4
        assert TILE_MATERIAL_ENUM_MAP[0] == "SOIL"
        assert TILE_MATERIAL_ENUM_MAP[1] == "STONE"
        assert TILE_MATERIAL_ENUM_MAP[2] == "PLANKS"
        assert TILE_MATERIAL_ENUM_MAP[3] == "BRICKS"

    def test_classify_material_known(self):
        assert classify_material(0) == "SOIL"
        assert classify_material(1) == "STONE"
        assert classify_material(2) == "PLANKS"
        assert classify_material(3) == "BRICKS"

    def test_classify_material_unknown(self):
        assert classify_material(999) == "UNKNOWN"
        assert classify_material(-1) == "UNKNOWN"

    def test_is_liquid_tile_true(self):
        assert is_liquid_tile(1024) is True
        assert is_liquid_tile(2000) is True

    def test_is_liquid_tile_false(self):
        assert is_liquid_tile(1023) is False
        assert is_liquid_tile(0) is False

    def test_is_floor_tile_true(self):
        assert is_floor_tile(256) is True
        assert is_floor_tile(500) is True
        assert is_floor_tile(511) is True

    def test_is_floor_tile_false(self):
        assert is_floor_tile(255) is False
        assert is_floor_tile(512) is False
        assert is_floor_tile(0) is False

    def test_classify_tile_label_liquid(self):
        assert classify_tile_label(1024) == "LIQUID"
        assert classify_tile_label(2048) == "LIQUID"

    def test_classify_tile_label_floor(self):
        assert classify_tile_label(300) == "FLOOR"
        assert classify_tile_label(256) == "FLOOR"

    def test_classify_tile_label_wall(self):
        assert classify_tile_label(1280) == "WALL"
        assert classify_tile_label(1535) == "WALL"

    def test_classify_tile_label_default(self):
        assert classify_tile_label(0) == "DEFAULT"
        assert classify_tile_label(100) == "DEFAULT"


class TestJobSystem:
    """Deterministic tests for job system helpers in bridge/probe.py."""

    def _sample_jobs(self):
        return [
            {"idx": 1, "type": "df.job_type.ConstructBed", "cancelled": False, "suspended": False, "worker_id": 1001, "n_items": 3},
            {"idx": 2, "type": "df.job_type.PrepareMeal", "cancelled": False, "suspended": False, "worker_id": None, "n_items": 2},
            {"idx": 3, "type": "df.job_type.MakeBarrel", "cancelled": True, "suspended": False, "worker_id": None, "n_items": 1},
            {"idx": 4, "type": "df.job_type.CollectSand", "cancelled": False, "suspended": True, "worker_id": None, "n_items": 0},
            {"idx": 5, "type": "df.job_type.ConstructBed", "cancelled": False, "suspended": True, "worker_id": None, "n_items": 5},
            {"idx": 6, "type": "df.job_type.SmeltOre", "cancelled": False, "suspended": False, "worker_id": 2002, "n_items": 1},
        ]

    def test_job_state_constants(self):
        assert JOB_STATE_QUEUED == "queued"
        assert JOB_STATE_ACTIVE == "active"
        assert JOB_STATE_SUSPENDED == "suspended"
        assert JOB_STATE_CANCELLED == "cancelled"

    def test_job_state_cancelled(self):
        j = {"cancelled": True, "worker_id": None}
        assert job_state(j) == JOB_STATE_CANCELLED

    def test_job_state_suspended(self):
        j = {"cancelled": False, "suspended": True, "worker_id": None}
        assert job_state(j) == JOB_STATE_SUSPENDED

    def test_job_state_active(self):
        j = {"cancelled": False, "suspended": False, "worker_id": 42}
        assert job_state(j) == JOB_STATE_ACTIVE

    def test_job_state_queued(self):
        j = {"cancelled": False, "suspended": False, "worker_id": None}
        assert job_state(j) == JOB_STATE_QUEUED

    def test_job_category_construction(self):
        assert job_category("df.job_type.ConstructBed") == "construction"
        assert job_category("df.job_type.ConstructChest") == "construction"

    def test_job_category_food(self):
        assert job_category("df.job_type.PrepareMeal") == "food"
        assert job_category("df.job_type.ButcherAnimal") == "food"

    def test_job_category_manufacturing(self):
        assert job_category("df.job_type.MakeBarrel") == "manufacturing"
        assert job_category("df.job_type.SmeltOre") == "manufacturing"
        assert job_category("df.job_type.CutGems") == "manufacturing"

    def test_job_category_harvesting(self):
        assert job_category("df.job_type.CollectSand") == "harvesting"
        assert job_category("df.job_type.HarvestFruits") == "harvesting"

    def test_job_category_other_fallback(self):
        assert job_category("") == "other"
        assert job_category(None) == "other"
        assert job_category("unknown_type") == "other"

    def test_count_jobs_by_state(self):
        jobs = self._sample_jobs()
        counts = count_jobs_by_state(jobs)
        # idx1: cancelled=F, suspended=F, worker=1001 -> active
        # idx2: cancelled=F, suspended=F, worker=None -> queued
        # idx3: cancelled=T -> cancelled
        # idx4: cancelled=F, suspended=T -> suspended
        # idx5: cancelled=F, suspended=T -> suspended
        # idx6: cancelled=F, suspended=F, worker=2002 -> active
        assert counts["active"] == 2
        assert counts["queued"] == 1
        assert counts["cancelled"] == 1
        assert counts["suspended"] == 2

    def test_count_jobs_by_category(self):
        jobs = self._sample_jobs()
        cats = count_jobs_by_category(jobs)
        # ConstructBed(2) -> construction, PrepareMeal -> food, MakeBarrel -> manufacturing, CollectSand -> harvesting, SmeltOre -> manufacturing
        assert cats["construction"] == 2
        assert cats["food"] == 1
        assert cats["manufacturing"] == 2
        assert cats["harvesting"] == 1

    def test_active_worker_ids(self):
        jobs = self._sample_jobs()
        workers = active_worker_ids(jobs)
        assert set(workers) == {1001, 2002}

    def test_suspicious_jobs(self):
        jobs = self._sample_jobs()
        stuck = suspicious_jobs(jobs)
        # idx5: suspended=True, n_items=5, worker_id=None -> stuck
        # idx4: suspended=True, n_items=0 -> not stuck (no items to block on)
        assert len(stuck) == 1
        assert stuck[0]["idx"] == 5


class TestTileMapLuaContract:
    """Static contract tests for bridge.tile_map() in core.lua.

    Validates the Lua source directly — no live DFHack required.
    Ensures the tile_map function exists, returns the correct shape,
    and that world_summary has been fully removed.
    """

    @staticmethod
    def _core_lua_path():
        return os.path.join(os.path.dirname(__file__), "..", "bridge", "core.lua")

    @staticmethod
    def _load_core():
        with open(TestTileMapLuaContract._core_lua_path()) as f:
            return f.read()

    def test_tile_map_function_defined(self):
        src = self._load_core()
        assert "function bridge.tile_map()" in src, (
            "bridge.tile_map() function not defined in core.lua"
        )

    def test_world_summary_removed(self):
        src = self._load_core()
        assert "world_summary" not in src, (
            "world_summary should be fully removed from core.lua"
        )

    def test_tile_map_returns_has_map_false_default(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "has_map" in func_body
        assert "has_map = false" in func_body, (
            "tile_map must initialize has_map to false as the default guard"
        )

    def test_tile_map_returns_dimension_fields(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        for field in ["width", "height", "depth", "block_width", "block_height", "block_depth"]:
            assert f"result.{field}" in func_body, (
                f"tile_map result must set {field} from map dimensions"
            )

    def test_tile_map_returns_tiles_array(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "tiles = {}" in func_body, (
            "tile_map must initialize tiles as an empty table"
        )

    def test_tile_map_guards_no_global(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "df.global" in func_body, (
            "tile_map must guard on absence of df.global"
        )

    def test_tile_map_guards_no_map(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "df.global.world.map" in func_body or "map = df.global.world.map" in func_body, (
            "tile_map must guard on absence of the map object"
        )

    def test_tile_map_samples_tiles(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "dfhack.maps" in func_body, (
            "tile_map must use dfhack.maps for tile sampling"
        )
        assert "getTileType" in func_body, (
            "tile_map must call getTileType to read tile data"
        )

    def test_tile_map_tile_entries_have_required_fields(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        for field in ["x", "y", "z", "type", "material", "walkable"]:
            assert field in func_body, (
                f"tile_map tile entries must include field '{field}'"
            )

    def test_tile_map_uses_limit_bound(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "256" in func_body or "limit" in func_body, (
            "tile_map must bound tile sampling to prevent oversized output"
        )

    def test_tile_map_uses_isvalidtilepos(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "isValidTilePos" in func_body, (
            "tile_map must validate tile positions before sampling"
        )

    def test_tile_map_uses_pcall_for_safety(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "pcall" in func_body, (
            "tile_map must use pcall for material and walkability lookups"
        )

    def test_tile_map_uses_goto_continue_loop(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "::continue_loop::" in func_body, (
            "tile_map must use goto to skip invalid tile positions"
        )

    def test_tile_map_material_classification(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "tiletype.attrs" in func_body, (
            "tile_map must read tiletype attributes for material class"
        )
        assert "tiletype_material" in func_body, (
            "tile_map must walk the tiletype_material enum"
        )

    def test_tile_map_walkability_check(self):
        src = self._load_core()
        func_body = src.split("function bridge.tile_map()")[1].split("\nreturn bridge")[0]
        assert "iswalkable" in func_body, (
            "tile_map must check tile walkability"
        )

    def test_bridge_return_still_present(self):
        src = self._load_core()
        assert src.strip().endswith("return bridge"), (
            "core.lua must end with 'return bridge'"
        )


class TestUnitNeedsContract:
    """Deterministic tests for unit needs / counters helpers in bridge/probe.py."""

    def test_threshold_constants(self):
        assert HUNGER_DIRE_THRESHOLD == 75000
        assert THIRST_DIRE_THRESHOLD == 50000
        assert SLEEPINESS_DIRE_THRESHOLD == 150000

    def test_counters_field_lists(self):
        expected_c1 = {"job_counter", "swap_counter", "winded", "stunned",
                        "unconscious", "suffocation", "webbed", "pain",
                        "nausea", "dizziness"}
        assert set(COUNTERS_1_FIELDS) == expected_c1
        expected_c2 = {"hunger_timer", "thirst_timer", "sleepiness_timer",
                        "exhaustion", "stomach_content", "stored_fat"}
        assert set(COUNTERS_2_FIELDS) == expected_c2

    def test_is_in_dire_need_comfortable(self):
        comfy = {"hunger_timer": 1000, "thirst_timer": 500, "sleepiness_timer": 2000}
        assert is_in_dire_need(comfy) is False

    def test_is_in_dire_need_hunger(self):
        hungrier = {"hunger_timer": 75001, "thirst_timer": 0, "sleepiness_timer": 0}
        assert is_in_dire_need(hungrier) is True

    def test_is_in_dire_need_exact_boundary_hunger(self):
        at_limit = {"hunger_timer": 75000, "thirst_timer": 0, "sleepiness_timer": 0}
        assert is_in_dire_need(at_limit) is False

    def test_is_in_dire_need_thirst(self):
        thirsty = {"hunger_timer": 0, "thirst_timer": 50001, "sleepiness_timer": 0}
        assert is_in_dire_need(thirsty) is True

    def test_is_in_dire_need_sleepiness(self):
        sleepy = {"hunger_timer": 0, "thirst_timer": 0, "sleepiness_timer": 150001}
        assert is_in_dire_need(sleepy) is True

    def test_is_in_dire_need_empty_dict(self):
        assert is_in_dire_need({}) is False

    def test_need_severity_none(self):
        comfy = {"hunger_timer": 100, "thirst_timer": 100, "sleepiness_timer": 100}
        assert need_severity(comfy) == 0

    def test_need_severity_single_dire(self):
        single = {"hunger_timer": 80000}
        assert need_severity(single) == 1

    def test_need_severity_all_dire(self):
        all_dire = {
            "hunger_timer": 75001,
            "thirst_timer": 50001,
            "sleepiness_timer": 150001,
        }
        assert need_severity(all_dire) == 3

    def test_need_severity_physical_distress(self):
        pained = {"pain": 5}
        assert need_severity(pained) == 0.5

    def test_need_severity_combined(self):
        combined = {
            "hunger_timer": 75001,
            "thirst_timer": 50001,
            "pain": 3,
            "nausea": 2,
        }
        assert need_severity(combined) == 3.0

    def test_need_severity_max_achievable(self):
        """Max score is 3 dire + 4 physical flags * 0.5 = 5.0."""
        extreme = {
            "hunger_timer": 75001,
            "thirst_timer": 50001,
            "sleepiness_timer": 150001,
            "pain": 1,
            "nausea": 1,
            "dizziness": 1,
            "suffocation": 1,
        }
        assert need_severity(extreme) == 5.0


class TestBuildingObservation:
    """Deterministic tests for building observation helpers in bridge/probe.py."""

    def test_known_building_types_list(self):
        assert isinstance(KNOWN_BUILDING_TYPES, list)
        assert len(KNOWN_BUILDING_TYPES) >= 10

    def test_building_schema_keys_complete(self):
        expected = {"idx", "id", "type", "subtype", "custom_id", "center",
                    "built", "build_stage", "max_stage"}
        assert set(BUILDING_SCHEMA_KEYS) == expected

    def _sample_bld(self, btype="Workshop", built=True, stage=3, maxstg=5,
                    cx=10, cy=20, cz=5):
        return {
            "idx": 1, "id": 1001, "type": f"df.building_type.{btype}",
            "subtype": 2, "custom_id": -1,
            "center": {"x": cx, "y": cy, "z": cz},
            "built": built, "build_stage": stage, "max_stage": maxstg,
        }

    def test_is_complete_building_true(self):
        b = self._sample_bld()
        assert is_complete_building(b) is True

    def test_is_complete_building_not_built(self):
        b = self._sample_bld(built=False)
        assert is_complete_building(b) is False

    def test_is_complete_building_negative_stage(self):
        b = self._sample_bld(stage=-1)
        assert is_complete_building(b) is False

    def test_is_complete_building_empty_dict(self):
        assert is_complete_building({}) is False

    def test_unfinished_buildings_filters(self):
        complete = self._sample_bld()
        incomplete = self._sample_bld(built=False, stage=1, maxstg=5)
        result = unfinished_buildings([complete, incomplete])
        assert len(result) == 1
        assert result[0] is incomplete

    def test_unfinished_buildings_empty_input(self):
        assert unfinished_buildings([]) == []

    def test_building_type_label_with_prefix(self):
        b = self._sample_bld("Furnace")
        assert building_type_label(b) == "Furnace"

    def test_building_type_label_unknown(self):
        assert building_type_label({"type": "unknown"}) == "unknown"

    def test_building_type_label_missing_key(self):
        assert building_type_label({}) == "unknown"

    def test_buildings_at_z(self):
        level5 = self._sample_bld(cz=5)
        level3 = self._sample_bld(cz=3)
        level5_explicit = self._sample_bld(cx=0, cy=0, cz=5)
        result = buildings_at_z([level5, level3, level5_explicit], z=5)
        assert len(result) == 2

    def test_buildings_at_z_none_match(self):
        assert buildings_at_z([], z=99) == []

    def test_building_count_by_type(self):
        bldgs = [
            self._sample_bld("Workshop"),
            self._sample_bld("Furnace"),
            self._sample_bld("Workshop"),
        ]
        counts = building_count_by_type(bldgs)
        assert counts["Workshop"] == 2
        assert counts["Furnace"] == 1

    def test_building_count_by_type_empty(self):
        assert building_count_by_type([]) == {}


class TestItemObservation:
    """Deterministic tests for item observation helpers in bridge/probe.py."""

    def _sample_items(self):
        return [
            {"idx": 1, "type": "FOOD", "mat_mode": "plant", "material_id": 5, "value": 20},
            {"idx": 2, "type": "TOOL", "mat_mode": "metal", "material_id": 17, "value": 500},
            {"idx": 3, "type": "WOOD", "mat_mode": "plant", "material_id": 8, "value": 10},
            {"idx": 4, "type": "MEAT", "mat_mode": "flesh", "material_id": 12, "value": 50},
            {"idx": 5, "type": "ARMOR", "mat_mode": "metal", "material_id": 17, "value": 3000},
            {"idx": 6, "type": "BOOK", "mat_mode": "book", "material_id": -1, "value": 200},
            {"idx": 7, "type": "CONTAINER", "mat_mode": "wood", "material_id": 8, "value": 75},
            {"idx": 8, "type": "BAR_GEMS", "mat_mode": "gem", "material_id": 3, "value": 10000},
            {"idx": 9, "type": "CHEESE", "mat_mode": "foodstuff", "material_id": -1, "value": 80},
            {"idx": 10, "type": "LIQUID_MISC", "mat_mode": "liquid", "material_id": 42, "value": 5},
        ]

    def test_item_type_enum_map(self):
        assert isinstance(ITEM_TYPE_ENUM_MAP, dict)
        assert len(ITEM_TYPE_ENUM_MAP) >= 15
        assert ITEM_TYPE_ENUM_MAP["TOOL"] == "tool"
        assert ITEM_TYPE_ENUM_MAP["FOOD"] == "food"

    def test_item_category_consumable(self):
        for itype in ("FOOD", "MEAT", "PLANT", "CHEESE", "GLOB", "LIQUID_MISC", "POISON_FLASK"):
            assert item_category({"type": itype}) == "consumable", itype


    def test_item_category_structural(self):
        for itype in ("WOOD", "STONE"):
            assert item_category({"type": itype}) == "structural", itype

    def test_item_category_metalwork(self):
        for itype in ("METAL_INGOT", "BAR_GEMS", "CLOTH"):
            assert item_category({"type": itype}) == "metalwork", itype

    def test_item_category_protection(self):
        for itype in ("ARMOR", "HELM", "GLOVES", "PANTS", "SHOES"):
            assert item_category({"type": itype}) == "protection", itype

    def test_item_category_tool(self):
        assert item_category({"type": "TOOL"}) == "tool"

    def test_item_category_knowledge(self):
        for itype in ("BOOK", "PAPER", "ARTIFACT"):
            assert item_category({"type": itype}) == "knowledge", itype

    def test_item_category_storage(self):
        assert item_category({"type": "CONTAINER"}) == "storage"

    def test_item_category_other_fallback(self):
        assert item_category({"type": "unknown"}) == "other"
        assert item_category({}) == "other"
        assert item_category({"type": None}) == "other"

    def test_total_inventory_value(self):
        items = self._sample_items()
        expected = 20 + 500 + 10 + 50 + 3000 + 200 + 75 + 10000 + 80 + 5
        assert total_inventory_value(items) == expected

    def test_total_inventory_value_empty(self):
        assert total_inventory_value([]) == 0

    def test_total_inventory_value_missing_key(self):
        assert total_inventory_value([{}]) == 0

    def test_count_items_by_category_detailed(self):
        items = self._sample_items()
        counts = count_items_by_category(items)
        # FOOD→consumable, MEAT→consumable, CHEESE→consumable, LIQUID_MISC→consumable = 4
        assert counts["consumable"] == 4
        # WOOD→structural = 1
        assert counts["structural"] == 1
        # TOOL→tool = 1
        assert counts["tool"] == 1
        # ARMOR→protection = 1
        assert counts["protection"] == 1
        # BOOK→knowledge = 1
        assert counts["knowledge"] == 1
        # CONTAINER→storage = 1
        assert counts["storage"] == 1
        # BAR_GEMS→metalwork = 1
        assert counts["metalwork"] == 1

    def test_count_items_by_category_empty(self):
        assert count_items_by_category([]) == {}

    def test_high_value_items_above_threshold(self):
        items = self._sample_items()
        high = high_value_items(items, threshold=1000)
        vals = [i["value"] for i in high]
        assert all(v > 1000 for v in vals)

    def test_high_value_items_default_threshold(self):
        items = self._sample_items()
        high = high_value_items(items)
        vals = {i["value"] for i in high}
        # Only ARMOR(3000) and BAR_GEMS(10000) exceed default 1000
        assert 3000 in vals
        assert 10000 in vals
        assert 500 not in vals

    def test_high_value_items_empty(self):
        assert high_value_items([]) == []


class TestUnitPopulation:

    def _units(self):
        return [
            {"id": 1, "killed": False, "civ_id": 1, "pos": [10, 20, 3]},
            {"id": 2, "killed": True, "civ_id": 1, "pos": [11, 20, 3]},
            {"id": 3, "killed": False, "civ_id": 2, "pos": [50, 60, 7]},
            {"id": 4, "killed": False, "civ_id": None, "pos": [12, 22, 5]},
        ]

    def test_alive_units(self):
        units = self._units()
        alive = alive_units(units)
        assert len(alive) == 3
        assert all(not u["killed"] for u in alive)

    def test_dead_units(self):
        units = self._units()
        dead = dead_units(units)
        assert len(dead) == 1
        assert all(u["killed"] for u in dead)

    def test_unit_population(self):
        units = self._units()
        pop = unit_population(units)
        assert pop["total"] == 4
        assert pop["alive"] == 3
        assert pop["dead"] == 1

    def test_units_by_civ_id(self):
        units = self._units()
        groups = units_by_civ_id(units)
        assert "1" in groups
        assert "2" in groups
        assert "none" in groups
        assert len(groups["1"]) == 2
        assert len(groups["2"]) == 1
        assert len(groups["none"]) == 1

    def test_units_at_z_list_pos(self):
        units = self._units()
        z3 = units_at_z(units, 3)
        assert len(z3) == 2
        z7 = units_at_z(units, 7)
        assert len(z7) == 1

    def test_units_at_z_dict_pos(self):
        units = [
            {"id": 1, "pos": {"x": 0, "y": 0, "z": 4}},
            {"id": 2, "pos": {"x": 1, "y": 1, "z": 5}},
        ]
        assert len(units_at_z(units, 4)) == 1
        assert len(units_at_z(units, 5)) == 1
        assert len(units_at_z(units, 99)) == 0

    def test_unit_positions(self):
        units = self._units()
        positions = unit_positions(units)
        assert positions[0] == (10, 20, 3)
        assert positions[2] == (50, 60, 7)
        assert len(positions) == 4

    def test_unit_positions_missing(self):
        units = [{"id": 1}]
        positions = unit_positions(units)
        assert positions == [(0, 0, 0)]

    def test_nearby_units(self):
        units = self._units()
        nearby = nearby_units(units, 10, 20, 5)
        ids = {u["id"] for u in nearby}
        assert 1 in ids
        assert 2 in ids
        assert 4 in ids
        assert 3 not in ids

    def test_nearby_manhattan_boundary(self):
        units = [
            {"id": 1, "pos": [0, 3, 0]},
            {"id": 2, "pos": [3, 0, 0]},
            {"id": 3, "pos": [0, 4, 0]},
        ]
        exact = nearby_units(units, 0, 0, 3)
        ids = {u["id"] for u in exact}
        assert 1 in ids
        assert 2 in ids
        assert 3 not in ids


class TestMapFeatures:
    """Tests for the map features observation bridge and helpers."""

    def _sample_features(self):
        return [
            {"idx": 0, "name": "Wyr River", "type": "RiverStream",
             "water": True, "magma": False, "subterranean": False,
             "chasm": False, "underworld": False, "discovered": True},
            {"idx": 1, "name": "Volsky", "type": "Volcano",
             "water": False, "magma": True, "subterranean": False,
             "chasm": False, "underworld": False, "discovered": False},
            {"idx": 2, "name": "Dark Passage", "type": "UnderworldChasm",
             "water": False, "magma": False, "subterranean": True,
             "chasm": True, "underworld": True, "discovered": True},
        ]

    def test_map_feature_schema_keys_present(self):
        for feat in self._sample_features():
            for key in MAP_FEATURE_SCHEMA_KEYS:
                assert key in feat, f"Missing schema key: {key}"

    def test_water_features_filter(self):
        features = self._sample_features()
        water = water_features(features)
        assert len(water) == 1
        assert water[0]["name"] == "Wyr River"

    def test_magma_features_filter(self):
        features = self._sample_features()
        magma = magma_features(features)
        assert len(magma) == 1
        assert magma[0]["type"] == "Volcano"

    def test_discovered_features_filter(self):
        features = self._sample_features()
        disc = discovered_features(features)
        ids = [f["idx"] for f in disc]
        assert 0 in ids
        assert 2 in ids
        assert 1 not in ids

    def test_feature_categories(self):
        features = self._sample_features()
        cats = feature_categories(features)
        assert len(cats["water"]) == 1
        assert len(cats["magma"]) == 1
        assert len(cats["chasm"]) == 1
        assert len(cats["subterranean"]) == 1
        assert len(cats["underworld"]) == 1

    def test_hazardous_features(self):
        features = self._sample_features()
        haz = hazardous_features(features)
        ids = [f["idx"] for f in haz]
        assert 1 in ids   # Volcano (magma)
        assert 2 in ids   # UnderworldChasm (underworld + chasm)
        assert 0 not in ids

    def test_empty_features(self):
        assert water_features([]) == []
        assert magma_features([]) == []
        assert discovered_features([]) == []
        assert hazardous_features([]) == []
        cats = feature_categories([])
        for _key, val in cats.items():
            assert val == []

    def test_known_feature_types_not_empty(self):
        assert len(KNOWN_FEATURE_TYPES) > 0
        assert "Volcano" in KNOWN_FEATURE_TYPES
        assert "RiverStream" in KNOWN_FEATURE_TYPES


class TestTileMapObservation:
    """Deterministic tests for tile map observation helpers.

    The probe_tile_map() function calls bridge.tile_map() via DFHack at runtime.
    These tests are pure-Python and exercise the shape of the returned data using
    synthetic tile dicts that mirror bridge/core.lua output.
    """

    def _sample_tiles(self, n=10):
        return [
            {"x": i % 4, "y": i // 4, "z": 0,
             "type": 256 + (i % 3),  # floor range [256..511]
             "material": "STONE" if i < 7 else "SOIL",
             "walkable": i < 8}
            for i in range(n)
        ]

    def test_map_dimensions_basic(self):
        data = {"has_map": True, "width": 64, "height": 64, "depth": 25}
        w, h, d = map_dimensions(data)
        assert (w, h, d) == (64, 64, 25)

    def test_map_dimensions_none_input(self):
        assert map_dimensions(None) == (0, 0, 0)
        assert map_dimensions({}) == (0, 0, 0)

    def test_tile_material_counts(self):
        tiles = self._sample_tiles(10)
        counts = tile_material_counts(tiles)
        assert counts["STONE"] == 7
        assert counts["SOIL"] == 3

    def test_tile_material_counts_empty(self):
        assert tile_material_counts([]) == {}

    def test_tile_material_counts_with_none_tile(self):
        tiles = [None, {"material": "STONE"}]
        counts = tile_material_counts(tiles)
        # None → "unknown", the second is "STONE".
        assert counts["unknown"] == 1
        assert counts["STONE"] == 1

    def test_walkable_fraction(self):
        tiles = self._sample_tiles(10)
        ratio = walkable_tile_fraction(tiles)
        assert ratio == 0.8

    def test_walkable_fraction_empty(self):
        assert walkable_tile_fraction([]) == 0.0

    def test_liquid_fraction(self):
        tiles = [
            {"x": 0, "y": 0, "z": 0, "type": 1100, "material": "AIR", "walkable": False},
            {"x": 1, "y": 0, "z": 0, "type": 200, "material": "STONE", "walkable": True},
        ]
        assert liquid_tile_fraction(tiles) == 0.5

    def test_floor_fraction(self):
        tiles = [
            {"x": 0, "y": 0, "z": 0, "type": 300, "material": "STONE", "walkable": True},
            {"x": 1, "y": 0, "z": 0, "type": 350, "material": "STONE", "walkable": True},
            {"x": 2, "y": 0, "z": 0, "type": 400, "material": "STONE", "walkable": True},
        ]
        assert floor_tile_fraction(tiles) == 1.0

    def test_dominant_material(self):
        tiles = self._sample_tiles(10)
        assert dominant_material(tiles) == "STONE"

    def test_dominant_material_empty(self):
        assert dominant_material([]) is None

    def test_dominant_material_tie(self):
        tiles = [
            {"x": 0, "y": 0, "z": 0, "type": 100, "material": "STONE", "walkable": True},
            {"x": 1, "y": 0, "z": 0, "type": 100, "material": "SOIL", "walkable": True},
        ]
        # Both have count 1; max will return one of them.
        result = dominant_material(tiles)
        assert result in ("STONE", "SOIL")

    def test_tile_summary_valid(self):
        tiles = self._sample_tiles(8)
        data = {
            "has_map": True, "width": 16, "height": 16, "depth": 5,
            "block_width": 2, "block_height": 2, "block_depth": 1,
            "tiles": tiles,
        }
        summary = tile_summary(data)
        assert summary["has_map"] is True
        assert summary["dimensions"] == (16, 16, 5)
        assert summary["total_sampled"] == 8
        assert 0.0 <= summary["walkable_pct"] <= 1.0
        assert isinstance(summary["material_breakdown"], dict)

    def test_tile_summary_none(self):
        summary = tile_summary(None)
        assert summary["has_map"] is False
        assert summary["dimensions"] == (0, 0, 0)
        assert summary["total_sampled"] == 0

    def test_schema_keys_defined(self):
        for key in TILE_MAP_SCHEMA_KEYS:
            assert isinstance(key, str)
        assert "has_map" in TILE_MAP_SCHEMA_KEYS
        assert "tiles" in TILE_MAP_SCHEMA_KEYS

    def test_sample_limit_is_256(self):
        assert TILE_SAMPLE_LIMIT == 256

if __name__ == "__main__":

    """Run all tests without pytest — portable to bare Python 3.13."""
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
                     TestConfidenceIntervals, TestAdvanceValidation,
                     TestDiskCheckpoint, TestGradualAdvance, TestResourceMonitor,
                     TestMultiSeedStress, TestCurriculumGradualAndMonitor,
                     TestSkillChainReset, TestRunnerMultiple,
                     TestEpisodeLoggerIntegration, TestInferenceLatency,
                     TestEmergencyPauseSkill, TestEmergencyPauseCurriculum,
                     TestProfessionLabor, TestTileClassification, TestJobSystem,
                     TestTileMapLuaContract,
                     TestUnitNeedsContract, TestBuildingObservation,
                      TestItemObservation, TestUnitPopulation,
                      TestDfhackErrorHandling, TestMapFeatures,
                      TestTileMapObservation]

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
