from bonsai_control.cycle_policy import choose_cycle


def decide(**overrides):
    values = dict(
        has_promoted_discovery=True,
        last_job_type="coding_cycle",
        last_job_state="completed",
        last_job_changed=True,
        promoted_coding_since_discovery=1,
    )
    values.update(overrides)
    return choose_cycle(**values)


def test_discovery_bootstraps_the_knowledge_library():
    assert decide(has_promoted_discovery=False).job_type == "discovery_cycle"


def test_fresh_discovery_is_followed_by_coding():
    assert decide(last_job_type="discovery_cycle").job_type == "coding_cycle"


def test_empty_coding_retries_with_failure_handoff():
    decision = decide(last_job_state="rejected", last_job_changed=False)
    assert decision.job_type == "coding_cycle"
    assert "retry" in decision.reason


def test_maintenance_cancelled_coding_is_retried():
    assert decide(last_job_state="cancelled", last_job_changed=None).job_type == "coding_cycle"


def test_three_promoted_code_cycles_trigger_refresh():
    assert decide(promoted_coding_since_discovery=3).job_type == "discovery_cycle"
