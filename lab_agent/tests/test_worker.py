import json
import os
import subprocess
from pathlib import Path

import pytest

from bonsai_lab_agent.quality_gate import evaluate_python_quality
from bonsai_lab_agent.probe_guard import ensure_runtime_ready, run_guarded_probe

from bonsai_lab_agent.worker import (
    Config,
    apply_coding_graph_edits,
    bounded_ollama_chat,
    cleanup_generated_runtime_files,
    coding_graph_decision,
    df_runtime_process_ids,
    discovery_needs_synthesis,
    compact_phase_checkpoint,
    compact_discovery_trace,
    harness_environment,
    has_executable_candidate_change,
    persist_cross_job_wip,
    model_response_content,
    provider_model_id,
    restore_cross_job_wip,
    structured_model_request,
    synthesize_discovery,
    trace_ended_with_degenerate_stop,
    trace_has_live_game_probe,
    trace_latest_input_tokens,
    trace_phase_latest_input_tokens,
    trace_phase_tool_use_count,
    unique_fuzzy_edit_span,
    unique_minimal_delta_span,
    unique_whitespace_edit_span,
    serializable_working_tree_paths,
    select_coding_context,
    supervised_df_runtime_process_ids,
    validate_coding_candidate,
    working_tree_fingerprint,
    working_tree_paths,
    write_discovery_bundle,
)


def test_openai_structured_request_uses_high_reasoning_without_token_limit():
    config = object.__new__(Config)
    object.__setattr__(config, "model", "k2think/MBZUAI-IFM/K2-Think-v2")
    object.__setattr__(config, "model_api_style", "openai")
    object.__setattr__(config, "model_reasoning_effort", "high")
    payload = json.loads(
        structured_model_request(
            config,
            [{"role": "user", "content": "return JSON"}],
            {"type": "object", "properties": {"ok": {"type": "boolean"}}},
            schema_name="canary",
            ollama_num_ctx=1024,
            ollama_num_predict=64,
        )
    )
    assert payload["model"] == "MBZUAI-IFM/K2-Think-v2"
    assert payload["reasoning_effort"] == "high"
    assert payload["response_format"]["type"] == "json_schema"
    assert not any("max" in key or "predict" in key for key in payload)
    assert provider_model_id(config) == "MBZUAI-IFM/K2-Think-v2"


def test_openai_structured_request_can_lower_only_repair_reasoning_without_token_limit():
    config = object.__new__(Config)
    object.__setattr__(config, "model", "k2think/MBZUAI-IFM/K2-Think-v2")
    object.__setattr__(config, "model_api_style", "openai")
    object.__setattr__(config, "model_reasoning_effort", "high")
    payload = json.loads(
        structured_model_request(
            config,
            [{"role": "user", "content": "repair"}],
            {"type": "object", "properties": {"ok": {"type": "boolean"}}},
            schema_name="repair",
            ollama_num_ctx=1024,
            ollama_num_predict=64,
            reasoning_effort="medium",
        )
    )
    assert payload["reasoning_effort"] == "medium"
    assert not any("max" in key or "predict" in key for key in payload)


def test_openai_response_content_is_separate_from_reasoning():
    config = object.__new__(Config)
    object.__setattr__(config, "model_api_style", "openai")
    response = {
        "choices": [
            {"message": {"reasoning": "private reasoning", "content": "  {\"ok\": true}\n"}}
        ]
    }
    assert model_response_content(config, response) == '{"ok": true}'


def test_openai_empty_content_reports_finish_reason_reasoning_and_usage():
    config = object.__new__(Config)
    object.__setattr__(config, "model_api_style", "openai")
    response = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"reasoning_content": "private reasoning", "content": None},
            }
        ],
        "usage": {"completion_tokens": 4096},
    }
    with pytest.raises(
        RuntimeError,
        match=r"finish_reason='length'.*reasoning_chars=17.*completion_tokens",
    ):
        model_response_content(config, response)


class HeartbeatApi:
    def heartbeat(self, job: dict[str, object], progress: dict[str, object]) -> None:
        pass

    def worker_heartbeat(self, status: str, job_id: str, progress: dict[str, object]) -> None:
        pass


def test_bounded_ollama_chat_kills_a_process_past_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_curl = tmp_path / "fake-curl"
    fake_curl.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    fake_curl.chmod(0o755)
    config = object.__new__(Config)
    object.__setattr__(config, "phase_timeout", 0)
    object.__setattr__(config, "model", "ollama/test")
    object.__setattr__(config, "ollama_url", "http://127.0.0.1:1")
    clock = {"value": 0.0}

    def monotonic() -> float:
        clock["value"] += 70.0
        return clock["value"]

    monkeypatch.setattr("bonsai_lab_agent.worker.time.monotonic", monotonic)
    monkeypatch.setattr("bonsai_lab_agent.worker.time.sleep", lambda _seconds: None)
    with pytest.raises(TimeoutError, match="process deadline"):
        bounded_ollama_chat(
            config,
            HeartbeatApi(),  # type: ignore[arg-type]
            {"id": "job"},
            tmp_path,
            "coding_graph_draft_1",
            b"{}",
            0.0,
            curl_bin=str(fake_curl),
        )
    assert not list(tmp_path.glob(".*.json"))
    assert not list(tmp_path.glob(".*.log"))


def test_bounded_model_error_includes_provider_response_body(tmp_path: Path):
    fake_curl = tmp_path / "fake-curl"
    fake_curl.write_text(
        "#!/bin/sh\nprintf '{\"error\":\"provider overloaded\"}'\n"
        "printf 'curl: HTTP 500' >&2\nexit 22\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    config = object.__new__(Config)
    object.__setattr__(config, "phase_timeout", 120)
    object.__setattr__(config, "model", "k2think/test")
    object.__setattr__(config, "model_api_url", "http://127.0.0.1:1")

    with pytest.raises(RuntimeError, match="provider overloaded"):
        bounded_ollama_chat(
            config,
            HeartbeatApi(),  # type: ignore[arg-type]
            {"id": "job"},
            tmp_path,
            "discovery_structured_synthesis",
            b"{}",
            0.0,
            curl_bin=str(fake_curl),
        )


def test_discovery_synthesis_uses_medium_reasoning_without_output_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = init_repo(tmp_path)
    (repo / "knowledge").mkdir()
    (repo / "knowledge" / "INDEX.md").write_text("# Knowledge\n", encoding="utf-8")
    trace = tmp_path / "opencode-trace.jsonl"
    trace.write_text('{"probe":"DFHack 53.15-r2 on DF 53.15"}\n', encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_request(*_args, **kwargs):
        captured.update(kwargs)
        return b"{}"

    note = "DF 53.15 / DFHack 53.15-r2\n\nVERIFIED: bounded probe evidence.\n" + (
        "Evidence and implication for reset observe act advance.\n" * 12
    )
    bundle = {
        "note_path": "probe-episode-backend.md",
        "index_markdown": "# Knowledge\n\n[Episode backend](dfhack/probe-episode-backend.md)\n",
        "note_markdown": note,
    }
    response = {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(bundle)}}]
    }
    monkeypatch.setattr("bonsai_lab_agent.worker.structured_model_request", fake_request)
    monkeypatch.setattr(
        "bonsai_lab_agent.worker.bounded_ollama_chat",
        lambda *_args, **_kwargs: json.dumps(response).encode(),
    )
    config = object.__new__(Config)
    object.__setattr__(config, "model_api_style", "openai")
    object.__setattr__(config, "model", "k2think/MBZUAI-IFM/K2-Think-v2")
    target = synthesize_discovery(
        config,
        HeartbeatApi(),  # type: ignore[arg-type]
        {"id": "job"},
        repo,
        trace,
        0.0,
    )

    assert captured["reasoning_effort"] == "medium"
    assert target == "dfhack/probe-episode-backend.md"


def test_discovery_trace_compaction_deduplicates_large_tool_metadata(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    huge_output = "x" * 100_000 + "\nBONSAI_PROBE_RESULT {\"exit\":0}\n"
    events = [
        {
            "type": "runtime_readiness",
            "ready": True,
            "output": "DFHack 53.15-r2 on DF 53.15",
        },
        {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "bonsai-df-probe help lua"},
                    "output": huge_output,
                    "metadata": {"output": huge_output},
                },
            },
        },
        {"type": "text", "part": {"text": "VERIFIED focused conclusion"}},
    ]
    trace.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    compact = compact_discovery_trace(trace)
    assert len(compact) <= 24_000
    assert "BONSAI_PROBE_RESULT" in compact
    assert "VERIFIED focused conclusion" in compact
    assert compact.count("BONSAI_PROBE_RESULT") == 1
    assert len(compact) < len(trace.read_text(encoding="utf-8")) // 10


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "baseline"], check=True, capture_output=True)
    return repo


def test_discovery_requires_changed_index_and_focused_note(tmp_path: Path):
    repo = init_repo(tmp_path)
    assert discovery_needs_synthesis(repo) is True
    (repo / "knowledge" / "dfhack").mkdir(parents=True)
    (repo / "knowledge" / "INDEX.md").write_text("[Bridge](dfhack/bridge.md)\n", encoding="utf-8")
    (repo / "knowledge" / "dfhack" / "bridge.md").write_text("# Bridge\n", encoding="utf-8")
    assert discovery_needs_synthesis(repo) is False
    assert working_tree_paths(repo) == {"knowledge/INDEX.md", "knowledge/dfhack/bridge.md"}


def test_discovery_repair_is_required_for_changes_outside_knowledge(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "knowledge" / "dfhack").mkdir(parents=True)
    (repo / "knowledge" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    (repo / "knowledge" / "dfhack" / "bridge.md").write_text("# Bridge\n", encoding="utf-8")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    assert discovery_needs_synthesis(repo) is True


def test_structured_discovery_writes_validated_bundle(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = write_discovery_bundle(
        repo,
        {
            "note_path": "bridge-primitives.md",
            "index_markdown": "# Index  \n\n[Bridge](dfhack/bridge-primitives.md)  \n" + "context " * 30,
            "note_markdown": (
                "# Bridge primitives  \n\n"
                "VERIFIED — Dwarf Fortress 53.15 with DFHack 53.15-r2.\n\n"
                "INFERRED — bridge implication.\n\nOPEN — controlled probe remains.\n\n"
                + "Source and recommendation. " * 30
            ),
        },
    )
    assert target == "dfhack/bridge-primitives.md"
    assert discovery_needs_synthesis(repo) is False
    assert subprocess.run(
        ["git", "-C", str(repo), "diff", "--check"],
        capture_output=True,
        text=True,
    ).returncode == 0


def write_trace(path: Path, events: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def test_phase_tool_budget_does_not_count_prior_phase(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    events = [{"type": "tool_use"} for _ in range(16)]
    events.append({"type": "harness_phase", "phase": "live_game_probe_recovery"})
    events.extend({"type": "tool_use"} for _ in range(3))
    write_trace(trace, events)
    assert trace_phase_tool_use_count(trace, "opencode") == 16
    assert trace_phase_tool_use_count(trace, "live_game_probe_recovery") == 3


def test_live_probe_requires_completed_trusted_wrapper_result(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [{
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 20 -- /srv/df-bonsai/current/dfhack-run status"},
                    "metadata": {
                        "output": 'probe complete\nBONSAI_PROBE_RESULT {"exit":0,"timed_out":false,"runtime_ready":true}'
                    },
                },
            },
        }],
    )
    assert trace_has_live_game_probe(trace) is True


def test_live_probe_rejects_raw_timeout_and_unfinished_wrapper(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "type": "tool_use",
                "part": {
                    "tool": "bash",
                    "state": {
                        "status": "completed",
                        "input": {"command": "timeout 20 /srv/df-bonsai/current/dwarfort --help"},
                        "metadata": {"output": "still running"},
                    },
                },
            },
            {
                "type": "tool_use",
                "part": {
                    "tool": "bash",
                    "state": {
                        "status": "running",
                        "input": {"command": "bonsai-df-probe --timeout 20 -- /srv/df-bonsai/current/dfhack-run status"},
                    },
                },
            },
        ],
    )
    assert trace_has_live_game_probe(trace) is False


def test_live_probe_rejects_wrapper_when_runtime_never_became_ready(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [{
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "bonsai-df-probe -- dfhack-run status"},
                    "metadata": {
                        "output": 'BONSAI_PROBE_RESULT {"exit":126,"timed_out":false,"runtime_ready":false}'
                    },
                },
            },
        }],
    )
    assert trace_has_live_game_probe(trace) is False


def test_live_probe_can_be_required_in_the_current_phase(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    result = 'BONSAI_PROBE_RESULT {"exit":0,"timed_out":false,"runtime_ready":true}'
    write_trace(
        trace,
        [
            {
                "type": "tool_use",
                "part": {
                    "tool": "bash",
                    "state": {
                        "status": "completed",
                        "input": {"command": "bonsai-df-probe -- dfhack-run help"},
                        "metadata": {"output": result},
                    },
                },
            },
            {"type": "harness_phase", "phase": "implementation_continuation_1"},
            {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed"}}},
        ],
    )

    assert trace_has_live_game_probe(trace) is True
    assert trace_has_live_game_probe(trace, "opencode") is True
    assert trace_has_live_game_probe(trace, "implementation_continuation_1") is False


def test_context_and_degenerate_stop_classifiers(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "type": "step_finish",
                "part": {
                    "reason": "tool-calls",
                    "tokens": {"input": 69000, "output": 100},
                },
            },
            {
                "type": "step_finish",
                "part": {
                    "reason": "stop",
                    "tokens": {"input": 71000, "output": 1},
                },
            },
        ],
    )
    assert trace_latest_input_tokens(trace) == 71000
    assert trace_ended_with_degenerate_stop(trace) is True


def test_context_rollover_is_scoped_to_fresh_phase(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {"type": "step_finish", "part": {"tokens": {"input": 73000}}},
            {"type": "harness_phase", "phase": "implementation_continuation_1"},
            {"type": "step_finish", "part": {"tokens": {"input": 9000}}},
        ],
    )
    assert trace_latest_input_tokens(trace) == 9000
    assert trace_phase_latest_input_tokens(trace, "opencode") == 73000
    assert trace_phase_latest_input_tokens(trace, "implementation_continuation_1") == 9000


def test_four_token_stop_is_treated_as_degenerate(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [{"type": "step_finish", "part": {"reason": "stop", "tokens": {"output": 4}}}],
    )
    assert trace_ended_with_degenerate_stop(trace) is True


def test_implementation_only_environment_removes_research_tools(monkeypatch, tmp_path: Path):
    class ConfigStub:
        opencode_config = tmp_path / "opencode.json"

    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"permission":{"task":"allow"}}')
    general = harness_environment(ConfigStub())
    restricted = harness_environment(ConfigStub(), implementation_only=True)

    assert general["OPENCODE_CONFIG_CONTENT"] == '{"permission":{"task":"allow"}}'
    permissions = json.loads(restricted["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permissions["bash"]["*dwarfort*"] == "deny"
    assert permissions["bash"]["*dfhack-run*"] == "deny"
    assert permissions["bash"]["*/bonsai-df-probe *"] == "allow"
    assert permissions["task"] == "deny"
    assert permissions["webfetch"] == "deny"
    assert permissions["websearch"] == "deny"


def test_validation_repair_defaults_to_two_fresh_attempts(monkeypatch):
    monkeypatch.setenv("BONSAI_CONTROL_URL", "http://control")
    monkeypatch.setenv("BONSAI_LAB_TOKEN", "test-token")
    monkeypatch.delenv("BONSAI_VALIDATION_REPAIR_ATTEMPTS", raising=False)
    assert Config.from_env().validation_repair_attempts == 2


def test_recovery_prompt_paths_are_stable_and_json_serializable(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    (repo / "new_test.py").write_text("pass\n", encoding="utf-8")

    changed = serializable_working_tree_paths(repo)

    assert changed == ["README.md", "new_test.py"]
    assert json.loads(json.dumps(changed)) == changed


def test_working_tree_fingerprint_detects_edits_and_scoped_test_progress(tmp_path: Path):
    repo = init_repo(tmp_path)
    bridge = repo / "bridge.py"
    bridge.write_text("VALUE = 1\n", encoding="utf-8")
    all_before = working_tree_fingerprint(repo)
    tests_before = working_tree_fingerprint(repo, ("tests/", "evaluator_public/"))

    bridge.write_text("VALUE = 2\n", encoding="utf-8")
    assert working_tree_fingerprint(repo) != all_before
    assert working_tree_fingerprint(repo, ("tests/", "evaluator_public/")) == tests_before

    (repo / "tests").mkdir()
    (repo / "tests" / "test_bridge.py").write_text(
        "def test_bridge():\n    assert True\n", encoding="utf-8"
    )
    assert working_tree_fingerprint(repo, ("tests/", "evaluator_public/")) != tests_before


def test_generated_df_logs_are_not_candidate_changes_and_are_cleaned(tmp_path: Path):
    repo = init_repo(tmp_path)
    for name in ("errorlog.txt", "gamelog.txt", "stderr.log", "stdout.log"):
        (repo / name).write_text("generated by DF\n", encoding="utf-8")
    for name in (".mypy_cache", ".pytest_cache", ".ruff_cache"):
        (repo / name).mkdir()
        (repo / name / "cache.bin").write_bytes(b"generated cache")

    assert working_tree_paths(repo) == set()
    assert cleanup_generated_runtime_files(repo) == [
        "errorlog.txt",
        "gamelog.txt",
        "stderr.log",
        "stdout.log",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    ]
    assert not any((repo / name).exists() for name in ("errorlog.txt", "gamelog.txt", "stderr.log", "stdout.log"))
    assert not any((repo / name).exists() for name in (".mypy_cache", ".pytest_cache", ".ruff_cache"))


def test_executable_candidate_requires_an_implementation_root(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_only.py").write_text("def test_only():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    assert has_executable_candidate_change(repo) is False
    (repo / "bridge").mkdir()
    (repo / "bridge" / "observe.py").write_text("VALUE = 4\n", encoding="utf-8")
    assert has_executable_candidate_change(repo) is True


def test_df_runtime_process_ids_only_accepts_managed_dwarfort(tmp_path: Path):
    proc = tmp_path / "proc"
    runtime = tmp_path / "df-runtime"
    outside = tmp_path / "outside"
    proc.mkdir()
    runtime.mkdir()
    outside.mkdir()
    for target in (runtime / "dwarfort", runtime / "dfhack-run", outside / "dwarfort"):
        target.write_text("binary", encoding="utf-8")
    for pid, target in (("101", runtime / "dwarfort"), ("102", runtime / "dfhack-run"), ("103", outside / "dwarfort")):
        entry = proc / pid
        entry.mkdir()
        os.symlink(target, entry / "exe")

    assert df_runtime_process_ids(proc, runtime) == {101}


def test_supervised_runtime_pid_is_identified_by_systemd_cgroup(tmp_path: Path):
    proc = tmp_path / "proc"
    runtime = tmp_path / "df-runtime"
    proc.mkdir()
    runtime.mkdir()
    executable = runtime / "dwarfort"
    executable.write_text("binary", encoding="utf-8")
    for pid, cgroup in (
        ("101", "0::/system.slice/bonsai-df-runtime.service\n"),
        ("102", "0::/user.slice/opencode.scope\n"),
    ):
        entry = proc / pid
        entry.mkdir()
        os.symlink(executable, entry / "exe")
        (entry / "cgroup").write_text(cgroup, encoding="utf-8")

    assert supervised_df_runtime_process_ids(proc, runtime) == {101}


def test_guarded_probe_hard_kills_term_ignoring_runtime(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    executable = runtime / "dwarfort"
    executable.write_text(
        "#!/bin/sh\ntrap '' TERM\nwhile :; do sleep 1; done\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = run_guarded_probe(
        [str(executable), "--fake-probe"],
        timeout_seconds=1,
        runtime_root=runtime,
    )

    assert result["exit_code"] == 124
    assert result["timed_out"] is True


def test_guarded_probe_rejects_executable_outside_runtime(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    outside = tmp_path / "dwarfort"
    outside.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    outside.chmod(0o755)

    try:
        run_guarded_probe([str(outside)], runtime_root=runtime)
    except ValueError as exc:
        assert "probe executable" in str(exc)
    else:
        raise AssertionError("outside executable was accepted")


def test_runtime_readiness_starts_service_then_observes_rpc(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    client = runtime / "dfhack-run"
    client.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    calls: list[list[str]] = []
    client_results = iter(
        [
            subprocess.CompletedProcess([], 2, b"Could not connect\n"),
            subprocess.CompletedProcess([], 0, b"DFHack 53.15-r2\n"),
        ]
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0] == "/usr/bin/systemctl":
            return subprocess.CompletedProcess(command, 0, b"")
        return next(client_results)

    readiness = ensure_runtime_ready(
        runtime_root=runtime,
        timeout_seconds=5,
        command_runner=fake_run,
        sleep=lambda _seconds: None,
        monotonic=lambda: 100.0,
    )

    assert readiness["ready"] is True
    assert readiness["started"] is True
    assert readiness["attempts"] == 2
    assert calls[1] == ["/usr/bin/systemctl", "start", "bonsai-df-runtime.service"]


def test_guarded_dfhack_probe_fails_before_spawn_when_runtime_is_unavailable(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    client = runtime / "dfhack-run"
    client.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    client.chmod(0o755)

    result = run_guarded_probe(
        [str(client), "version"],
        runtime_root=runtime,
        readiness_check=lambda **_kwargs: {
            "ready": False,
            "started": True,
            "attempts": 3,
            "error": "RPC unavailable",
        },
    )

    assert result["exit_code"] == 126
    assert result["runtime"] == {
        "ready": False,
        "started": True,
        "attempts": 3,
        "error": "RPC unavailable",
        "required": True,
    }


def test_external_checkpoint_compacts_evidence_and_diff(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "bridge.py").write_text("VALUE = 1\n", encoding="utf-8")
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "type": "tool_use",
                "part": {
                    "tool": "bash",
                    "state": {
                        "input": {"command": "timeout 5 dfhack-run status"},
                        "output": "Could not connect",
                    },
                },
            },
            {"type": "step_finish", "part": {"tokens": {"input": 55000}}},
        ],
    )

    checkpoint = compact_phase_checkpoint(repo, trace, "opencode", "context_rollover", "gate failed")

    assert checkpoint["changed_paths"] == ["bridge.py"]
    assert checkpoint["stop_reason"] == "context_rollover"
    assert checkpoint["previous_gate_error"] == "gate failed"
    assert "bridge.py" in checkpoint["diff_stat"]
    assert "+VALUE = 1" in checkpoint["diff_excerpt"]
    assert checkpoint["latest_phase_input_tokens"] == 55000
    assert checkpoint["recent_evidence"][-1]["output"] == "Could not connect"


def test_harness_owned_validation_detects_edits_after_old_test_output(tmp_path: Path):
    repo = init_repo(tmp_path)
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert 2 * 3 == 6\n", encoding="utf-8")
    broken = repo / "bridge.py"
    broken.write_text("if True:\n", encoding="utf-8")

    failed = validate_coding_candidate(repo)
    assert failed["ok"] is False
    assert any(command["name"] == "py_compile" and command["exit_code"] != 0 for command in failed["commands"])

    broken.write_text("VALUE = 1\n", encoding="utf-8")
    passed = validate_coding_candidate(repo)
    assert passed["ok"] is True


def test_coding_graph_context_selects_objective_source_symbol_and_test(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "game_runner").mkdir()
    (repo / "game_runner" / "episode.py").write_text(
        "def _dfhack_run(command):\n    return command\n", encoding="utf-8"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_episode.py").write_text(
        "from game_runner.episode import _dfhack_run\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "add episode"],
        check=True,
        capture_output=True,
    )

    packet = select_coding_context(
        repo,
        {
            "objective": "Repair `game_runner/episode.py` and `_dfhack_run` with a regression test"
        },
    )

    assert "game_runner/episode.py" in packet
    assert "tests/test_episode.py" in packet
    assert "def _dfhack_run" in packet["game_runner/episode.py"]


def test_coding_graph_context_keeps_named_symbols_from_large_file_middle(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "bridge").mkdir()
    filler = "".join(f"# unrelated filler {index:04d} {'x' * 60}\n" for index in range(420))
    targets = """
def probe_map_features():
    return _dfhack_run("lua require('bridge.core').map_features()", timeout=10)

def probe_tile_map(timeout=20):
    return _dfhack_run("lua require('bridge.core').tile_map()", timeout=timeout)

def probe_unit_skills(timeout=20):
    return _dfhack_run("lua require('bridge.core').unit_skills()", timeout=timeout)
"""
    (repo / "bridge" / "probe.py").write_text(
        "from game_runner.episode import _dfhack_run\n" + filler + targets + filler,
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "add large probe"],
        check=True,
        capture_output=True,
    )

    packet = select_coding_context(
        repo,
        {
            "objective": "Repair bridge/probe.py",
            "description": (
                "Remove redundant lua from probe_map_features, probe_tile_map, "
                "and probe_unit_skills."
            ),
        },
    )

    excerpt = packet["bridge/probe.py"]
    assert len(excerpt) <= 18_000
    assert "def probe_map_features" in excerpt
    assert "def probe_tile_map" in excerpt
    assert "def probe_unit_skills" in excerpt
    assert "lua require('bridge.core').map_features()" in excerpt
    assert "lua require('bridge.core').tile_map()" in excerpt
    assert "lua require('bridge.core').unit_skills()" in excerpt


def test_coding_graph_applies_exact_controller_validated_edits(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "client.py"
    target.parent.mkdir()
    target.write_text("VALUE = 1\n", encoding="utf-8")

    changed = apply_coding_graph_edits(
        repo,
        {
            "edits": [
                {"path": "bridge/client.py", "old": "VALUE = 1", "new": "VALUE = 2"},
                {
                    "path": "tests/test_client.py",
                    "old": "",
                    "new": "from bridge.client import VALUE\n\ndef test_value():\n    assert VALUE == 2\n",
                },
            ]
        },
    )

    assert changed == ["bridge/client.py", "tests/test_client.py"]
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"


def test_coding_graph_can_fully_replace_existing_untracked_wip_file(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "broken.py"
    target.parent.mkdir()
    target.write_text("def broken():\\n  return ???\n", encoding="utf-8")

    changed = apply_coding_graph_edits(
        repo,
        {
            "edits": [
                {
                    "path": "bridge/broken.py",
                    "old": "",
                    "new": "def repaired():\n    return True\n",
                }
            ]
        },
    )

    assert changed == ["bridge/broken.py"]
    assert target.read_text(encoding="utf-8") == "def repaired():\n    return True\n"


def test_coding_graph_refuses_full_replacement_of_tracked_file(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "tracked.py"
    target.parent.mkdir()
    target.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "tracked"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(ValueError, match="empty old is only valid for a new file"):
        apply_coding_graph_edits(
            repo,
            {"edits": [{"path": "bridge/tracked.py", "old": "", "new": "VALUE = 2\n"}]},
        )

    assert target.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_coding_graph_applies_unique_whitespace_drift_without_weakening_tokens(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "client.py"
    target.parent.mkdir()
    target.write_text(
        "def probe():\n    result = call(\n        \"lua source\",\n        timeout=10,\n    )\n    return result\n",
        encoding="utf-8",
    )

    changed = apply_coding_graph_edits(
        repo,
        {
            "edits": [
                {
                    "path": "bridge/client.py",
                    "old": 'result = call("lua source", timeout=10,)',
                    "new": 'result = call("source", timeout=10,)',
                },
                {
                    "path": "tests/test_client.py",
                    "old": "",
                    "new": "def test_transport():\n    assert 3 == 3\n",
                },
            ]
        },
    )

    assert changed == ["bridge/client.py", "tests/test_client.py"]
    assert 'result = call("source", timeout=10,)' in target.read_text(encoding="utf-8")


def test_whitespace_match_rejects_ambiguous_token_sequences():
    current = 'first = call("x")\nsecond = call("x")\n'
    assert unique_whitespace_edit_span(current, 'call( "x" )') is None


def test_coding_graph_transplants_unique_small_delta_from_hallucinated_wrapper(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "probe.py"
    target.parent.mkdir()
    target.write_text(
        "def probe_map_features():\n"
        "    # Actual implementation intentionally differs from the proposal wrapper.\n"
        "    result = _dfhack_run(\"lua require('bridge.core').map_features()\", timeout=10)\n"
        "    return result if isinstance(result, list) else []\n",
        encoding="utf-8",
    )
    old = """def probe_map_features(timeout=10):
    \"\"\"Imagined wrapper.\"\"\"
    try:
        result = _dfhack_run(\"lua require('bridge.core').map_features()\", timeout=timeout)
        return result
    except Exception:
        return []"""
    new = old.replace("lua require", "require")

    changed = apply_coding_graph_edits(
        repo,
        {
            "edits": [
                {"path": "bridge/probe.py", "old": old, "new": new},
                {
                    "path": "tests/test_probe.py",
                    "old": "",
                    "new": "def test_probe_delta():\n    assert 4 == 4\n",
                },
            ]
        },
    )

    updated = target.read_text(encoding="utf-8")
    assert changed == ["bridge/probe.py", "tests/test_probe.py"]
    assert "lua require" not in updated
    assert "def probe_map_features():" in updated
    assert "Actual implementation intentionally differs" in updated


def test_minimal_delta_rejects_ambiguous_local_anchors():
    old = 'result = _dfhack_run("lua require(\'bridge.core\').observe()")'
    new = old.replace("lua require", "require")
    current = old + "\n" + old + "\n"
    assert unique_minimal_delta_span(current, old, new) is None


def test_coding_graph_rejects_protected_edit_without_partial_write(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "client.py"
    target.parent.mkdir()
    target.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe path"):
        apply_coding_graph_edits(
            repo,
            {
                "edits": [
                    {"path": "bridge/client.py", "old": "VALUE = 1", "new": "VALUE = 2"},
                    {"path": "control_plane/app.py", "old": "", "new": "UNSAFE = True\n"},
                ]
            },
        )

    assert target.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (repo / "control_plane" / "app.py").exists()


def test_coding_graph_batches_independent_edits_against_one_file_version(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "client.py"
    target.parent.mkdir()
    target.write_text("FIRST = 1\nMIDDLE = 2\nLAST = 3\n", encoding="utf-8")

    changed = apply_coding_graph_edits(
        repo,
        {
            "edits": [
                {"path": "bridge/client.py", "old": "FIRST = 1", "new": "FIRST = 10"},
                {"path": "bridge/client.py", "old": "LAST = 3", "new": "LAST = 30"},
            ]
        },
    )

    assert changed == ["bridge/client.py"]
    assert target.read_text(encoding="utf-8") == "FIRST = 10\nMIDDLE = 2\nLAST = 30\n"


def test_coding_graph_accepts_only_unique_high_similarity_python_method(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "tests" / "test_contract.py"
    target.parent.mkdir()
    target.write_text(
        "class TestContract:\n"
        "    def test_transport_error(self):\n"
        "        \"\"\"Old live-only assumption.\"\"\"\n"
        "        result = call_live_server(timeout=5)\n"
        "        assert result is None\n\n"
        "    def test_other(self):\n"
        "        assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    approximate_old = (
        "    def test_transport_error(self):\n"
        "        \"\"\"Slightly different live-only assumption.\"\"\"\n"
        "        result = call_live_server(timeout=2)\n"
        "        assert result is None\n"
    )
    replacement = (
        "    def test_transport_error(self, monkeypatch):\n"
        "        monkeypatch.setattr('bridge.probe.probe_time', lambda **_kwargs: None)\n"
        "        assert probe_time(timeout=2) is None\n"
    )

    assert unique_fuzzy_edit_span(
        target.read_text(encoding="utf-8"),
        approximate_old,
        replacement,
        "tests/test_contract.py",
    ) is not None
    changed = apply_coding_graph_edits(
        repo,
        {"edits": [{"path": "tests/test_contract.py", "old": approximate_old, "new": replacement}]},
    )

    assert changed == ["tests/test_contract.py"]
    updated = target.read_text(encoding="utf-8")
    assert "monkeypatch" in updated
    assert "def test_other" in updated


def test_coding_graph_rejects_ambiguous_fuzzy_symbol(tmp_path: Path):
    current = (
        "class First:\n    def test_same(self):\n        assert True\n\n"
        "class Second:\n    def test_same(self):\n        assert False\n"
    )
    old = "    def test_same(self):\n        assert maybe_true\n" + ("# context\n" * 10)
    replacement = "    def test_same(self):\n        assert 2 + 2 == 4\n"
    assert unique_fuzzy_edit_span(current, old, replacement, "tests/test_contract.py") is None


def test_coding_graph_fuzzy_replacement_must_keep_the_same_symbol():
    current = "def test_transport():\n    assert call_live() is None\n"
    old = "def test_transport():\n    # a long but approximate block\n    assert live_result is None\n"
    new = "def unrelated_test():\n    assert 2 + 2 == 4\n"
    assert unique_fuzzy_edit_span(current, old, new, "tests/test_contract.py") is None


def test_coding_graph_selects_distinct_duplicate_class_by_similarity():
    current = (
        "class TestTransport:\n"
        "    def test_existing(self):\n        assert 2 + 2 == 4\n\n"
        "class TestTransport:\n"
        "    def test_live(self):\n        assert call_live() is None\n"
    )
    old = (
        "class TestTransport:\n"
        "    # approximate duplicate class from the model\n"
        "    def test_live(self):\n        assert live_result is None\n"
    )
    new = (
        "class TestTransport:\n"
        "    def test_live(self, monkeypatch):\n"
        "        monkeypatch.setattr('bridge.probe.probe_time', lambda **_kwargs: None)\n"
        "        assert probe_time() is None\n"
    )
    span = unique_fuzzy_edit_span(current, old, new, "tests/test_contract.py")
    assert span is not None
    assert "call_live" in current[span[0]:span[1]]


def test_coding_graph_routes_from_artifacts_and_validation(tmp_path: Path):
    repo = init_repo(tmp_path)
    assert coding_graph_decision(repo, None) == "draft"
    (repo / "bridge").mkdir()
    (repo / "bridge" / "client.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert coding_graph_decision(repo, {"ok": True}) == "repair"
    (repo / "tests").mkdir()
    (repo / "tests" / "test_client.py").write_text(
        "def test_value():\n    assert 2 == 2\n", encoding="utf-8"
    )
    assert coding_graph_decision(repo, {"ok": False}) == "repair"
    assert coding_graph_decision(repo, {"ok": True}) == "promote"


class WipConfigStub:
    def __init__(self, root: Path):
        self.wip_dir = root / "wip"


def wip_job(job_type: str = "coding_cycle") -> dict:
    return {
        "id": "5917fed3-3f4c-434a-a886-2ba756422bf6",
        "objective_id": "baca4249-75a2-4aec-8bcc-9d4a008cd1fa",
        "job_type": job_type,
    }


def clean_repo(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "reset", "--hard", "HEAD"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "clean", "-fd"], check=True, capture_output=True)


def test_cross_job_wip_restores_tracked_and_untracked_progress(tmp_path: Path):
    repo = init_repo(tmp_path)
    config = WipConfigStub(tmp_path)
    job = wip_job()
    (repo / "bridge").mkdir()
    (repo / "bridge" / "probe.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_probe.py").write_text("def test_value():\n    assert True\n", encoding="utf-8")
    trace = tmp_path / "store-trace.jsonl"

    stored = persist_cross_job_wip(config, job, repo, "baseline", "repair", "gate failed", trace)
    assert stored is not None
    assert stored["changed_paths"] == ["bridge/probe.py", "tests/test_probe.py"]
    clean_repo(repo)

    restore_trace = tmp_path / "restore-trace.jsonl"
    restored = restore_cross_job_wip(config, {**job, "id": "82dbd080-1d14-4421-bfb1-7ef3f7d50a97"}, repo, restore_trace)
    assert restored is not None
    assert restored["status"] == "restored"
    assert restored["replay_count"] == 1
    assert (repo / "bridge" / "probe.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert working_tree_paths(repo) == {"bridge/probe.py", "tests/test_probe.py"}
    assert "cross_job_wip_restored" in restore_trace.read_text(encoding="utf-8")


def test_cross_job_wip_clears_after_patch_is_in_baseline(tmp_path: Path):
    repo = init_repo(tmp_path)
    config = WipConfigStub(tmp_path)
    job = wip_job()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_done.py").write_text("def test_done():\n    assert True\n", encoding="utf-8")
    persist_cross_job_wip(config, job, repo, "baseline", "candidate", "ready")
    subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "promoted"], check=True, capture_output=True)

    cleared = restore_cross_job_wip(config, {**job, "id": "82dbd080-1d14-4421-bfb1-7ef3f7d50a97"}, repo)
    assert cleared is not None
    assert cleared["status"] == "already_in_baseline"
    assert not config.wip_dir.joinpath(f"{job['objective_id']}.coding_cycle.patch").exists()
    assert not config.wip_dir.joinpath(f"{job['objective_id']}.coding_cycle.json").exists()


def test_cross_job_wip_never_restores_protected_paths(tmp_path: Path):
    repo = init_repo(tmp_path)
    config = WipConfigStub(tmp_path)
    job = wip_job()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_safe.py").write_text("def test_safe():\n    assert True\n", encoding="utf-8")
    (repo / "control_plane").mkdir()
    (repo / "control_plane" / "unsafe.py").write_text("SECRET = True\n", encoding="utf-8")

    stored = persist_cross_job_wip(config, job, repo, "baseline", "repair", "failed")
    assert stored is not None
    assert stored["changed_paths"] == ["tests/test_safe.py"]
    assert stored["skipped_paths"] == ["control_plane/unsafe.py"]
    clean_repo(repo)

    restored = restore_cross_job_wip(config, {**job, "id": "82dbd080-1d14-4421-bfb1-7ef3f7d50a97"}, repo)
    assert restored is not None and restored["status"] == "restored"
    assert (repo / "tests" / "test_safe.py").is_file()
    assert not (repo / "control_plane" / "unsafe.py").exists()


def test_cross_job_wip_defers_across_job_modes(tmp_path: Path):
    repo = init_repo(tmp_path)
    config = WipConfigStub(tmp_path)
    coding = wip_job("coding_cycle")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_pending.py").write_text("def test_pending():\n    assert True\n", encoding="utf-8")
    persist_cross_job_wip(config, coding, repo, "baseline", "repair", "failed")
    clean_repo(repo)

    discovery = {**coding, "id": "82dbd080-1d14-4421-bfb1-7ef3f7d50a97", "job_type": "discovery_cycle"}
    deferred = restore_cross_job_wip(config, discovery, repo)
    assert deferred is None
    assert working_tree_paths(repo) == set()
    assert config.wip_dir.joinpath(f"{coding['objective_id']}.coding_cycle.patch").is_file()


def test_cross_job_wip_namespaces_coding_and_discovery_for_one_objective(tmp_path: Path):
    repo = init_repo(tmp_path)
    config = WipConfigStub(tmp_path)
    coding = wip_job("coding_cycle")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_pending.py").write_text(
        "def test_pending():\n    assert 2 + 2 == 4\n", encoding="utf-8"
    )
    persist_cross_job_wip(config, coding, repo, "baseline", "repair", "failed")
    clean_repo(repo)
    discovery = {**coding, "id": "82dbd080-1d14-4421-bfb1-7ef3f7d50a97", "job_type": "discovery_cycle"}
    (repo / "knowledge").mkdir()
    (repo / "knowledge" / "INDEX.md").write_text("# Evidence\n", encoding="utf-8")
    persist_cross_job_wip(config, discovery, repo, "baseline", "discovery", "candidate")

    names = {path.name for path in config.wip_dir.iterdir()}
    assert f"{coding['objective_id']}.coding_cycle.patch" in names
    assert f"{coding['objective_id']}.discovery_cycle.patch" in names


def test_cross_job_wip_quarantines_after_three_unchanged_replays(tmp_path: Path):
    repo = init_repo(tmp_path)
    config = WipConfigStub(tmp_path)
    job = wip_job()
    (repo / "bridge").mkdir()
    (repo / "bridge" / "stuck.py").write_text("BROKEN = True\n", encoding="utf-8")
    persist_cross_job_wip(config, job, repo, "baseline", "repair", "failed")
    clean_repo(repo)

    for _ in range(3):
        restored = restore_cross_job_wip(config, job, repo)
        assert restored is not None and restored["status"] == "restored"
        clean_repo(repo)

    quarantined = restore_cross_job_wip(config, job, repo)
    assert quarantined is not None and quarantined["status"] == "quarantined"
    assert quarantined["reason"] == "unchanged_replay_limit"
    assert quarantined["replay_count"] == 3
    assert working_tree_paths(repo) == set()
    active_stem = f"{job['objective_id']}.coding_cycle"
    assert not config.wip_dir.joinpath(f"{active_stem}.patch").exists()
    assert not config.wip_dir.joinpath(f"{active_stem}.json").exists()
    assert len(list(config.wip_dir.joinpath("quarantine").glob("*.patch"))) == 1
    assert len(list(config.wip_dir.joinpath("quarantine").glob("*.json"))) == 1


def test_cross_job_wip_changed_patch_resets_replay_count(tmp_path: Path):
    repo = init_repo(tmp_path)
    config = WipConfigStub(tmp_path)
    job = wip_job()
    (repo / "bridge").mkdir()
    target = repo / "bridge" / "progress.py"
    target.write_text("STEP = 1\n", encoding="utf-8")
    persist_cross_job_wip(config, job, repo, "baseline", "repair", "first")
    clean_repo(repo)
    restored = restore_cross_job_wip(config, job, repo)
    assert restored is not None and restored["replay_count"] == 1

    target.write_text("STEP = 2\n", encoding="utf-8")
    persist_cross_job_wip(config, job, repo, "baseline", "repair", "changed")
    metadata_path = config.wip_dir / f"{job['objective_id']}.coding_cycle.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["replay_count"] == 0


def test_quality_gate_ignores_preexisting_lint_but_checks_added_lines(tmp_path: Path):
    repo = init_repo(tmp_path)
    legacy = repo / "bridge" / "legacy.py"
    legacy.parent.mkdir()
    legacy.write_text("import os\n\nVALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "legacy lint"], check=True, capture_output=True)
    legacy.write_text("import os\n\nVALUE = 1\nNEW_VALUE = VALUE + 1\n", encoding="utf-8")

    quality = evaluate_python_quality(repo, "HEAD", ["bridge/legacy.py"])
    assert quality["ok"] is True
    assert not any(item["code"] == "F401" for item in quality["diagnostics"])


def test_quality_gate_blocks_undefined_names_on_new_lines(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "bridge" / "broken.py"
    target.parent.mkdir()
    target.write_text("def observe():\n    return invented_runtime_value\n", encoding="utf-8")

    quality = evaluate_python_quality(repo, "HEAD", ["bridge/broken.py"])
    assert quality["ok"] is False
    assert any(item["code"] == "F821" for item in quality["diagnostics"])


def test_quality_gate_blocks_placeholder_tests_and_swallowed_errors(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "tests" / "test_slop.py"
    target.parent.mkdir()
    target.write_text(
        "def test_placeholder():\n"
        "    assert True\n\n"
        "def swallow():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )

    quality = evaluate_python_quality(repo, "HEAD", ["tests/test_slop.py"])
    codes = {item["code"] for item in quality["diagnostics"]}
    assert quality["ok"] is False
    assert "SLOP002" in codes
    assert "SLOP003" in codes


def test_quality_gate_blocks_placeholder_replacing_existing_test_body(tmp_path: Path):
    repo = init_repo(tmp_path)
    target = repo / "tests" / "test_existing.py"
    target.parent.mkdir()
    target.write_text(
        "def test_existing():\n    assert 2 * 3 == 6\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "real test"],
        check=True,
        capture_output=True,
    )
    target.write_text("def test_existing():\n    assert True\n", encoding="utf-8")

    quality = evaluate_python_quality(repo, "HEAD", ["tests/test_existing.py"])
    assert quality["ok"] is False
    assert any(item["code"] == "SLOP002" for item in quality["diagnostics"])


def test_harness_validation_returns_exact_quality_errors_for_repair(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_real.py").write_text(
        "def test_real():\n    assert 2 * 3 == 6\n",
        encoding="utf-8",
    )
    (repo / "bridge").mkdir()
    (repo / "bridge" / "broken.py").write_text(
        "def observe():\n    return missing_df_state\n",
        encoding="utf-8",
    )

    validation = validate_coding_candidate(repo)
    quality_command = next(
        command for command in validation["commands"] if command["name"] == "python_quality_gate"
    )
    assert validation["ok"] is False
    assert quality_command["exit_code"] == 1
    assert "F821" in quality_command["output"]
    assert "missing_df_state" in quality_command["output"]
