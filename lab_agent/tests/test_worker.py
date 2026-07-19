import json
import subprocess
from pathlib import Path

from bonsai_lab_agent.worker import (
    Config,
    discovery_needs_synthesis,
    compact_phase_checkpoint,
    harness_environment,
    trace_ended_with_degenerate_stop,
    trace_has_live_game_probe,
    trace_latest_input_tokens,
    trace_phase_latest_input_tokens,
    trace_phase_tool_use_count,
    serializable_working_tree_paths,
    validate_coding_candidate,
    working_tree_paths,
    write_discovery_bundle,
)


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


def test_live_probe_accepts_bounded_dfhack_and_bridge_commands(tmp_path: Path):
    for command in (
        "timeout 20 /srv/df-bonsai/current/hack/dfhack-run status",
        "timeout 20 python3 bridge/probe.py --observe",
    ):
        trace = tmp_path / "trace.jsonl"
        write_trace(
            trace,
            [{
                "type": "tool_use",
                "part": {
                    "tool": "bash",
                    "state": {"input": {"command": command}},
                },
            }],
        )
        assert trace_has_live_game_probe(trace) is True


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
    assert checkpoint["latest_phase_input_tokens"] == 55000
    assert checkpoint["recent_evidence"][-1]["output"] == "Could not connect"


def test_harness_owned_validation_detects_edits_after_old_test_output(tmp_path: Path):
    repo = init_repo(tmp_path)
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    broken = repo / "bridge.py"
    broken.write_text("if True:\n", encoding="utf-8")

    failed = validate_coding_candidate(repo)
    assert failed["ok"] is False
    assert any(command["name"] == "py_compile" and command["exit_code"] != 0 for command in failed["commands"])

    broken.write_text("VALUE = 1\n", encoding="utf-8")
    passed = validate_coding_candidate(repo)
    assert passed["ok"] is True
