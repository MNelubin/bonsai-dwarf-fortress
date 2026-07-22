from bonsai_control.orchestrator import failure_fingerprint, submission_hash, summary_tail


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


def test_submission_hash_is_canonical_and_commit_sensitive():
    manifest_a = {"protocol": "jsonl-v1", "kind": "python_callable"}
    manifest_b = {"kind": "python_callable", "protocol": "jsonl-v1"}
    assert submission_hash("a" * 40, manifest_a) == submission_hash("a" * 40, manifest_b)
    assert submission_hash("a" * 40, manifest_a) != submission_hash("b" * 40, manifest_a)


def test_summary_tail_accepts_structured_experiment_result():
    rendered = summary_tail({"score": 0.75, "live_df": {"ready": True}})
    assert '"score": 0.75' in rendered
    assert '"ready": true' in rendered
