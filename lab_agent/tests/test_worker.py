import json
import subprocess
from pathlib import Path

from bonsai_lab_agent.worker import (
    discovery_needs_synthesis,
    has_public_test_change,
    normalize_commit_description,
    trace_ended_with_degenerate_stop,
    trace_has_live_game_probe,
    trace_has_test_execution,
    trace_has_successful_test,
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


def test_live_game_probe_requires_bounded_runtime_execution(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    events = [
        {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {"input": {"command": "file /srv/df-bonsai/current/dwarfort"}},
            },
        },
        {
            "type": "tool_use",
            "part": {
                "tool": "read",
                "state": {"input": {"path": "/srv/df-bonsai/current/VERSIONS.txt"}},
            },
        },
    ]
    trace.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    assert trace_has_live_game_probe(trace) is False

    events.append(
        {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {
                    "input": {
                        "command": "timeout 20 /srv/df-bonsai/current/dfhack-run probe_dfhack"
                    }
                },
            },
        }
    )
    trace.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    assert trace_has_live_game_probe(trace) is True


def test_test_execution_requires_bash_test_command(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    read_event = {
        "type": "tool_use",
        "part": {"tool": "read", "state": {"input": {"path": "tests/test_bridge_contract.py"}}},
    }
    trace.write_text(json.dumps(read_event), encoding="utf-8")
    assert trace_has_test_execution(trace) is False
    test_event = {
        "type": "tool_use",
        "part": {
            "tool": "bash",
            "state": {"input": {"command": "python -m pytest tests/test_bridge_contract.py -q"}},
        },
    }
    trace.write_text(json.dumps(test_event), encoding="utf-8")
    assert trace_has_test_execution(trace) is True


def test_successful_test_rejects_pipe_masked_failure(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    event = {
        "type": "tool_use",
        "part": {
            "tool": "bash",
            "state": {
                "status": "completed",
                "input": {"command": "pytest -q 2>&1 | tail -20"},
                "metadata": {"exit": 0, "output": "1 failed, 139 passed in 0.45s"},
            },
        },
    }
    trace.write_text(json.dumps(event), encoding="utf-8")
    assert trace_has_successful_test(trace) is False
    event["part"]["state"]["metadata"]["output"] = "140 passed in 0.41s"
    trace.write_text(json.dumps(event), encoding="utf-8")
    assert trace_has_successful_test(trace) is True


def test_public_test_change_is_required_for_coding_candidate(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "bridge.py").write_text("changed\n", encoding="utf-8")
    assert has_public_test_change(repo) is False
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_bridge.py").write_text("def test_bridge():\n    assert True\n", encoding="utf-8")
    assert has_public_test_change(repo) is True


def test_public_evaluator_change_is_accepted(tmp_path: Path):
    repo = init_repo(tmp_path)
    evaluator = repo / "evaluator_public"
    evaluator.mkdir()
    (evaluator / "contract.py").write_text("CHECK = True\n", encoding="utf-8")
    assert has_public_test_change(repo) is True


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
            "index_markdown": "# Index\n\n[Bridge](dfhack/bridge-primitives.md)\n" + "context " * 30,
            "note_markdown": (
                "# Bridge primitives\n\n"
                "VERIFIED — Dwarf Fortress 53.15 with DFHack 53.15-r2.\n\n"
                "INFERRED — bridge implication.\n\nOPEN — controlled probe remains.\n\n"
                + "Source and recommendation. " * 30
            ),
        },
    )
    assert target == "dfhack/bridge-primitives.md"
    assert discovery_needs_synthesis(repo) is False


def test_detects_degenerate_opencode_stop(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        '{"type":"step_finish","part":{"reason":"tool-calls","tokens":{"output":42}}}\n'
        '{"type":"step_finish","part":{"reason":"stop","tokens":{"input":27428,"output":1}}}\n',
        encoding="utf-8",
    )
    assert trace_ended_with_degenerate_stop(trace) is True


def test_normal_stop_does_not_trigger_recovery(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        '{"type":"step_finish","part":{"reason":"stop","tokens":{"output":73}}}\n',
        encoding="utf-8",
    )
    assert trace_ended_with_degenerate_stop(trace) is False


def test_commit_description_is_normalized_and_trailers_are_reserved():
    title, body = normalize_commit_description(
        {
            "title": "  Add deterministic episode logging.\n",
            "body": "Explain the change.\nBonsai-Job-Type: fake\nKeep this detail.",
        },
        "coding_cycle",
    )
    assert title == "Add deterministic episode logging"
    assert body == "Explain the change.\nKeep this detail."


def test_commit_description_has_readable_fallback():
    title, body = normalize_commit_description({}, "discovery_cycle")
    assert title == "Advance discovery cycle"
    assert body
