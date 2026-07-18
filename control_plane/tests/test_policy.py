from bonsai_control.policy import PromotionEvidence, evaluate_promotion


def good(**overrides):
    values = dict(
        changed_paths=("player/policy.py", "tests/test_policy.py"),
        unit_tests_passed=True,
        bridge_smoke_passed=True,
        short_eval_passed=True,
        full_eval_passed=True,
        median_score_delta=1.0,
        worst_quantile_delta=0.0,
        resource_ratio=1.05,
        fast_forward=True,
    )
    values.update(overrides)
    return PromotionEvidence(**values)


def test_good_candidate_is_automatically_promotable():
    decision = evaluate_promotion(good())
    assert decision.allowed
    assert decision.reasons == ()


def test_control_plane_change_is_rejected():
    decision = evaluate_promotion(good(changed_paths=("control_plane/bonsai_control/main.py",)))
    assert not decision.allowed
    assert "protected path" in decision.reasons[0]


def test_worst_quantile_regression_is_rejected():
    decision = evaluate_promotion(good(worst_quantile_delta=-0.01))
    assert not decision.allowed
    assert "worst quantile regressed" in decision.reasons


def test_non_fast_forward_is_rejected():
    decision = evaluate_promotion(good(fast_forward=False))
    assert not decision.allowed
    assert "not a fast-forward" in decision.reasons[-1]

