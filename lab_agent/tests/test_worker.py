import json
import subprocess
from pathlib import Path

from bonsai_lab_agent.worker import (
    discovery_needs_synthesis,
    trace_ended_with_degenerate_stop,
    trace_has_live_game_probe,
    trace_latest_input_tokens,
    trace_phase_tool_use_count,
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
