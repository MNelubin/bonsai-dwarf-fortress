from datetime import datetime, timedelta, timezone

from bonsai_control.orchestrator import (
    failure_fingerprint,
    repeated_failure_epoch_count,
    should_start_cooldown,
    submission_hash,
    summary_tail,
)


def test_failure_fingerprint_ignores_ids_paths_and_numbers():
    first = (
        "File /srv/bonsai-agent/runs/123/repo/a.py line 19 job "
        "de305d54-75b4-431b-adb2-eb6b9e546014 failed after 1600 seconds"
    )
    second = (
        "File /tmp/other/999/repo/a.py line 42 job "
        "550e8400-e29b-41d4-a716-446655440000 failed after 900 seconds"
    )
    assert failure_fingerprint(first) == failure_fingerprint(second)


def test_patch_protocol_variants_share_one_terminal_failure_epoch():
    first = "coding graph proposal does not change any file"
    second = "edit 2 cannot create over existing file tests/test_x.py"
    third = "edit 1 old text occurs 0 times instead of once: player/policy.py"
    assert failure_fingerprint(first) == failure_fingerprint(second) == failure_fingerprint(third)


def test_incomplete_promotion_shape_has_stable_failure_epoch():
    first = '{"missing_requirements": ["missing_executable_change"]}'
    second = '{"missing_requirements": ["missing_public_test_change"], "changed_paths": ["x"]}'
    assert failure_fingerprint(first) == failure_fingerprint(second)


def test_submission_hash_is_canonical_and_commit_sensitive():
    manifest_a = {"protocol": "jsonl-v1", "kind": "python_callable"}
    manifest_b = {"kind": "python_callable", "protocol": "jsonl-v1"}
    assert submission_hash("a" * 40, manifest_a) == submission_hash("a" * 40, manifest_b)
    assert submission_hash("a" * 40, manifest_a) != submission_hash("b" * 40, manifest_a)


def test_summary_tail_accepts_structured_experiment_result():
    rendered = summary_tail({"score": 0.75, "live_df": {"ready": True}})
    assert '"score": 0.75' in rendered
    assert '"ready": true' in rendered


def test_cooldown_rearms_only_after_a_new_matching_failure():
    state_updated = datetime.now(timezone.utc)
    assert not should_start_cooldown("same", state_updated - timedelta(seconds=1), state_updated)
    assert should_start_cooldown("same", state_updated + timedelta(seconds=1), state_updated)
    assert not should_start_cooldown(None, state_updated + timedelta(seconds=1), state_updated)


def test_repeated_failure_epoch_survives_one_cooldown_then_escalates():
    assert repeated_failure_epoch_count(None, 0, "same") == 3
    assert repeated_failure_epoch_count("same", 3, "same") == 6
    assert repeated_failure_epoch_count("old", 99, "new") == 3
