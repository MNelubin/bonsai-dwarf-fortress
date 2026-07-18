import subprocess
from pathlib import Path

import pytest

from bonsai_control.promoter import GateRejected, inspect_candidate


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def candidate_bundle(
    tmp_path: Path, changed_path: str, include_test_evidence: bool = True
) -> tuple[Path, str, str, Path]:
    repo = tmp_path / "trusted"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, stdout=subprocess.PIPE)
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "docs").mkdir()
    (repo / "docs" / "baseline.md").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    target = repo / changed_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_candidate():\n    assert True\n", encoding="utf-8")
    if include_test_evidence and not changed_path.startswith("tests/"):
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "test_evidence.py").write_text(
            "def test_evidence():\n    assert True\n", encoding="utf-8"
        )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "candidate")
    candidate = git(repo, "rev-parse", "HEAD")
    git(repo, "branch", f"agent/test", candidate)
    bundle = tmp_path / "candidate.bundle"
    git(repo, "bundle", "create", str(bundle), "refs/heads/agent/test")
    return repo, base, candidate, bundle


def test_allowed_candidate_passes_static_gate(tmp_path: Path):
    repo, base, candidate, bundle = candidate_bundle(tmp_path, "bridge/bridge.py")
    report = inspect_candidate(repo, bundle, base, candidate, tmp_path / "eval")
    assert report["allowed"] is True
    assert report["gate_mode"] == "bootstrap_static_v1"
    assert "bridge/bridge.py" in report["checks"]["changed_paths"]


def test_protected_candidate_is_rejected(tmp_path: Path):
    repo, base, candidate, bundle = candidate_bundle(tmp_path, "control_plane/evil.py")
    with pytest.raises(GateRejected) as rejected:
        inspect_candidate(repo, bundle, base, candidate, tmp_path / "eval")
    assert any("protected path" in reason for reason in rejected.value.report["reasons"])


def test_discovery_candidate_only_updates_knowledge(tmp_path: Path):
    repo, base, candidate, bundle = candidate_bundle(
        tmp_path, "knowledge/INDEX.md", include_test_evidence=False
    )
    report = inspect_candidate(
        repo, bundle, base, candidate, tmp_path / "eval", job_type="discovery_cycle"
    )
    assert report["allowed"] is True
    assert report["job_type"] == "discovery_cycle"


def test_discovery_rejects_code_changes(tmp_path: Path):
    repo, base, candidate, bundle = candidate_bundle(tmp_path, "bridge/bridge.py")
    with pytest.raises(GateRejected) as rejected:
        inspect_candidate(
            repo, bundle, base, candidate, tmp_path / "eval", job_type="discovery_cycle"
        )
    assert any("only change knowledge" in reason for reason in rejected.value.report["reasons"])
