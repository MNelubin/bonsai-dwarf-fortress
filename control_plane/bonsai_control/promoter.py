from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from psycopg import Connection

from .db import close_pool, connection as db_connection, open_pool
from .policy import AUTO_PATHS, PROTECTED_PATHS
from .settings import get_settings


MAX_CHANGED_FILES = 200
MAX_COMMITS = 20
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(rb"BONSAI_(?:LAB|ADMIN)_TOKEN\s*="),
    re.compile(rb"postgres(?:ql)?://[^\s:/]+:[^\s@]+@"),
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class GateRejected(RuntimeError):
    def __init__(self, report: dict[str, Any]):
        super().__init__("; ".join(report["reasons"]))
        self.report = report


@dataclass(frozen=True)
class Candidate:
    job_id: str
    job_type: str
    base_commit: str
    candidate_commit: str
    branch_name: str
    bundle_path: Path
    trace_sha256: str


def _run(command: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/home/bonsai",
                "LANG": "C.UTF-8",
                "GIT_TERMINAL_PROMPT": "0",
            },
        )
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "").strip()[-4_000:]
        raise RuntimeError(
            f"command failed ({exc.returncode}): {' '.join(command)}\n{output}"
        ) from exc
    return completed.stdout.strip()


def _git(repo: Path, *args: str, timeout: int = 120) -> str:
    return _run(["git", "-C", str(repo), *args], timeout=timeout)


def _bundle_ref(bundle: Path, candidate_commit: str) -> str:
    output = _run(["git", "bundle", "list-heads", str(bundle)])
    for line in output.splitlines():
        commit, separator, ref = line.partition(" ")
        if separator and commit == candidate_commit and ref.startswith("refs/heads/agent/"):
            return ref
    raise RuntimeError("bundle has no agent branch pointing to candidate_commit")


def _safe_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
        and "\\" not in path
        and not path.startswith(".git")
    )


def _knowledge_link_target(source_path: str, raw_target: str) -> str | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return None
    resolved = PurePosixPath(source_path).parent / target
    normalized: list[str] = []
    for part in resolved.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized:
                return ""
            normalized.pop()
        else:
            normalized.append(part)
    return "/".join(normalized)


def inspect_candidate(
    trusted_repo: Path,
    bundle_path: Path,
    base_commit: str,
    candidate_commit: str,
    evaluator_dir: Path,
    job_type: str = "coding_cycle",
) -> dict[str, Any]:
    reasons: list[str] = []
    checks: dict[str, Any] = {}
    evaluator_dir.mkdir(parents=True, exist_ok=True)
    bundle_ref = _bundle_ref(bundle_path, candidate_commit)
    with tempfile.TemporaryDirectory(prefix="candidate-", dir=evaluator_dir) as temporary:
        repo = Path(temporary) / "repo"
        _run(["git", "clone", "--no-hardlinks", "--no-checkout", str(trusted_repo), str(repo)])
        _git(repo, "fetch", "--no-tags", str(bundle_path), bundle_ref)
        _git(repo, "cat-file", "-e", f"{base_commit}^{{commit}}")
        _git(repo, "cat-file", "-e", f"{candidate_commit}^{{commit}}")

        fast_forward = (
            subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", base_commit, candidate_commit],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
        checks["fast_forward"] = fast_forward
        if not fast_forward:
            reasons.append("candidate is not a descendant of the trusted baseline")

        commit_count = int(_git(repo, "rev-list", "--count", f"{base_commit}..{candidate_commit}"))
        checks["commit_count"] = commit_count
        if commit_count < 1 or commit_count > MAX_COMMITS:
            reasons.append(f"candidate commit count {commit_count} is outside 1..{MAX_COMMITS}")

        raw_changes = subprocess.check_output(
            [
                "git",
                "-C",
                str(repo),
                "diff",
                "--no-renames",
                "--name-status",
                "-z",
                base_commit,
                candidate_commit,
            ]
        ).decode("utf-8", errors="strict")
        fields = raw_changes.rstrip("\0").split("\0") if raw_changes else []
        changes = [(fields[index], fields[index + 1]) for index in range(0, len(fields), 2)]
        changed_paths = [path for _, path in changes]
        checks["changed_paths"] = changed_paths
        if not changed_paths:
            reasons.append("candidate contains no changed paths")
        if len(changed_paths) > MAX_CHANGED_FILES:
            reasons.append(f"candidate changes more than {MAX_CHANGED_FILES} files")
        for path in changed_paths:
            if not _safe_path(path):
                reasons.append(f"unsafe git path: {path!r}")
            elif path.startswith(PROTECTED_PATHS):
                reasons.append(f"protected path changed: {path}")
            elif not path.startswith(AUTO_PATHS):
                reasons.append(f"path outside auto-promotion allowlist: {path}")
        if job_type == "discovery_cycle":
            for path in changed_paths:
                if not path.startswith("knowledge/"):
                    reasons.append(f"discovery mode may only change knowledge/: {path}")
            if not any(path.endswith((".md", ".json")) for path in changed_paths):
                reasons.append("discovery candidate must contain Markdown or JSON knowledge")
            index_exists = subprocess.run(
                ["git", "-C", str(repo), "cat-file", "-e", f"{candidate_commit}:knowledge/INDEX.md"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
            if not index_exists:
                reasons.append("discovery candidate must provide knowledge/INDEX.md")
            knowledge_files = _git(repo, "ls-tree", "-r", "--name-only", candidate_commit, "--", "knowledge/").splitlines()
            substantive_notes = [
                path for path in knowledge_files
                if path != "knowledge/INDEX.md" and path.endswith((".md", ".json"))
            ]
            checks["knowledge_files"] = knowledge_files
            if not substantive_notes:
                reasons.append("discovery candidate must provide at least one knowledge note besides INDEX.md")
            broken_links: list[dict[str, str]] = []
            for source_path in (path for path in knowledge_files if path.endswith(".md")):
                markdown = _git(repo, "show", f"{candidate_commit}:{source_path}")
                for raw_target in MARKDOWN_LINK.findall(markdown):
                    target = _knowledge_link_target(source_path, raw_target)
                    if target is None:
                        continue
                    if not target or not target.startswith("knowledge/") or subprocess.run(
                        ["git", "-C", str(repo), "cat-file", "-e", f"{candidate_commit}:{target}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ).returncode != 0:
                        broken_links.append({"source": source_path, "target": raw_target})
            checks["broken_knowledge_links"] = broken_links
            if broken_links:
                reasons.append("discovery knowledge contains broken or escaping local links")
        else:
            if any(path.startswith("knowledge/") for path in changed_paths):
                reasons.append("coding mode may not change the discovery knowledge library")
            if not any(path.startswith(("tests/", "evaluator_public/")) for path in changed_paths):
                reasons.append("coding candidate must add or update public test/evaluation evidence")

        diff_check = subprocess.run(
            ["git", "-C", str(repo), "diff", "--check", base_commit, candidate_commit],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        checks["diff_check"] = diff_check.stdout[-4_000:]
        if diff_check.returncode != 0:
            reasons.append("git diff --check failed")

        total_bytes = 0
        parsed_files: list[str] = []
        for status, path in changes:
            if status == "D" or not _safe_path(path):
                continue
            tree_entry = _git(repo, "ls-tree", candidate_commit, "--", path)
            mode = tree_entry.split(maxsplit=1)[0] if tree_entry else ""
            if mode in {"120000", "160000"}:
                reasons.append(f"symlink or submodule is forbidden: {path}")
                continue
            size = int(_git(repo, "cat-file", "-s", f"{candidate_commit}:{path}"))
            total_bytes += size
            if size > MAX_BLOB_BYTES:
                reasons.append(f"file exceeds {MAX_BLOB_BYTES} bytes: {path}")
                continue
            content = subprocess.check_output(
                ["git", "-C", str(repo), "show", f"{candidate_commit}:{path}"]
            )
            for pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    reasons.append(f"possible secret detected in {path}")
                    break
            try:
                if path.endswith(".py"):
                    ast.parse(content.decode("utf-8"), filename=path)
                    parsed_files.append(path)
                elif path.endswith(".json"):
                    json.loads(content.decode("utf-8"))
                    parsed_files.append(path)
            except (SyntaxError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                reasons.append(f"static parse failed for {path}: {exc}")
        checks["parsed_files"] = parsed_files
        checks["changed_blob_bytes"] = total_bytes
        if total_bytes > MAX_TOTAL_BYTES:
            reasons.append(f"changed content exceeds {MAX_TOTAL_BYTES} bytes")

    report = {
        "gate_mode": "bootstrap_static_v1",
        "job_type": job_type,
        "allowed": not reasons,
        "reasons": reasons,
        "checks": checks,
    }
    if reasons:
        raise GateRejected(report)
    return report


def _event(
    connection: Connection,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO bonsai.events
            (event_type, actor_type, actor_id, aggregate_type, aggregate_id, payload)
        VALUES (%s, 'control', 'promoter', %s, %s, %s)
        """,
        (event_type, aggregate_type, aggregate_id, json.dumps(payload, default=str)),
    )


def _next_candidate() -> Candidate | None:
    settings = get_settings()
    with db_connection() as connection, connection.transaction():
        row = connection.execute(
            """
            SELECT j.*, g.id AS git_change_id, g.branch_name
            FROM bonsai.jobs j
            JOIN bonsai.git_changes g ON g.job_id = j.id
            WHERE j.state = 'candidate' AND g.promotion_state IN ('draft', 'evaluating')
            ORDER BY j.completed_at, j.created_at
            FOR UPDATE OF g SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        baseline = connection.execute(
            "SELECT current_baseline_commit FROM bonsai.system_state WHERE singleton = true"
        ).fetchone()["current_baseline_commit"]
        if row["base_commit"] != baseline:
            report = {
                "gate_mode": "bootstrap_static_v1",
                "allowed": False,
                "reasons": ["candidate base is not the current trusted baseline"],
            }
            connection.execute(
                "UPDATE bonsai.jobs SET state = 'rejected', error = %s, updated_at = now() WHERE id = %s",
                (report["reasons"][0], row["id"]),
            )
            connection.execute(
                "UPDATE bonsai.git_changes SET promotion_state = 'rejected', evidence = evidence || %s WHERE id = %s",
                (json.dumps(report), row["git_change_id"]),
            )
            _event(connection, "promotion.rejected", "job", str(row["id"]), report)
            return None
        artifacts = connection.execute(
            "SELECT * FROM bonsai.artifacts WHERE sha256 = ANY(%s)", (row["artifact_hashes"],)
        ).fetchall()
        bundle = next((item for item in artifacts if item["media_type"] == "application/x-git-bundle"), None)
        trace = next((item for item in artifacts if item["media_type"] == "application/x-ndjson"), None)
        if bundle is None or trace is None:
            report = {
                "gate_mode": "bootstrap_static_v1",
                "allowed": False,
                "reasons": ["candidate requires both git bundle and OpenCode trace artifacts"],
            }
            connection.execute(
                "UPDATE bonsai.jobs SET state = 'rejected', error = %s, updated_at = now() WHERE id = %s",
                (report["reasons"][0], row["id"]),
            )
            connection.execute(
                "UPDATE bonsai.git_changes SET promotion_state = 'rejected', evidence = evidence || %s WHERE id = %s",
                (json.dumps(report), row["git_change_id"]),
            )
            _event(connection, "promotion.rejected", "job", str(row["id"]), report)
            return None
        bundle_path = Path(bundle["storage_path"]).resolve()
        if not bundle_path.is_relative_to(Path(settings.artifact_dir).resolve()):
            raise RuntimeError("candidate bundle path escapes artifact root")
        connection.execute(
            "UPDATE bonsai.git_changes SET promotion_state = 'evaluating' WHERE id = %s",
            (row["git_change_id"],),
        )
        _event(connection, "promotion.started", "job", str(row["id"]), {"candidate_commit": row["candidate_commit"]})
        return Candidate(
            job_id=str(row["id"]),
            job_type=row["job_type"],
            base_commit=row["base_commit"],
            candidate_commit=row["candidate_commit"],
            branch_name=row["branch_name"],
            bundle_path=bundle_path,
            trace_sha256=trace["sha256"],
        )


def _record_rejection(candidate: Candidate, report: dict[str, Any]) -> None:
    with db_connection() as connection, connection.transaction():
        connection.execute(
            "UPDATE bonsai.jobs SET state = 'rejected', error = %s, updated_at = now() WHERE id = %s",
            ("; ".join(report["reasons"]), candidate.job_id),
        )
        connection.execute(
            """
            UPDATE bonsai.git_changes
            SET promotion_state = 'rejected', evidence = evidence || %s
            WHERE job_id = %s
            """,
            (json.dumps(report), candidate.job_id),
        )
        _event(connection, "promotion.rejected", "job", candidate.job_id, report)


def _record_retry(candidate: Candidate, error: str) -> None:
    payload = {"error": error[-4_000:]}
    with db_connection() as connection, connection.transaction():
        connection.execute(
            """
            UPDATE bonsai.git_changes
            SET promotion_state = 'draft', evidence = evidence || %s
            WHERE job_id = %s
            """,
            (json.dumps({"last_retry": payload}), candidate.job_id),
        )
        _event(connection, "promotion.retry_scheduled", "job", candidate.job_id, payload)


def _promote(candidate: Candidate, report: dict[str, Any]) -> None:
    settings = get_settings()
    trusted_repo = Path(settings.trusted_repo)
    trusted_head = _git(trusted_repo, "rev-parse", "HEAD")
    if trusted_head != candidate.base_commit:
        raise RuntimeError(f"trusted checkout moved from baseline: {trusted_head}")
    bundle_ref = _bundle_ref(candidate.bundle_path, candidate.candidate_commit)
    local_ref = f"refs/remotes/bonsai-candidate/{candidate.job_id}"
    _git(trusted_repo, "fetch", "--no-tags", str(candidate.bundle_path), f"{bundle_ref}:{local_ref}")
    _git(trusted_repo, "merge-base", "--is-ancestor", candidate.base_commit, candidate.candidate_commit)
    _git(
        trusted_repo,
        "push",
        settings.github_remote,
        f"{candidate.candidate_commit}:refs/heads/main",
        timeout=180,
    )
    _git(trusted_repo, "merge", "--ff-only", candidate.candidate_commit)
    _git(trusted_repo, "push", "origin", "main", timeout=180)
    report = {**report, "trace_sha256": candidate.trace_sha256, "promoted_at": time.time()}
    with db_connection() as connection, connection.transaction():
        connection.execute(
            """
            UPDATE bonsai.system_state
            SET current_baseline_commit = %s, updated_at = now()
            WHERE singleton = true AND current_baseline_commit = %s
            """,
            (candidate.candidate_commit, candidate.base_commit),
        )
        connection.execute(
            "UPDATE bonsai.jobs SET state = 'completed', updated_at = now() WHERE id = %s",
            (candidate.job_id,),
        )
        connection.execute(
            """
            UPDATE bonsai.git_changes
            SET promotion_state = 'promoted', evidence = evidence || %s, promoted_at = now()
            WHERE job_id = %s
            """,
            (json.dumps(report), candidate.job_id),
        )
        _event(connection, "promotion.completed", "job", candidate.job_id, report)
        _event(
            connection,
            "system.baseline_changed",
            "system",
            "singleton",
            {"commit": candidate.candidate_commit, "job_id": candidate.job_id},
        )


def tick() -> bool:
    settings = get_settings()
    candidate = _next_candidate()
    if candidate is None:
        return False
    try:
        report = inspect_candidate(
            Path(settings.trusted_repo),
            candidate.bundle_path,
            candidate.base_commit,
            candidate.candidate_commit,
            Path(settings.evaluator_dir),
            candidate.job_type,
        )
        _promote(candidate, report)
        print(f"promoted {candidate.job_id} -> {candidate.candidate_commit}", flush=True)
    except GateRejected as exc:
        _record_rejection(candidate, exc.report)
        print(f"rejected {candidate.job_id}: {exc}", flush=True)
    except Exception as exc:
        _record_retry(candidate, repr(exc))
        print(f"promotion retry for {candidate.job_id}: {exc!r}", flush=True)
    return True


def main() -> None:
    settings = get_settings()
    open_pool()
    try:
        while True:
            tick()
            time.sleep(settings.promotion_poll_seconds)
    finally:
        close_pool()


if __name__ == "__main__":
    main()
