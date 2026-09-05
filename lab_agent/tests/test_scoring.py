"""Unit tests for the statistical scorer, grounded in the 2026-07-24 calibration
data (K=8 no-op episodes). Verifies: no-op < good, σ≈0 inputs give tight CIs and
trustworthy verdicts, and near-ties are correctly flagged UNTRUSTWORTHY."""

from bonsai_lab_agent.scoring import (
    EpisodeObs, raw_components, normalized_score, aggregate, compare,
    TICKS_PER_DAY,
)

H30 = 30 * TICKS_PER_DAY  # 36000 ticks

# T0 (pinned save): 7 dwarves, everything fresh.
T0 = EpisodeObs(abs_tick=2016801, cohort_alive=7, cohort_size=7, hunger_sum=7,
                thirst_sum=7, stress_danger=0, food_count=12, drink_count=12,
                buildings=1, dug_tiles=0, workorders_done=0)

# No-op at 30 days — EXACT calibration numbers (hunger_sum=252007 identical across
# all 8 episodes; thirst ~104000; food/drink/buildings unchanged; no dig/orders).
NOOP_H30 = EpisodeObs(abs_tick=2052801, cohort_alive=7, cohort_size=7,
                      hunger_sum=252007, thirst_sum=104000, stress_danger=0,
                      food_count=12, drink_count=12, buildings=1,
                      dug_tiles=0, workorders_done=0)

# A competent controller: dwarves kept fed/watered, food/drink produced, digging
# and workshops built, workorders completed.
GOOD_H30 = EpisodeObs(abs_tick=2052801, cohort_alive=7, cohort_size=7,
                      hunger_sum=70000, thirst_sum=50000, stress_danger=0,
                      food_count=30, drink_count=30, buildings=5,
                      dug_tiles=150, workorders_done=15)


def _noop_ref():
    noop = raw_components(NOOP_H30, T0, H30)["composite"]
    ref = raw_components(GOOD_H30, T0, H30)["composite"]
    return noop, ref


def test_good_beats_noop_raw():
    noop = raw_components(NOOP_H30, T0, H30)["composite"]
    good = raw_components(GOOD_H30, T0, H30)["composite"]
    assert good > noop, f"good {good:.3f} should beat no-op {noop:.3f}"


def test_survival_gate_zeroes_on_wipe():
    wipe = EpisodeObs(abs_tick=2052801, cohort_alive=0, cohort_size=7, hunger_sum=0,
                      thirst_sum=0, stress_danger=0, food_count=99, drink_count=99,
                      buildings=9, dug_tiles=999, workorders_done=99)
    # even with huge development, a wiped fort scores 0 (survival is a hard gate)
    assert raw_components(wipe, T0, H30)["composite"] == 0.0


def test_normalized_endpoints():
    noop, ref = _noop_ref()
    assert normalized_score(NOOP_H30, T0, H30, noop, ref) == 0.0
    assert normalized_score(GOOD_H30, T0, H30, noop, ref) == 1.0


def test_sigma_zero_inputs_give_trustworthy_verdict():
    """Calibration proved the scored observables are σ≈0 across episodes, so no-op
    scores are identical -> MAD=0, CI half-width 0 -> any real delta is trustworthy."""
    noop, ref = _noop_ref()
    # 8 identical no-op episodes (the actual calibration outcome for scored fields)
    noop_scores = [normalized_score(NOOP_H30, T0, H30, noop, ref)] * 8
    # 8 good episodes with tiny jitter (thirst wobbled ~0.8% in calibration)
    good_scores = [normalized_score(
        EpisodeObs(**{**GOOD_H30.__dict__, "thirst_sum": 50000 + d}), T0, H30, noop, ref)
        for d in (-400, -200, -100, 0, 100, 200, 300, 400)]
    a = aggregate(good_scores)
    b = aggregate(noop_scores)
    assert b.ci_half == 0.0                 # no-op perfectly stable
    assert a.median > b.median
    verdict = compare(a, b, "good", "noop")
    assert verdict.trustworthy and verdict.winner == "good", verdict.reason


def test_near_tie_flagged_untrustworthy():
    """Two policies within the noise band must be flagged UNTRUSTWORTHY (raise K)."""
    a = aggregate([0.50, 0.55, 0.45, 0.52, 0.48])   # wide spread
    b = aggregate([0.51, 0.46, 0.56, 0.49, 0.53])
    v = compare(a, b)
    assert not v.trustworthy, f"should be a tie: {v.reason}"


def test_too_few_runs_untrustworthy():
    a = aggregate([0.9, 0.9])
    b = aggregate([0.1, 0.1])
    assert not compare(a, b).trustworthy  # n<3 -> cannot trust


def test_comfort_is_not_a_quantity_divided_by_itself():
    """The hunger and thirst timers count ticks since the dwarf last ate or drank.

    _sat used to divide the per-dwarf mean by the EPISODE HORIZON, which is the same
    quantity for anyone who did not happen to eat during the episode. Measured on
    ourfort16-final at horizon 3600: hunger_sum went 0 -> 25200 across 7 citizens, a mean
    of exactly 3600, so satisfaction was exactly 1 - 3600/3600 = 0. Twenty percent of the
    metric's weight was arithmetically zero rather than conditionally zero, on a fort
    where every dwarf was perfectly fed.
    """
    from bonsai_lab_agent.scoring import (COMFORT_HUNGER_CEILING, COMFORT_THIRST_CEILING,
                                          _sat)

    # The exact episode that exposed it must now score as the healthy fort it was.
    assert _sat(25200, 7, COMFORT_HUNGER_CEILING) > 0.9

    # Measured on region3-lab: 136 citizens, none in distress, hunger p50 21190.
    assert 0.5 < _sat(3104826, 136, COMFORT_HUNGER_CEILING) < 0.8

    # Monotone, and floored at the worst a working fort was ever seen to show.
    assert _sat(0, 7, COMFORT_HUNGER_CEILING) == 1.0
    assert _sat(COMFORT_HUNGER_CEILING * 7, 7, COMFORT_HUNGER_CEILING) == 0.0
    assert _sat(COMFORT_HUNGER_CEILING * 70, 7, COMFORT_HUNGER_CEILING) == 0.0
    assert (_sat(10_000, 7, COMFORT_HUNGER_CEILING)
            > _sat(20_000, 7, COMFORT_HUNGER_CEILING))

    # Thirst is a tighter ceiling than hunger, as the measurement showed.
    assert COMFORT_THIRST_CEILING < COMFORT_HUNGER_CEILING


def test_comfort_ceilings_are_measured_not_guessed():
    """These are observed ceilings of a functioning fort, not DF's internal threshold.

    This build of DFHack exposes no isHungry/isThirsty/isStarving/isDehydrated, so the
    real threshold is unmeasured. The constants are named for what they are; guessing a
    threshold from folklore is how this file came to carry TICKS_PER_DAY = 86400
    "verified against position.lua".
    """
    import inspect

    from bonsai_lab_agent import scoring

    assert scoring.COMFORT_HUNGER_CEILING == 64_021   # max seen on a fort in no distress
    assert scoring.COMFORT_THIRST_CEILING == 35_167
    source = inspect.getsource(scoring)
    assert "region3-lab" in source, "the measurement's provenance must stay in the file"
