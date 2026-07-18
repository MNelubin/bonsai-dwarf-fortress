import subprocess
from pathlib import Path

from bonsai_lab_agent.worker import (
    discovery_needs_synthesis,
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
