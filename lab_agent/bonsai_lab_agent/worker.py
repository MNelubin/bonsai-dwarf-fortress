from __future__ import annotations

import contextlib
import difflib
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .probe_guard import ensure_runtime_ready
from .quality_gate import evaluate_python_quality


class GraphBlockedError(RuntimeError):
    """A bounded graph reached a terminal node and must not retry the same job."""


GUARDED_BASH_PERMISSIONS = {
    "*": "allow",
    "*dwarfort*": "deny",
    "*dfhack-run*": "deny",
    "*/bonsai-df-probe *": "allow",
}


@dataclass(frozen=True)
class Config:
    control_url: str
    lab_token: str
    model: str
    baseline_repo: Path
    baseline_remote: str
    runs_dir: Path
    outbox_dir: Path
    wip_dir: Path
    poll_seconds: int
    harness_timeout: int
    opencode_bin: str
    opencode_config: Path
    ollama_url: str
    context_rollover_tokens: int
    phase_timeout: int
    coding_tool_budget: int
    max_continuations: int
    validation_repair_attempts: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            control_url=os.environ["BONSAI_CONTROL_URL"].rstrip("/"),
            lab_token=os.environ["BONSAI_LAB_TOKEN"],
            model=os.environ.get("BONSAI_MODEL", "ollama/qwen3.6:27b-96k"),
            baseline_repo=Path(os.environ.get("BONSAI_BASELINE_REPO", "/srv/bonsai-agent/workspace")),
            baseline_remote=os.environ.get(
                "BONSAI_BASELINE_REMOTE",
                "https://github.com/MNelubin/bonsai-dwarf-fortress.git",
            ),
            runs_dir=Path(os.environ.get("BONSAI_RUNS_DIR", "/srv/bonsai-agent/runs")),
            outbox_dir=Path(os.environ.get("BONSAI_OUTBOX_DIR", "/srv/bonsai-agent/outbox")),
            wip_dir=Path(os.environ.get("BONSAI_WIP_DIR", "/srv/bonsai-agent/wip")),
            poll_seconds=int(os.environ.get("BONSAI_POLL_SECONDS", "10")),
            harness_timeout=int(os.environ.get("BONSAI_HARNESS_TIMEOUT", "3600")),
            opencode_bin=os.environ.get("BONSAI_OPENCODE_BIN", "/usr/local/bin/opencode"),
            opencode_config=Path(
                os.environ.get("BONSAI_OPENCODE_CONFIG", "/etc/bonsai-agent/opencode.json")
            ),
            ollama_url=os.environ.get("BONSAI_OLLAMA_URL", "http://100.96.0.4:11434").rstrip("/"),
            context_rollover_tokens=int(
                os.environ.get("BONSAI_CONTEXT_ROLLOVER_TOKENS", "55000")
            ),
            phase_timeout=int(os.environ.get("BONSAI_PHASE_TIMEOUT", "420")),
            coding_tool_budget=int(os.environ.get("BONSAI_CODING_TOOL_BUDGET", "24")),
            max_continuations=int(os.environ.get("BONSAI_MAX_CONTINUATIONS", "1")),
            validation_repair_attempts=int(
                os.environ.get("BONSAI_VALIDATION_REPAIR_ATTEMPTS", "2")
            ),
        )


class Api:
    def __init__(self, config: Config):
        self.config = config

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        raw: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, Any]:
        url = f"{self.config.control_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        request = urllib.request.Request(
            url,
            method=method,
            data=data,
            headers={
                "X-Bonsai-Lab-Token": self.config.lab_token,
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"control API {exc.code}: {body[:2000]}") from exc

    def lease(self) -> dict[str, Any] | None:
        status, body = self.request("POST", "/api/v1/jobs/lease")
        return None if status == 204 else body

    def heartbeat(self, job: dict[str, Any], progress: dict[str, Any]) -> None:
        self.request(
            "POST",
            f"/api/v1/jobs/{job['id']}/heartbeat",
            {"progress": progress},
            {"lease_token": job["lease_token"]},
        )

    def worker_heartbeat(
        self,
        status: str,
        current_job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            version = importlib.metadata.version("bonsai-lab-agent")
        except importlib.metadata.PackageNotFoundError:
            version = "development"
        self.request(
            "POST",
            "/api/v1/workers/heartbeat",
            {
                "status": status,
                "model": self.config.model,
                "harness": "opencode",
                "version": version,
                "current_job_id": current_job_id,
                "details": details or {},
            },
        )
    def complete(self, job: dict[str, Any], result: dict[str, Any], artifacts: list[str]) -> None:
        completion_status = "candidate" if result.get("changed") else "rejected"
        self.request(
            "POST",
            f"/api/v1/jobs/{job['id']}/complete",
            {"status": completion_status, "result": result, "artifact_hashes": artifacts},
            {"lease_token": job["lease_token"]},
        )

    def fail(self, job: dict[str, Any], error: str, retryable: bool = True) -> None:
        self.request(
            "POST",
            f"/api/v1/jobs/{job['id']}/fail",
            {"error": error[-20_000:], "retryable": retryable},
            {"lease_token": job["lease_token"]},
        )

    def upload(self, job_id: str, path: Path, media_type: str) -> str:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        self.request(
            "PUT",
            f"/api/v1/artifacts/{digest}",
            query={"job_id": job_id, "media_type": media_type},
            raw=data,
            content_type=media_type,
        )
        return digest


def working_tree_paths(repo: Path) -> set[str]:
    paths: set[str] = set()
    for command in (
        ["git", "-C", str(repo), "diff", "--name-only", "HEAD"],
        ["git", "-C", str(repo), "diff", "--cached", "--name-only", "HEAD"],
        ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
    ):
        paths.update(
            line
            for line in subprocess.check_output(command, text=True).splitlines()
            if line and not is_generated_runtime_path(line)
        )
    return paths


def serializable_working_tree_paths(repo: Path) -> list[str]:
    """Return stable JSON-safe paths for prompts and API payloads."""
    return sorted(working_tree_paths(repo))


def working_tree_fingerprint(repo: Path, prefixes: tuple[str, ...] = ()) -> str:
    """Hash the current candidate content so phase watchdogs can detect real edits."""
    digest = hashlib.sha256()
    for relative in serializable_working_tree_paths(repo):
        if prefixes and not relative.startswith(prefixes):
            continue
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        target = repo / relative
        if target.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(target).encode("utf-8", errors="surrogateescape"))
        elif target.is_file():
            digest.update(b"file\0")
            with target.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"missing\0")
    return digest.hexdigest()


def working_tree_diff(repo: Path) -> tuple[str, str]:
    """Return stat and patch text including untracked files without staging them."""
    untracked = [
        path
        for path in subprocess.check_output(
            ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
            text=True,
        ).splitlines()
        if path and not is_generated_runtime_path(path)
    ]
    if untracked:
        subprocess.run(
            ["git", "-C", str(repo), "add", "--intent-to-add", "--", *untracked],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        diff_stat = subprocess.check_output(
            ["git", "-C", str(repo), "diff", "--stat", "HEAD"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        diff_excerpt = subprocess.check_output(
            ["git", "-C", str(repo), "diff", "--unified=2", "--no-ext-diff", "HEAD"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        if untracked:
            subprocess.run(
                ["git", "-C", str(repo), "reset", "--mixed", "HEAD", "--", *untracked],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
    return diff_stat, diff_excerpt


GENERATED_RUNTIME_PATHS = frozenset(
    {"errorlog.txt", "gamelog.txt", "stderr.log", "stdout.log"}
)
GENERATED_RUNTIME_DIRS = frozenset({".mypy_cache", ".pytest_cache", ".ruff_cache"})
DF_RUNTIME_ROOT = Path("/srv/df-bonsai")
SUPERVISED_DF_UNIT = "bonsai-df-runtime.service"


def is_generated_runtime_path(relative: str) -> bool:
    return relative in GENERATED_RUNTIME_PATHS or any(
        relative == directory or relative.startswith(f"{directory}/")
        for directory in GENERATED_RUNTIME_DIRS
    )


def cleanup_generated_runtime_files(repo: Path) -> list[str]:
    """Remove only known untracked validator/DF artifacts in a disposable run clone."""
    removed: list[str] = []
    for relative in sorted(GENERATED_RUNTIME_PATHS):
        target = repo / relative
        if not target.is_file() or target.is_symlink():
            continue
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", relative],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if tracked:
            continue
        target.unlink()
        removed.append(relative)
    for relative in sorted(GENERATED_RUNTIME_DIRS):
        target = repo / relative
        if not target.is_dir() or target.is_symlink():
            continue
        tracked_files = subprocess.check_output(
            ["git", "-C", str(repo), "ls-files", "--", relative], text=True
        ).strip()
        if tracked_files:
            continue
        shutil.rmtree(target)
        removed.append(relative)
    return removed


def df_runtime_process_ids(
    proc_root: Path = Path("/proc"),
    runtime_root: Path = DF_RUNTIME_ROOT,
) -> set[int]:
    """Return exact dwarfort executables rooted under the managed DF installation."""
    result: set[int] = set()
    root_text = runtime_root.resolve().as_posix().rstrip("/") + "/"
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return result
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            executable = Path(os.readlink(entry / "exe"))
        except (FileNotFoundError, OSError, PermissionError):
            continue
        if executable.name == "dwarfort" and executable.as_posix().startswith(root_text):
            result.add(int(entry.name))
    return result


def supervised_df_runtime_process_ids(
    proc_root: Path = Path("/proc"),
    runtime_root: Path = DF_RUNTIME_ROOT,
    service: str = SUPERVISED_DF_UNIT,
) -> set[int]:
    """Return managed dwarfort PIDs owned by the supervised systemd cgroup."""
    protected: set[int] = set()
    marker = f"/{service}"
    for pid in df_runtime_process_ids(proc_root, runtime_root):
        try:
            cgroup = (proc_root / str(pid) / "cgroup").read_text(
                encoding="utf-8", errors="replace"
            )
        except (FileNotFoundError, OSError, PermissionError):
            continue
        if any(line.rstrip().endswith(marker) for line in cgroup.splitlines()):
            protected.add(pid)
    return protected


def reap_df_probe_processes(grace_seconds: float = 2.0) -> dict[str, Any]:
    """Terminate leaked DF probe executables, escalating to SIGKILL when required."""
    protected = supervised_df_runtime_process_ids()
    targets = sorted(df_runtime_process_ids() - protected - {os.getpid()})
    for pid in targets:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    if targets:
        time.sleep(grace_seconds)
    survivors: list[int] = []
    for pid in targets:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        survivors.append(pid)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    return {"targets": targets, "sigkill": survivors, "protected": sorted(protected)}


WIP_AUTO_PATHS = (
    "knowledge/",
    "bridge/",
    "game_runner/",
    "player/",
    "skills/",
    "curricula/",
    "evaluator_public/",
    "tests/",
    "docs/",
)
WIP_PROTECTED_PATHS = (
    ".github/",
    "control_plane/",
    "db/",
    "evaluator_private/",
    "infra/",
    "security/",
    "lab_agent/",
)
WIP_MAX_PATCH_BYTES = 32 * 1024 * 1024
OBJECTIVE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _safe_wip_path(path: str, job_type: str) -> bool:
    if not path or "\\" in path or "\x00" in path:
        return False
    normalized = PurePosixPath(path)
    if normalized.is_absolute() or normalized.as_posix() != path:
        return False
    if any(part in {"", ".", ".."} for part in normalized.parts):
        return False
    if path.startswith(WIP_PROTECTED_PATHS) or not path.startswith(WIP_AUTO_PATHS):
        return False
    if job_type == "discovery_cycle":
        return path.startswith("knowledge/")
    return not path.startswith("knowledge/")


def _wip_files(config: Config, job: dict[str, Any]) -> tuple[Path, Path] | None:
    objective_id = str(job.get("objective_id") or "")
    job_type = str(job.get("job_type") or "")
    if OBJECTIVE_ID.fullmatch(objective_id) is None or job_type not in {
        "coding_cycle",
        "discovery_cycle",
        "research_cycle",
    }:
        return None
    stem = f"{objective_id}.{job_type}"
    return config.wip_dir / f"{stem}.patch", config.wip_dir / f"{stem}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _trace_event(trace_path: Path | None, payload: dict[str, Any]) -> None:
    if trace_path is None:
        return
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as trace:
        trace.write(json.dumps(payload, ensure_ascii=False) + "\n")


def persist_cross_job_wip(
    config: Config,
    job: dict[str, Any],
    repo: Path,
    base_commit: str,
    phase: str,
    reason: str,
    trace_path: Path | None = None,
) -> dict[str, Any] | None:
    """Persist a safe objective-scoped patch so a later job can resume it."""
    targets = _wip_files(config, job)
    if targets is None or not (repo / ".git").is_dir():
        return None
    patch_path, metadata_path = targets
    changed_paths = sorted(working_tree_paths(repo))
    safe_paths = [path for path in changed_paths if _safe_wip_path(path, str(job["job_type"]))]
    skipped_paths = [path for path in changed_paths if path not in safe_paths]
    if not safe_paths:
        return None

    untracked = set(
        subprocess.check_output(
            ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
            text=True,
        ).splitlines()
    )
    intent_paths = [path for path in safe_paths if path in untracked]
    if intent_paths:
        subprocess.run(
            ["git", "-C", str(repo), "add", "--intent-to-add", "--", *intent_paths],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        patch = subprocess.check_output(
            [
                "git", "-C", str(repo), "diff", "--binary", "--full-index", "HEAD", "--",
                *safe_paths,
            ]
        )
    finally:
        if intent_paths:
            subprocess.run(
                ["git", "-C", str(repo), "reset", "--mixed", "HEAD", "--", *intent_paths],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
    if not patch:
        return None
    if len(patch) > WIP_MAX_PATCH_BYTES:
        raise RuntimeError(f"cross-job WIP patch exceeds {WIP_MAX_PATCH_BYTES} bytes")

    previous: dict[str, Any] = {}
    if metadata_path.is_file():
        try:
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = {}
    digest = hashlib.sha256(patch).hexdigest()
    metadata = {
        "schema_version": 1,
        "objective_id": str(job["objective_id"]),
        "source_job_id": str(job["id"]),
        "source_base_commit": base_commit,
        "job_type": str(job["job_type"]),
        "changed_paths": safe_paths,
        "skipped_paths": skipped_paths,
        "phase": phase,
        "reason": reason[-2000:],
        "patch_sha256": digest,
        "patch_bytes": len(patch),
        "replay_count": int(previous.get("replay_count") or 0),
        "updated_at_unix": time.time(),
    }
    config.wip_dir.mkdir(parents=True, exist_ok=True)
    temporary_patch = patch_path.with_name(f".{patch_path.name}.{os.getpid()}.tmp")
    temporary_patch.write_bytes(patch)
    os.replace(temporary_patch, patch_path)
    _write_json_atomic(metadata_path, metadata)
    event = {
        "type": "cross_job_wip_stored",
        "objective_id": metadata["objective_id"],
        "source_job_id": metadata["source_job_id"],
        "changed_paths": safe_paths,
        "skipped_paths": skipped_paths,
        "patch_sha256": digest,
        "patch_bytes": len(patch),
        "phase": phase,
        "reason": reason[-500:],
    }
    _trace_event(trace_path, event)
    return event


def restore_cross_job_wip(
    config: Config,
    job: dict[str, Any],
    repo: Path,
    trace_path: Path | None = None,
) -> dict[str, Any] | None:
    """Restore the latest safe WIP for this objective onto a fresh trusted baseline."""
    targets = _wip_files(config, job)
    if targets is None:
        return None
    patch_path, metadata_path = targets
    if not patch_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "invalid_metadata", "error": repr(exc)[-500:]}
    patch = patch_path.read_bytes()
    if hashlib.sha256(patch).hexdigest() != metadata.get("patch_sha256"):
        return {"status": "digest_mismatch", "source_job_id": metadata.get("source_job_id")}
    changed_paths = metadata.get("changed_paths") or []
    if not isinstance(changed_paths, list) or not all(
        isinstance(path, str) and _safe_wip_path(path, str(metadata.get("job_type") or ""))
        for path in changed_paths
    ):
        return {"status": "unsafe_metadata", "source_job_id": metadata.get("source_job_id")}

    reverse = subprocess.run(
        ["git", "-C", str(repo), "apply", "--reverse", "--check", str(patch_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if reverse.returncode == 0:
        patch_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        event = {
            "type": "cross_job_wip_cleared",
            "status": "already_in_baseline",
            "source_job_id": metadata.get("source_job_id"),
            "changed_paths": changed_paths,
        }
        _trace_event(trace_path, event)
        return event

    if metadata.get("job_type") != job.get("job_type"):
        event = {
            "type": "cross_job_wip_deferred",
            "status": "job_type_mismatch",
            "stored_job_type": metadata.get("job_type"),
            "current_job_type": job.get("job_type"),
            "source_job_id": metadata.get("source_job_id"),
        }
        _trace_event(trace_path, event)
        return event

    check = subprocess.run(
        ["git", "-C", str(repo), "apply", "--check", str(patch_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check.returncode == 0:
        applied = subprocess.run(
            ["git", "-C", str(repo), "apply", str(patch_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        applied = subprocess.run(
            ["git", "-C", str(repo), "apply", "--3way", str(patch_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    if applied.returncode != 0:
        # prepare_run creates a disposable clean clone, so returning it to HEAD is safe.
        subprocess.run(
            ["git", "-C", str(repo), "reset", "--hard", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "clean", "-fd"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        event = {
            "type": "cross_job_wip_conflict",
            "status": "apply_failed",
            "source_job_id": metadata.get("source_job_id"),
            "changed_paths": changed_paths,
            "error": applied.stdout[-2000:],
        }
        _trace_event(trace_path, event)
        return event

    subprocess.run(
        ["git", "-C", str(repo), "reset", "--mixed", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    metadata["replay_count"] = int(metadata.get("replay_count") or 0) + 1
    metadata["last_restored_job_id"] = str(job["id"])
    metadata["last_restored_at_unix"] = time.time()
    _write_json_atomic(metadata_path, metadata)
    event = {
        "type": "cross_job_wip_restored",
        "status": "restored",
        "source_job_id": metadata.get("source_job_id"),
        "source_base_commit": metadata.get("source_base_commit"),
        "changed_paths": sorted(working_tree_paths(repo)),
        "patch_sha256": metadata.get("patch_sha256"),
        "replay_count": metadata["replay_count"],
    }
    _trace_event(trace_path, event)
    return event


def discovery_needs_synthesis(repo: Path) -> bool:
    changed_paths = working_tree_paths(repo)
    index = repo / "knowledge" / "INDEX.md"
    focused_root = repo / "knowledge" / "dfhack"
    focused_notes = (
        [
            path
            for path in focused_root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".json"}
        ]
        if focused_root.is_dir()
        else []
    )
    return (
        not changed_paths
        or any(not path.startswith("knowledge/") for path in changed_paths)
        or not index.is_file()
        or not focused_notes
    )


def trace_ended_with_degenerate_stop(trace_path: Path) -> bool:
    """Detect an OpenCode turn that produced only an immediate tiny stop response."""
    if not trace_path.is_file():
        return False
    last_finish: dict[str, Any] | None = None
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "step_finish":
            last_finish = event
    if last_finish is None:
        return False
    part = last_finish.get("part") or {}
    tokens = part.get("tokens") or {}
    output_tokens = tokens.get("output")
    return (
        part.get("reason") == "stop"
        and isinstance(output_tokens, int)
        and output_tokens <= 4
    )


def trace_has_live_game_probe(trace_path: Path, phase: str | None = None) -> bool:
    """Require a completed trusted-wrapper result, optionally within one phase."""
    if not trace_path.is_file():
        return False
    current_phase = "opencode"
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "harness_phase":
            current_phase = str(event.get("phase") or "")
            continue
        if phase is not None and current_phase != phase:
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        if part.get("tool") != "bash":
            continue
        state = part.get("state") or {}
        if state.get("status") != "completed":
            continue
        tool_input = state.get("input") or {}
        command = " ".join(str(value) for value in tool_input.values()).lower()
        if "bonsai-df-probe" not in command:
            continue
        output = str((state.get("metadata") or {}).get("output") or state.get("output") or "")
        for output_line in output.splitlines():
            if not output_line.startswith("BONSAI_PROBE_RESULT "):
                continue
            try:
                result = json.loads(output_line.removeprefix("BONSAI_PROBE_RESULT "))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(result.get("exit"), int)
                and isinstance(result.get("timed_out"), bool)
                and result.get("runtime_ready") is True
            ):
                return True
    return False


def trace_phase_tool_use_count(trace_path: Path, phase: str) -> int:
    """Count tools only within one harness phase, not across an appended trace."""
    if not trace_path.is_file():
        return 0
    current_phase = "opencode"
    count = 0
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "harness_phase":
            current_phase = str(event.get("phase") or "")
        elif event.get("type") == "tool_use" and current_phase == phase:
            count += 1
    return count


def trace_latest_input_tokens(trace_path: Path) -> int:
    """Return the most recent OpenCode step input size for context rollover."""
    if not trace_path.is_file():
        return 0
    latest = 0
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "step_finish":
            continue
        tokens = ((event.get("part") or {}).get("tokens") or {})
        input_tokens = tokens.get("input")
        if isinstance(input_tokens, int):
            latest = input_tokens
    return latest


def trace_phase_latest_input_tokens(trace_path: Path, phase: str) -> int:
    """Return the latest input size from only the requested fresh process phase."""
    if not trace_path.is_file():
        return 0
    current_phase = "opencode"
    latest = 0
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "harness_phase":
            current_phase = str(event.get("phase") or "")
            continue
        if event.get("type") != "step_finish" or current_phase != phase:
            continue
        tokens = ((event.get("part") or {}).get("tokens") or {})
        input_tokens = tokens.get("input")
        if isinstance(input_tokens, int):
            latest = input_tokens
    return latest


def compact_phase_checkpoint(
    repo: Path,
    trace_path: Path,
    phase: str,
    reason: str,
    previous_error: str = "",
) -> dict[str, Any]:
    """Build a deterministic, tool-free handoff for a fresh OpenCode process."""
    current_phase = "opencode"
    phase_events: list[dict[str, Any]] = []
    if trace_path.is_file():
        for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "harness_phase":
                current_phase = str(event.get("phase") or "")
                continue
            if current_phase == phase:
                phase_events.append(event)

    evidence: list[dict[str, str]] = []
    todo: Any = None
    for event in phase_events:
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        state = part.get("state") or {}
        tool_input = state.get("input") or {}
        if part.get("tool") == "todowrite":
            todo = tool_input.get("todos")
        output = str((state.get("metadata") or {}).get("output") or state.get("output") or "")
        evidence.append(
            {
                "tool": str(part.get("tool") or ""),
                "input": json.dumps(tool_input, ensure_ascii=False)[:1200],
                "output": output[-1600:],
            }
        )

    changed = serializable_working_tree_paths(repo)
    diff_stat, diff_excerpt = working_tree_diff(repo)
    return {
        "from_phase": phase,
        "stop_reason": reason,
        "previous_gate_error": previous_error[-4000:],
        "changed_paths": changed,
        "diff_stat": diff_stat[-4000:],
        "diff_excerpt": diff_excerpt[:14000],
        "todo": todo,
        "recent_evidence": evidence[-8:],
        "live_probe_observed": trace_has_live_game_probe(trace_path),
        "latest_phase_input_tokens": trace_phase_latest_input_tokens(trace_path, phase),
    }


def store_external_checkpoint(
    repo: Path,
    trace_path: Path,
    phase: str,
    reason: str,
    previous_error: str = "",
) -> dict[str, Any]:
    checkpoint = compact_phase_checkpoint(repo, trace_path, phase, reason, previous_error)
    checkpoint_path = repo.parent / f"checkpoint-{phase}.json"
    checkpoint_path.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with trace_path.open("a", encoding="utf-8") as trace:
        trace.write(
            json.dumps(
                {
                    "type": "external_checkpoint",
                    "phase": phase,
                    "path": checkpoint_path.name,
                    "changed_paths": checkpoint["changed_paths"],
                    "stop_reason": reason,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return checkpoint


def validate_coding_candidate(repo: Path) -> dict[str, Any]:
    """Run harness-owned checks after the model's final edit, so evidence cannot be stale."""
    commands: list[dict[str, Any]] = []

    diff_check = subprocess.run(
        ["git", "-C", str(repo), "diff", "--check"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    commands.append(
        {"name": "git_diff_check", "exit_code": diff_check.returncode, "output": diff_check.stdout[-8000:]}
    )

    changed_python = [
        str(repo / path)
        for path in serializable_working_tree_paths(repo)
        if path.endswith(".py") and (repo / path).is_file()
    ]
    if changed_python:
        compile_check = subprocess.run(
            [sys.executable, "-m", "py_compile", *changed_python],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        commands.append(
            {"name": "py_compile", "exit_code": compile_check.returncode, "output": compile_check.stdout[-12000:]}
        )

    targets = [name for name in ("tests", "evaluator_public") if (repo / name).is_dir()]
    if targets:
        public_tests = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *targets],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        commands.append(
            {"name": "public_pytest", "exit_code": public_tests.returncode, "output": public_tests.stdout[-20000:]}
        )
    else:
        commands.append({"name": "public_pytest", "exit_code": 2, "output": "no public test directory"})

    quality = evaluate_python_quality(
        repo,
        "HEAD",
        serializable_working_tree_paths(repo),
    )
    commands.append(
        {
            "name": "python_quality_gate",
            "exit_code": 0 if quality["ok"] else 1,
            "output": json.dumps(quality, ensure_ascii=False)[-24000:],
        }
    )

    return {
        "ok": all(command["exit_code"] == 0 for command in commands),
        "commands": commands,
        "quality": quality,
    }


CODING_CONTEXT_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:bridge|game_runner|player|skills|curricula|tests|"
    r"evaluator_public)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\."
    r"(?:py|lua|md|json|toml|yaml|yml))"
)
CODING_CONTEXT_SUFFIXES = frozenset({".py", ".lua", ".md", ".json", ".toml", ".yaml", ".yml"})
CODING_GRAPH_ROOTS = (
    "bridge/", "game_runner/", "player/", "skills/", "curricula/", "tests/", "evaluator_public/"
)
CODING_CONTEXT_MAX_FILE_CHARS = 18_000
CODING_CONTEXT_MAX_CHARS = 60_000


def _normalized_edit_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def unique_fuzzy_edit_span(
    current: str, old: str, new: str, path: str
) -> tuple[int, int, float] | None:
    """Resolve one unambiguous near-match while keeping exact paths and validation gates."""
    if not path.endswith(".py") or len(old) < 80:
        return None
    symbol = re.search(r"(?m)^[ \t]*(?:async[ \t]+)?def[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*\(", old)
    if symbol is None:
        return None
    name = symbol.group(1)
    replacement_symbol = re.search(
        r"(?m)^[ \t]*(?:async[ \t]+)?def[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*\(",
        new,
    )
    if replacement_symbol is None or replacement_symbol.group(1) != name:
        return None
    definitions = list(
        re.finditer(
            rf"(?m)^(?P<indent>[ \t]*)(?:async[ \t]+)?def[ \t]+{re.escape(name)}[ \t]*\(",
            current,
        )
    )
    if len(definitions) != 1:
        return None
    definition = definitions[0]
    start = definition.start()
    indent_width = len(definition.group("indent").expandtabs(4))
    end = len(current)
    for candidate in re.finditer(r"(?m)^(?P<indent>[ \t]*)(?:async[ \t]+)?def[ \t]+", current[definition.end():]):
        candidate_indent = len(candidate.group("indent").expandtabs(4))
        if candidate_indent <= indent_width:
            end = definition.end() + candidate.start()
            break
    actual = current[start:end].rstrip()
    score = difflib.SequenceMatcher(
        None,
        _normalized_edit_text(old),
        _normalized_edit_text(actual),
        autojunk=False,
    ).ratio()
    if score < 0.45:
        return None
    return start, start + len(actual), score


def select_coding_context(repo: Path, objective: dict[str, Any]) -> dict[str, str]:
    """Build a bounded, deterministic source packet for a tool-free coding node."""
    objective_text = json.dumps(objective, ensure_ascii=False)
    tracked = set(
        subprocess.check_output(
            ["git", "-C", str(repo), "ls-files"], text=True, errors="replace"
        ).splitlines()
    )
    selected: list[str] = []

    def add(path: str) -> None:
        target = repo / path
        if (
            path not in selected
            and path in tracked | working_tree_paths(repo)
            and target.is_file()
            and not target.is_symlink()
            and target.suffix.lower() in CODING_CONTEXT_SUFFIXES
        ):
            selected.append(path)

    for path in serializable_working_tree_paths(repo):
        add(path)
    for match in CODING_CONTEXT_PATH.finditer(objective_text):
        add(match.group(1))

    symbols = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]{3,})`", objective_text))
    symbols.update(re.findall(r"\b(_[A-Za-z][A-Za-z0-9_]{3,})\b", objective_text))
    for symbol in sorted(symbols)[:12]:
        matches = subprocess.run(
            ["git", "-C", str(repo), "grep", "-l", "-F", "--", symbol],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        if matches.returncode not in {0, 1}:
            continue
        for path in matches.stdout.splitlines()[:6]:
            if path.startswith(WIP_AUTO_PATHS):
                add(path)

    stems = {PurePosixPath(path).stem.removeprefix("test_") for path in selected}
    for path in sorted(tracked):
        if not path.startswith(("tests/", "evaluator_public/")):
            continue
        if any(stem and stem in PurePosixPath(path).stem for stem in stems):
            add(path)
    add("knowledge/INDEX.md")

    packet: dict[str, str] = {}
    remaining = CODING_CONTEXT_MAX_CHARS
    for path in selected:
        if remaining <= 0:
            break
        content = (repo / path).read_text(encoding="utf-8", errors="replace")
        if len(content) > CODING_CONTEXT_MAX_FILE_CHARS:
            half = CODING_CONTEXT_MAX_FILE_CHARS // 2
            content = content[:half] + "\n[... bounded context omitted ...]\n" + content[-half:]
        content = content[:remaining]
        if content:
            packet[path] = content
            remaining -= len(content)
    return packet


def apply_coding_graph_edits(repo: Path, payload: dict[str, Any]) -> list[str]:
    """Validate exact replacements first, then atomically materialize the graph proposal."""
    edits = payload.get("edits")
    if not isinstance(edits, list) or not 1 <= len(edits) <= 20:
        raise ValueError("coding graph must return between 1 and 20 exact edits")
    grouped: dict[str, list[tuple[int, str, str]]] = {}
    staged: dict[str, str] = {}
    changed: set[str] = set()
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise ValueError(f"edit {index} is not an object")
        path = edit.get("path")
        old = edit.get("old")
        new = edit.get("new")
        if not all(isinstance(value, str) for value in (path, old, new)):
            raise ValueError(f"edit {index} path/old/new must be strings")
        assert isinstance(path, str) and isinstance(old, str) and isinstance(new, str)
        if (
            not _safe_wip_path(path, "coding_cycle")
            or not path.startswith(CODING_GRAPH_ROOTS)
            or Path(path).suffix.lower() not in CODING_CONTEXT_SUFFIXES
        ):
            raise ValueError(f"edit {index} has unsafe path: {path}")
        target = repo / path
        if target.is_symlink():
            raise ValueError(f"edit {index} targets a symlink: {path}")
        grouped.setdefault(path, []).append((index, old, new))

    for path, file_edits in grouped.items():
        target = repo / path
        exists = target.is_file()
        current = target.read_text(encoding="utf-8") if exists else ""
        if not exists:
            if len(file_edits) != 1 or file_edits[0][1] != "":
                raise ValueError(f"new file requires exactly one empty-old edit: {path}")
            updated = file_edits[0][2]
        else:
            replacements: list[tuple[int, int, str, int]] = []
            for index, old, new in file_edits:
                if old == "":
                    raise ValueError(f"edit {index} empty old is only valid for a new file: {path}")
                occurrences = current.count(old)
                if occurrences == 0 and new and current.count(new) == 1:
                    continue  # Idempotent retry of an edit already present in restored WIP.
                if occurrences == 0:
                    fuzzy = unique_fuzzy_edit_span(current, old, new, path)
                    if fuzzy is not None:
                        start, end, _score = fuzzy
                        replacements.append((start, end, new, index))
                        continue
                if occurrences != 1:
                    raise ValueError(
                        f"edit {index} old text occurs {occurrences} times instead of once: {path}"
                    )
                start = current.index(old)
                replacements.append((start, start + len(old), new, index))
            ordered = sorted(replacements)
            for left, right in zip(ordered, ordered[1:]):
                if left[1] > right[0]:
                    raise ValueError(
                        f"edits {left[3]} and {right[3]} overlap in current file: {path}"
                    )
            updated = current
            for start, end, new, _index in reversed(ordered):
                updated = updated[:start] + new + updated[end:]
        if len(updated.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError(f"edits would exceed the 2 MiB file limit: {path}")
        staged[path] = updated
        if updated != current:
            changed.add(path)
    if not changed:
        raise ValueError("coding graph proposal does not change any file")
    for path, content in staged.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return sorted(changed)


def coding_graph_decision(repo: Path, validation: dict[str, Any] | None) -> str:
    """Route solely from durable artifacts and validator output, never chat wording."""
    if (
        has_executable_candidate_change(repo)
        and has_public_test_change(repo)
        and validation is not None
        and validation.get("ok") is True
    ):
        return "promote"
    return "draft" if not working_tree_paths(repo) else "repair"


def _coding_context_markdown(packet: dict[str, str]) -> str:
    return "\n\n".join(
        f"--- FILE {path} ---\n{content}\n--- END FILE {path} ---"
        for path, content in packet.items()
    )


def request_coding_graph_edits(
    config: Config,
    api: Api,
    job: dict[str, Any],
    repo: Path,
    objective: dict[str, Any],
    diagnostics: str,
    phase: str,
    started: float,
) -> dict[str, Any]:
    """Run one tool-free model node whose only output is exact controller-applied edits."""
    context_packet = select_coding_context(repo, objective)
    diff_stat, diff_excerpt = working_tree_diff(repo)
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                    },
                    "required": ["path", "old", "new"],
                },
            },
        },
        "required": ["summary", "edits"],
    }
    prompt = f"""
You are the PATCH node in a deterministic coding graph. You have no tools. Produce the smallest
correct implementation and deterministic public test for the objective using only the supplied source
packet, current diff, and validator diagnostics. Return schema-valid JSON only.

Each edit is an exact replacement: `old` must be copied byte-for-byte from the current file and occur
exactly once; `new` replaces it. Use old="" only to create a new file. Multiple edits to one file must be
independent, non-overlapping replacements against the supplied current version. Paths are limited to
bridge/, game_runner/, player/, skills/, curricula/, tests/, and
evaluator_public/. Never edit knowledge/, infrastructure, agent/controller code, or generated files.
Do not return prose instead of edits. Do not weaken tests, add placeholders, swallow errors, or invent
DFHack APIs. Preserve existing public interfaces unless the objective explicitly changes them.

Objective:
{json.dumps(objective, ensure_ascii=False)}

Current diff stat:
{diff_stat[-4000:] or "(clean)"}

Current diff excerpt:
{diff_excerpt[:20_000] or "(clean)"}

Validator/application diagnostics:
{diagnostics[-24_000:] or "No candidate exists yet."}

Bounded source packet:
{_coding_context_markdown(context_packet)}
""".strip()
    request_body = json.dumps(
        {
            "model": config.model.removeprefix("ollama/"),
            "stream": False,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise software patch generator inside a validated state graph.",
                },
                {"role": "user", "content": prompt},
            ],
            "format": schema,
            "options": {"temperature": 0.1, "num_ctx": 65536, "num_predict": 6144},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.ollama_url}/api/chat",
        method="POST",
        data=request_body,
        headers={"Content-Type": "application/json"},
    )

    def fetch() -> bytes:
        with urllib.request.urlopen(request, timeout=max(300, config.phase_timeout)) as response:
            return response.read(4 * 1024 * 1024 + 1)

    _trace_event(
        repo.parent / "opencode-trace.jsonl",
        {"type": "coding_graph_node_started", "phase": phase, "context_paths": list(context_packet)},
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fetch)
        while True:
            try:
                raw = future.result(timeout=25)
                break
            except FutureTimeout:
                elapsed = round(time.monotonic() - started)
                progress = {"phase": phase, "model": config.model, "elapsed_seconds": elapsed}
                api.heartbeat(job, progress)
                api.worker_heartbeat("running", str(job["id"]), progress)
    if len(raw) > 4 * 1024 * 1024:
        raise RuntimeError("coding graph response exceeded 4 MiB")
    response_payload = json.loads(raw)
    content = response_payload.get("message", {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("coding graph response has no message content")
    payload = json.loads(content)
    _trace_event(
        repo.parent / "opencode-trace.jsonl",
        {
            "type": "coding_graph_node_completed",
            "phase": phase,
            "summary": str(payload.get("summary") or "")[:1000],
            "proposed_paths": [
                edit.get("path") for edit in payload.get("edits", []) if isinstance(edit, dict)
            ],
        },
    )
    return payload


def run_coding_graph(
    config: Config,
    api: Api,
    job: dict[str, Any],
    repo: Path,
    base_commit: str,
    objective: dict[str, Any],
    previous_error: str,
    trace_path: Path,
    started: float,
) -> tuple[str, str]:
    """Execute bounded draft/apply/validate/repair nodes with durable routing state."""
    diagnostics = previous_error[-12_000:]
    validation: dict[str, Any] | None = None
    if working_tree_paths(repo):
        validation = validate_coding_candidate(repo)
        diagnostics = json.dumps(validation, ensure_ascii=False)[-24_000:]
    decision = coding_graph_decision(repo, validation)
    for attempt in range(1, 4):
        if decision == "promote":
            return "coding_graph_promote", "validated"
        phase = f"coding_graph_{decision}_{attempt}"
        progress = {
            "phase": phase,
            "model": config.model,
            "attempt": attempt,
            "changed_paths": serializable_working_tree_paths(repo),
        }
        api.heartbeat(job, progress)
        api.worker_heartbeat("running", str(job["id"]), progress)
        try:
            proposal = request_coding_graph_edits(
                config, api, job, repo, objective, diagnostics, phase, started
            )
            applied_paths = apply_coding_graph_edits(repo, proposal)
            persist_cross_job_wip(
                config, job, repo, base_commit, phase, "graph_edit_applied", trace_path
            )
            validation = validate_coding_candidate(repo)
            diagnostics = json.dumps(validation, ensure_ascii=False)[-24_000:]
            decision = coding_graph_decision(repo, validation)
            state = {
                "schema_version": 1,
                "phase": phase,
                "attempt": attempt,
                "decision": decision,
                "applied_paths": applied_paths,
                "changed_paths": serializable_working_tree_paths(repo),
                "validation": validation,
            }
        except Exception as exc:
            diagnostics = f"Proposal/application error: {exc!r}"
            decision = "repair" if working_tree_paths(repo) else "draft"
            state = {
                "schema_version": 1,
                "phase": phase,
                "attempt": attempt,
                "decision": decision,
                "changed_paths": serializable_working_tree_paths(repo),
                "error": diagnostics[-4000:],
            }
        checkpoint_path = repo.parent / "checkpoint-coding-graph.json"
        _write_json_atomic(checkpoint_path, state)
        _trace_event(trace_path, {"type": "coding_graph_transition", **state})
        if decision == "promote":
            return phase, "validated"
    raise GraphBlockedError(
        "coding graph reached cooldown after three bounded proposals; last diagnostics: "
        + diagnostics[-6000:]
    )


def finalize_graph_candidate(
    config: Config,
    api: Api,
    job: dict[str, Any],
    repo: Path,
    base_commit: str,
    branch: str,
    trace_path: Path,
    started: float,
    last_phase: str,
) -> tuple[dict[str, Any], list[str]]:
    """Commit, bundle, and upload a candidate produced by the deterministic graph."""
    trace_text = trace_path.read_text(encoding="utf-8", errors="replace")
    status = run("git status --porcelain", repo, 30)["output"].strip()
    if status:
        persist_cross_job_wip(
            config, job, repo, base_commit, last_phase, "candidate_ready", trace_path
        )
        subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
        try:
            commit_title, commit_body = generate_commit_description(config, job, repo)
        except Exception as exc:
            print(f"commit description fallback: {exc}", flush=True)
            commit_title, commit_body = normalize_commit_description({}, str(job["job_type"]))
        trailers = f"Bonsai-Job-Type: {job['job_type']}\nBonsai-Job-ID: {job['id']}"
        subprocess.run(
            [
                "git", "-C", str(repo), "commit", "-m", commit_title,
                "-m", commit_body, "-m", trailers,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    candidate_commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    changed = candidate_commit != base_commit
    changed_paths = (
        subprocess.check_output(
            ["git", "-C", str(repo), "diff", "--name-only", f"{base_commit}..{candidate_commit}"],
            text=True,
        ).splitlines()
        if changed
        else []
    )
    artifacts: list[str] = []
    if changed:
        subprocess.run(
            ["git", "-C", str(repo), "update-ref", f"refs/heads/{branch}", candidate_commit],
            check=True,
        )
        config.outbox_dir.mkdir(parents=True, exist_ok=True)
        bundle = config.outbox_dir / f"{job['id']}.bundle"
        subprocess.run(
            ["git", "-C", str(repo), "bundle", "create", str(bundle), f"refs/heads/{branch}"],
            check=True,
        )
        artifacts.append(api.upload(str(job["id"]), bundle, "application/x-git-bundle"))
    checkpoint_files = sorted(repo.parent.glob("checkpoint-*.json"))
    for checkpoint_file in checkpoint_files:
        artifacts.append(api.upload(str(job["id"]), checkpoint_file, "application/json"))
    artifacts.append(api.upload(str(job["id"]), trace_path, "application/x-ndjson"))
    summary = trace_text[-4000:].strip() or "Coding graph completed without textual summary"
    return (
        {
            "summary": summary,
            "job_type": job["job_type"],
            "harness": "coding_graph",
            "model": config.model,
            "base_commit": base_commit,
            "candidate_commit": candidate_commit,
            "branch": branch,
            "changed": changed,
            "changed_paths": changed_paths,
            "candidate_requested": changed,
            "external_checkpoints": [path.name for path in checkpoint_files],
            "duration_seconds": round(time.monotonic() - started, 2),
        },
        artifacts,
    )


def trace_has_test_execution(trace_path: Path) -> bool:
    """Detect an actual public test command, not merely reading a test file."""
    if not trace_path.is_file():
        return False
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        if part.get("tool") != "bash":
            continue
        tool_input = ((part.get("state") or {}).get("input") or {})
        command = " ".join(str(value) for value in tool_input.values()).lower()
        if any(marker in command for marker in ("pytest", "unittest", "test_bridge_contract.py")):
            return True
    return False


def trace_has_successful_test(trace_path: Path) -> bool:
    """Require positive test-run evidence; shell pipelines can mask a failing exit code."""
    if not trace_path.is_file():
        return False
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        state = part.get("state") or {}
        if part.get("tool") != "bash" or state.get("status") != "completed":
            continue
        tool_input = state.get("input") or {}
        command = " ".join(str(value) for value in tool_input.values()).lower()
        if not any(marker in command for marker in ("pytest", "unittest", "test_bridge_contract.py")):
            continue
        output = str((state.get("metadata") or {}).get("output") or state.get("output") or "")
        lowered = output.lower()
        if " passed" in lowered and not any(
            marker in lowered for marker in (" failed", " error", "traceback", "no module named")
        ):
            return True
    return False


def has_public_test_change(repo: Path) -> bool:
    """Coding candidates must carry reviewable public test/evaluation evidence."""
    return any(
        path == "tests"
        or path.startswith("tests/")
        or path == "evaluator_public"
        or path.startswith("evaluator_public/")
        for path in working_tree_paths(repo)
    )


def has_executable_candidate_change(repo: Path) -> bool:
    """Return true only when a coding candidate changes an implementation area."""
    implementation_roots = ("bridge/", "game_runner/", "player/", "skills/", "curricula/")
    return any(path.startswith(implementation_roots) for path in working_tree_paths(repo))


def normalize_commit_description(payload: dict[str, Any], job_type: str) -> tuple[str, str]:
    """Validate model-authored commit prose and provide deterministic fallbacks."""
    raw_title = str(payload.get("title") or "").replace("\r", " ").replace("\n", " ")
    title = " ".join(raw_title.split()).strip(" .")[:72]
    if not title:
        title = f"Advance {job_type.replace('_', ' ')}"
    raw_body = str(payload.get("body") or "").replace("\r\n", "\n").strip()
    body_lines = [
        line for line in raw_body.splitlines()
        if not line.lower().startswith(("bonsai-job-type:", "bonsai-job-id:"))
    ]
    body = "\n".join(body_lines).strip()[:1200]
    if not body:
        body = "Describe and verify the repository changes produced by the autonomous job."
    return title, body


def generate_commit_description(config: Config, job: dict[str, Any], repo: Path) -> tuple[str, str]:
    """Call Ollama without tools after the coding agent has finished its work."""
    diff_stat = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--cached", "--stat"], text=True
    )[-6000:]
    name_status = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--cached", "--name-status"], text=True
    )[-4000:]
    diff_excerpt = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--cached", "--unified=1", "--no-ext-diff"],
        text=True,
        errors="replace",
    )[:18000]
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["title", "body"],
    }
    objective = str((job.get("payload") or {}).get("objective") or "")[:2000]
    prompt = f"""
Write a clear Git commit title and body for the completed repository change below.
The title must be imperative, specific, at most 72 characters, and must not contain a job type or ID.
The body must explain what changed and why in 2-5 concise sentences. Do not invent tests or behavior not
visible in the diff. Return only schema-valid JSON. This is a tool-free postprocessing task.

Objective: {objective}
Job type: {job['job_type']}

Changed files:
{name_status}

Diff stat:
{diff_stat}

Diff excerpt:
{diff_excerpt}
""".strip()
    request_body = json.dumps(
        {
            "model": config.model.removeprefix("ollama/"),
            "stream": False,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": "You write precise Git commit messages from supplied diffs.",
                },
                {"role": "user", "content": prompt},
            ],
            "format": schema,
            "options": {"temperature": 0.1, "num_ctx": 32768, "num_predict": 512},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.ollama_url}/api/chat",
        method="POST",
        data=request_body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        response_payload = json.loads(response.read(256 * 1024 + 1))
    content = response_payload.get("message", {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("commit description response has no message content")
    return normalize_commit_description(json.loads(content), str(job["job_type"]))


DISCOVERY_NOTE_PATH = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}\.md$")


def write_discovery_bundle(repo: Path, payload: dict[str, Any]) -> str:
    note_path = payload.get("note_path")
    index_markdown = payload.get("index_markdown")
    note_markdown = payload.get("note_markdown")
    if not isinstance(note_path, str) or DISCOVERY_NOTE_PATH.fullmatch(note_path) is None:
        raise ValueError("structured discovery returned an unsafe note_path")
    if not isinstance(index_markdown, str) or not 50 <= len(index_markdown) <= 50_000:
        raise ValueError("structured discovery returned an invalid INDEX.md")
    if not isinstance(note_markdown, str) or not 500 <= len(note_markdown) <= 100_000:
        raise ValueError("structured discovery returned an invalid focused note")
    if "53.15" not in note_markdown or "53.15-r2" not in note_markdown:
        raise ValueError("structured discovery note lacks exact version markers")
    if not any(marker in note_markdown for marker in ("VERIFIED", "INFERRED", "OPEN")):
        raise ValueError("structured discovery note lacks claim tags or exact version markers")
    relative_target = f"dfhack/{note_path}"
    if relative_target not in index_markdown:
        raise ValueError("structured discovery index does not link the focused note")
    clean_index = "\n".join(line.rstrip() for line in index_markdown.splitlines()).rstrip() + "\n"
    clean_note = "\n".join(line.rstrip() for line in note_markdown.splitlines()).rstrip() + "\n"
    knowledge = repo / "knowledge"
    focused = knowledge / "dfhack"
    focused.mkdir(parents=True, exist_ok=True)
    (knowledge / "INDEX.md").write_text(clean_index, encoding="utf-8")
    (focused / note_path).write_text(clean_note, encoding="utf-8")
    return relative_target


def synthesize_discovery(
    config: Config,
    api: Api,
    job: dict[str, Any],
    repo: Path,
    trace_path: Path,
    started: float,
) -> str:
    trace_text = trace_path.read_text(encoding="utf-8", errors="replace")[-80_000:]
    index_path = repo / "knowledge" / "INDEX.md"
    existing_index = (
        index_path.read_text(encoding="utf-8", errors="replace")[:20_000]
        if index_path.is_file()
        else "(none)"
    )
    schema = {
        "type": "object",
        "properties": {
            "note_path": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}\\.md$"},
            "index_markdown": {"type": "string"},
            "note_markdown": {"type": "string"},
        },
        "required": ["note_path", "index_markdown", "note_markdown"],
    }
    prompt = f"""
Convert the bounded research trace below into a durable Dwarf Fortress knowledge bundle. You have
no tools and must rely only on the trace. Return JSON matching the schema.

Requirements:
- exact target versions: Dwarf Fortress 53.15 and DFHack 53.15-r2;
- note_path is a new mechanic-focused basename such as mechanics-units.md or probe-time-advance.md;
- index_markdown is a complete knowledge/INDEX.md and links the note as dfhack/<note_path>;
- note_markdown is a substantive focused note with every claim visibly tagged VERIFIED, INFERRED,
  or OPEN;
- cite exact source paths or bounded commands/results present in the trace;
- prioritize observed game fields, values, IDs, enums, coordinates, ticks, or state transitions;
- do not produce another generic environment/runtime-structure summary;
- explain implications for reset/observe/act/advance and end with concrete coding recommendations;
- do not claim a probe succeeded unless its result is present; preserve uncertainty as OPEN;
- never include credentials, tokens, binary data, or invented API names.

Existing INDEX.md:
---
{existing_index}
---

Research trace:
---
{trace_text}
---
""".strip()
    request_body = json.dumps(
        {
            "model": config.model.removeprefix("ollama/"),
            "stream": False,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise technical archivist. Output only schema-valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "format": schema,
            "options": {"temperature": 0.1, "num_ctx": 65536, "num_predict": 4096},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.ollama_url}/api/chat",
        method="POST",
        data=request_body,
        headers={"Content-Type": "application/json"},
    )

    def fetch() -> bytes:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.read(2 * 1024 * 1024 + 1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fetch)
        while True:
            try:
                raw = future.result(timeout=25)
                break
            except FutureTimeout as exc:
                elapsed = round(time.monotonic() - started)
                if elapsed > config.harness_timeout:
                    raise TimeoutError(
                        f"structured synthesis exceeded {config.harness_timeout} seconds"
                    ) from exc
                progress = {
                    "phase": "discovery_structured_synthesis",
                    "model": config.model,
                    "elapsed_seconds": elapsed,
                }
                api.heartbeat(job, progress)
                api.worker_heartbeat("running", str(job["id"]), progress)
    if len(raw) > 2 * 1024 * 1024:
        raise RuntimeError("structured discovery response exceeded 2 MiB")
    response_payload = json.loads(raw)
    content = response_payload.get("message", {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("Ollama structured discovery response has no message content")
    note_target = write_discovery_bundle(repo, json.loads(content))
    elapsed = round(time.monotonic() - started)
    api.heartbeat(job, {"phase": "discovery_structured_write", "model": config.model, "elapsed_seconds": elapsed})
    api.worker_heartbeat(
        "running",
        str(job["id"]),
        {"phase": "discovery_structured_write", "elapsed_seconds": elapsed},
    )
    with trace_path.open("a", encoding="utf-8") as trace:
        trace.write(json.dumps({"type": "structured_synthesis", "note": note_target}) + "\n")
    return note_target


def run(command: str, cwd: Path, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.run(
        ["/bin/bash", "-lc", command],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    output = process.stdout
    if len(output) > 30_000:
        output = output[-30_000:]
    return {
        "exit_code": process.returncode,
        "duration_seconds": round(time.monotonic() - started, 2),
        "output": output,
    }


def harness_environment(config: Config, *, implementation_only: bool = False) -> dict[str, str]:
    sensitive_names = {
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "OPENAI_API_KEY",
        "PGPASSWORD",
        "PGPASSFILE",
        "SSH_AUTH_SOCK",
    }
    child_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("BONSAI_")
        and key not in sensitive_names
        and not key.endswith(("_TOKEN", "_PASSWORD", "_SECRET", "_API_KEY"))
    }
    child_env.update(
        {
            "OPENCODE_CONFIG": str(config.opencode_config),
            "OPENCODE_AUTO_SHARE": "false",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_MODELS_FETCH": "true",
            "OPENCODE_DISABLE_CLAUDE_CODE": "true",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    if implementation_only:
        # Inline config has higher precedence than the global/project config.  A denied
        # task permission removes the Task tool from the model's tool description, so a
        # bounded repair phase cannot spend its entire fresh budget on another research
        # subagent.  Editing, bounded reads, shell commands, and tests remain available.
        child_env["OPENCODE_CONFIG_CONTENT"] = json.dumps(
            {
                "permission": {
                    "bash": GUARDED_BASH_PERMISSIONS,
                    "task": "deny",
                    "webfetch": "deny",
                    "websearch": "deny",
                    "skill": "deny",
                    "question": "deny",
                }
            }
        )
    return child_env


def stop_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=10)


def prepare_run(config: Config, job: dict[str, Any]) -> tuple[Path, str, str]:
    run_id = f"{job['id']}-{int(time.time())}"
    run_root = config.runs_dir / run_id
    repo = run_root / "repo"
    run_root.mkdir(parents=True, exist_ok=False)
    requested_base = job.get("base_commit")
    if not requested_base:
        raise RuntimeError("job has no trusted base_commit")
    subprocess.run(
        [
            "git",
            "-C",
            str(config.baseline_repo),
            "fetch",
            "--no-tags",
            config.baseline_remote,
            "main:refs/remotes/bonsai-trusted/main",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=180,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(config.baseline_repo), str(repo)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{requested_base}^{{commit}}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "switch", "--detach", requested_base],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    branch = f"agent/{job['id']}"
    subprocess.run(["git", "-C", str(repo), "switch", "-c", branch], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Bonsai Lab Agent"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "bonsai-agent@local"], check=True)
    return repo, base, branch


def execute_job(config: Config, api: Api, job: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    repo, base_commit, branch = prepare_run(config, job)
    trace_path = repo.parent / "opencode-trace.jsonl"
    cross_job_handoff = restore_cross_job_wip(config, job, repo, trace_path)
    runtime_progress = {"phase": "ensure_runtime_ready", "model": config.model}
    api.heartbeat(job, runtime_progress)
    api.worker_heartbeat("running", str(job["id"]), runtime_progress)
    runtime_readiness = ensure_runtime_ready()
    _trace_event(
        trace_path,
        {"type": "runtime_readiness", "phase": "ensure_runtime_ready", **runtime_readiness},
    )
    if runtime_readiness.get("ready") is not True:
        raise RuntimeError(
            "supervised Dwarf Fortress runtime is unavailable before LLM execution: "
            + str(runtime_readiness.get("error") or runtime_readiness.get("output") or "unknown")[-4000:]
        )
    raw_payload = job.get("payload", {})
    previous_cycle = raw_payload.get("previous_cycle") or {}
    compact_previous = {
        key: value
        for key, value in previous_cycle.items()
        if key != "summary_tail"
    }
    compact_previous["summary_tail"] = str(previous_cycle.get("summary_tail") or "")[-800:]
    previous_error = str(previous_cycle.get("error") or "")
    objective_payload = {
        key: value for key, value in raw_payload.items() if key != "previous_cycle"
    }
    discovery_mode = job.get("job_type") == "discovery_cycle"
    if discovery_mode:
        mode_instructions = """
You are in DISCOVERY MODE. Do not implement or modify executable product code. Your only writable
tree is knowledge/. This is a LIVE GAME ARCHAEOLOGY cycle, not a documentation review.

Choose one concrete, previously unmapped mechanic: calendar/time, pause and advancement, units and
their professions/needs/positions, tiles and materials, items, buildings, jobs, raws/enums, world/save
data, or another observable subsystem. Spend at most two calls reading existing knowledge. Your first
three investigative calls must target actual files or processes under /srv/df-bonsai/current or the
live DF runtime, not this repository.

Run at least one bounded executable probe through the trusted wrapper, for example:
`/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run status`.
Never execute `dwarfort` or `dfhack-run` directly or through shell `timeout`; the game ignores SIGTERM
and leaked earlier probes. The wrapper ensures the supervised headless runtime is ready before connecting.
Capture the wrapper's BONSAI_PROBE_RESULT, stdout/stderr, and extract field names,
enum values, IDs, coordinates, ticks, or state transitions. If a game launch is blocked, the failed
command and its precise blocker are evidence, but `ls`, `file`, or rereading VERSIONS.txt alone are not.

Create a new mechanic-focused note under knowledge/dfhack/ (prefer mechanics-<topic>.md or
probe-<topic>.md) and link it from INDEX.md. Do not rewrite generic environment/runtime-structure notes
unless a new executed probe directly falsifies them. Each claim must be tagged VERIFIED, INFERRED, or
OPEN and cite the exact command/result. End with one smallest executable coding task and its test.
Do not touch bridge/, game_runner/, player/, tests/, docs/, control_plane/, lab_agent/, or infra/.
A prose chat answer with no knowledge/ commit is a rejected cycle.
""".strip()
    else:
        mode_instructions = """
You are in CODING MODE. Read knowledge/INDEX.md and the relevant focused notes before probing the
game. Treat VERIFIED notes as the starting point and explicitly record when reality contradicts
them. Use at most 4 external discovery calls before the first write/edit.

Prefer executable progress over abstractions: run one bounded probe against the real installed game,
then turn its observed fields or failure mode into the smallest reusable bridge/probe/runner change.
All real-runtime commands must use `/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe`; never launch
`dwarfort`, `dfhack-run`, or a shell `timeout` around them directly.
The wrapper starts and checks the supervised headless runtime; do not build ad-hoc launch commands.
If the previous candidate was rejected, repair its exact promotion error before starting new work.
Do not satisfy the cycle with documentation alone. You MUST modify executable implementation, add or
update a deterministic test under tests/ or evaluator_public/, and run it. Do not change knowledge/
in coding mode. A clean git tree or a docs-only diff is a rejected cycle.
""".strip()
    prompt = f"""
Work autonomously as the senior agent for Bonsai Dwarf Fortress.

Objective payload: {json.dumps(objective_payload, ensure_ascii=False)}
Constraints: {json.dumps(job.get('constraints', {}), ensure_ascii=False)}
Bounded previous-cycle handoff: {json.dumps(compact_previous, ensure_ascii=False)}
Cross-job working-tree handoff: {json.dumps(cross_job_handoff, ensure_ascii=False)}

You are root inside an isolated Debian LXC containing Steam Dwarf Fortress 53.15 and DFHack
53.15-r2 at /srv/df-bonsai/current. This repository clone has no GitHub, PostgreSQL, Steam, or
control-plane credentials. Never search for or print secrets. You may inspect the whole lab, run
non-interactive shell commands and game probes, and edit this repository.

Long-term target: a deterministic DFHack bridge with reset/observe/act/advance, reproducible
headless episodes and metrics, curricula, then a tiny CPU inference player. Verify installed DFHack
APIs from actual scripts, docs, source definitions, or controlled probes; do not invent APIs. Never
read binary content. Do not modify protected control_plane/, db/, evaluator_private/, infra/,
security/, .github/, or lab_agent/. Do not add symlinks, submodules, secrets, generated binaries, or
files over 2 MiB.

Keep durable progress in the working tree and todo state. If the context grows too large, the harness
will stop this OpenCode process and continue from that durable state in a fresh bounded phase.
If the cross-job handoff status is `restored`, begin with `git diff --stat` and finish or repair that
existing candidate before starting unrelated work. Do not discard a restored diff merely to start over.

{mode_instructions}

Execution discipline is mandatory:
1. Inspect narrowly with `file`, `find -maxdepth`, `grep -m`, and bounded output; never dump a whole
   binary or directory tree.
2. Before reading any unknown path under /srv/df-bonsai, run `file` on it. Only read known text
   extensions such as .lua, .txt, .md, .json, .proto, .py, or .rst. Never use cat/head on an
   executable, shared object, archive, image, database, or extensionless unknown file.
3. Check `git status --short` before finishing and summarize exact files and verification evidence.
4. Treat a running/high-CPU process as a timeout, not successful evidence. Only the wrapper's terminal
   `BONSAI_PROBE_RESULT` proves a bounded probe completed.
""".strip()

    started = time.monotonic()
    last_heartbeat = 0.0
    requested_wall_time = int((job.get("constraints") or {}).get("wall_time_seconds", config.harness_timeout))
    job_wall_time = min(config.harness_timeout, max(300, requested_wall_time))
    def save_checkpoint(phase: str, reason: str) -> dict[str, Any]:
        checkpoint = store_external_checkpoint(
            repo, trace_path, phase, reason, previous_error
        )
        checkpoint["cross_job_wip"] = persist_cross_job_wip(
            config, job, repo, base_commit, phase, reason, trace_path
        )
        return checkpoint

    def run_harness(
        harness_prompt: str,
        phase: str,
        append: bool,
        max_tool_uses: int | None = None,
        phase_timeout: int | None = None,
        implementation_only: bool = False,
        progress_deadline_tools: int | None = None,
        progress_prefixes: tuple[str, ...] = (),
        probe_deadline_tools: int | None = None,
    ) -> str:
        nonlocal last_heartbeat
        budget_exhausted = False
        controlled_stop_reason: str | None = None
        phase_started = time.monotonic()
        effective_phase_timeout = phase_timeout or config.phase_timeout
        initial_fingerprint = working_tree_fingerprint(repo, progress_prefixes)
        command = [
            config.opencode_bin,
            "run",
            "--auto",
            "--format",
            "json",
            "--model",
            config.model,
            harness_prompt,
        ]
        with trace_path.open("a" if append else "w", encoding="utf-8") as trace:
            if append:
                trace.write(
                    json.dumps(
                        {
                            "type": "harness_phase",
                            "phase": phase,
                            "tool_profile": (
                                "implementation_only" if implementation_only else "general"
                            ),
                        }
                    )
                    + "\n"
                )
                trace.flush()
            pre_reap = reap_df_probe_processes()
            pre_removed = cleanup_generated_runtime_files(repo)
            trace.write(
                json.dumps(
                    {
                        "type": "runtime_cleanup",
                        "phase": phase,
                        "when": "before",
                        "processes": pre_reap,
                        "removed_files": pre_removed,
                    }
                )
                + "\n"
            )
            trace.flush()
            process = subprocess.Popen(
                command,
                cwd=repo,
                env=harness_environment(config, implementation_only=implementation_only),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=trace,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                while process.poll() is None:
                    elapsed = time.monotonic() - started
                    phase_elapsed = time.monotonic() - phase_started
                    if elapsed > job_wall_time:
                        budget_exhausted = True
                        controlled_stop_reason = "job_timeout"
                        stop_process_group(process)
                        break
                    if phase_elapsed > effective_phase_timeout:
                        budget_exhausted = True
                        controlled_stop_reason = "phase_timeout"
                        stop_process_group(process)
                        break
                    if (
                        config.context_rollover_tokens > 0
                        and trace_phase_latest_input_tokens(trace_path, phase)
                        >= config.context_rollover_tokens
                    ):
                        budget_exhausted = True
                        controlled_stop_reason = "context_rollover"
                        stop_process_group(process)
                        break
                    if trace_path.exists():
                        tool_uses = trace_phase_tool_use_count(trace_path, phase)
                        if (
                            probe_deadline_tools is not None
                            and tool_uses >= probe_deadline_tools
                            and not trace_has_live_game_probe(trace_path, phase)
                        ):
                            budget_exhausted = True
                            controlled_stop_reason = "probe_deadline"
                            stop_process_group(process)
                            break
                        if (
                            progress_deadline_tools is not None
                            and tool_uses >= progress_deadline_tools
                            and working_tree_fingerprint(repo, progress_prefixes)
                            == initial_fingerprint
                        ):
                            budget_exhausted = True
                            controlled_stop_reason = (
                                "public_test_deadline"
                                if progress_prefixes
                                else "edit_deadline"
                            )
                            stop_process_group(process)
                            break
                        if max_tool_uses is not None and tool_uses >= max_tool_uses:
                            budget_exhausted = True
                            controlled_stop_reason = "tool_budget"
                            stop_process_group(process)
                            break
                    if elapsed - last_heartbeat >= 35:
                        try:
                            progress = {
                                "phase": phase,
                                "model": config.model,
                                "elapsed_seconds": round(elapsed),
                            }
                            api.heartbeat(job, progress)
                            api.worker_heartbeat("running", str(job["id"]), progress)
                        except Exception as exc:
                            print(f"heartbeat failed: {exc}", flush=True)
                        last_heartbeat = elapsed
                    time.sleep(2)
                return_code = process.returncode
            finally:
                stop_process_group(process)
                post_reap = reap_df_probe_processes()
                post_removed = cleanup_generated_runtime_files(repo)
                trace.write(
                    json.dumps(
                        {
                            "type": "runtime_cleanup",
                            "phase": phase,
                            "when": "after",
                            "processes": post_reap,
                            "removed_files": post_removed,
                        }
                    )
                    + "\n"
                )
                trace.flush()
        if budget_exhausted:
            with trace_path.open("a", encoding="utf-8") as trace:
                trace.write(
                    json.dumps(
                        {
                            "type": "harness_budget_exhausted",
                            "phase": phase,
                            "max_tool_uses": max_tool_uses,
                            "reason": controlled_stop_reason or "tool_budget",
                        }
                    )
                    + "\n"
                )
            return controlled_stop_reason or "tool_budget"
        if return_code != 0:
            trace_text = trace_path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"OpenCode exited {return_code}: {trace_text[-6000:]}")
        return "completed"

    if not discovery_mode:
        last_phase, _last_reason = run_coding_graph(
            config,
            api,
            job,
            repo,
            base_commit,
            objective_payload,
            previous_error,
            trace_path,
            started,
        )
        cleanup_generated_runtime_files(repo)
        if not has_executable_candidate_change(repo):
            raise GraphBlockedError("coding graph ended without an executable implementation change")
        if not has_public_test_change(repo):
            raise GraphBlockedError("coding graph ended without a public test change")
        final_validation = validate_coding_candidate(repo)
        if not final_validation["ok"]:
            raise GraphBlockedError(
                "coding graph promotion recheck failed: "
                + json.dumps(final_validation, ensure_ascii=False)[-6000:]
            )
        return finalize_graph_candidate(
            config,
            api,
            job,
            repo,
            base_commit,
            branch,
            trace_path,
            started,
            last_phase,
        )

    discovery_tool_budget = min(
        24,
        max(8, int((job.get("constraints") or {}).get("discovery_tool_budget", 16))),
    )
    last_phase = "opencode"
    last_reason = run_harness(
        prompt,
        "opencode",
        append=trace_path.exists(),
        max_tool_uses=discovery_tool_budget if discovery_mode else config.coding_tool_budget,
        progress_deadline_tools=None if discovery_mode else 8,
        probe_deadline_tools=3,
    )

    if not trace_has_live_game_probe(trace_path):
        checkpoint = save_checkpoint(last_phase, last_reason)
        probe_recovery_prompt = f"""
You are a fresh bounded RUNTIME-PROBE phase for Bonsai Dwarf Fortress. Do not restart broad repository
research. The deterministic checkpoint below is the complete handoff from the previous process.

Checkpoint: {json.dumps(checkpoint, ensure_ascii=False)}

Your first tool call must run this exact safe readiness probe:
`/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help`.
Do not invoke `dwarfort`, `dfhack-run`, or shell `timeout` directly. Preserve BONSAI_PROBE_RESULT,
stdout/stderr, and any concrete fields or blocker. In coding mode, leave useful evidence in the working
tree only when it directly supports executable implementation. Do not commit.
""".strip()
        last_phase = "live_game_probe_recovery"
        last_reason = run_harness(
            probe_recovery_prompt,
            last_phase,
            append=True,
            max_tool_uses=1,
            phase_timeout=min(240, config.phase_timeout),
            implementation_only=True,
            probe_deadline_tools=1,
        )

    if not trace_has_live_game_probe(trace_path):
        with trace_path.open("a", encoding="utf-8") as trace:
            trace.write(
                json.dumps(
                    {
                        "type": "harness_warning",
                        "warning": "live_game_probe_not_observed",
                        "policy": "soft_after_bounded_recovery",
                    }
                )
                + "\n"
            )

    if discovery_mode and discovery_needs_synthesis(repo):
        synthesize_discovery(config, api, job, repo, trace_path, started)

    if not discovery_mode and (
        last_reason != "completed"
        or trace_ended_with_degenerate_stop(trace_path)
        or not working_tree_paths(repo)
    ):
        for continuation_index in range(config.max_continuations):
            checkpoint = save_checkpoint(last_phase, last_reason)
            continuation_phase = f"implementation_continuation_{continuation_index + 1}"
            continuation_prompt = f"""
You are a fresh IMPLEMENTATION continuation for Bonsai Dwarf Fortress. The previous process has been
externally compacted. Treat the JSON checkpoint below as its complete handoff; do not reread broad
documentation or restart research.

Objective: {json.dumps(objective_payload, ensure_ascii=False)}
Previous promotion error: {previous_error or "none"}
Checkpoint: {json.dumps(checkpoint, ensure_ascii=False)}

Continue from the existing working tree. If it is clean, implement the smallest executable improvement
supported by the recorded evidence now. If it contains a partial diff, finish that diff instead of replacing
it. Modify executable code and a deterministic public test. Run focused verification, check git status, and
leave changes uncommitted. Your FIRST tool call must edit or write a candidate file; all required task evidence
and exact target paths are already present above. Do not spend that call on status, reading, grep, or discovery.
""".strip()
            last_phase = continuation_phase
            last_reason = run_harness(
                continuation_prompt,
                continuation_phase,
                append=True,
                max_tool_uses=config.coding_tool_budget,
                phase_timeout=min(240, config.phase_timeout),
                implementation_only=True,
                progress_deadline_tools=1,
            )
            if (
                working_tree_paths(repo)
                and last_reason == "completed"
                and not trace_ended_with_degenerate_stop(trace_path)
            ):
                break

    cleanup_generated_runtime_files(repo)
    if not discovery_mode and not has_executable_candidate_change(repo):
        save_checkpoint(last_phase, "terminal_no_implementation")
        raise RuntimeError(
            "coding cycle produced no executable implementation change after bounded phases"
        )

    if not discovery_mode and working_tree_paths(repo):
        validation = validate_coding_candidate(repo)
        with trace_path.open("a", encoding="utf-8") as trace:
            trace.write(json.dumps({"type": "harness_validation", **validation}) + "\n")

        repair_attempts = min(3, max(1, config.validation_repair_attempts))
        for repair_index in range(repair_attempts):
            if has_public_test_change(repo) and validation["ok"]:
                break
            checkpoint = save_checkpoint(last_phase, "validation_failed")
            validation_output = json.dumps(validation, ensure_ascii=False)[-24000:]
            repair_prompt = f"""
You are a fresh TEST-AND-REPAIR phase. Do not research or redesign. Repair the existing candidate using
the exact harness-owned validation result and compact checkpoint below.

Checkpoint: {json.dumps(checkpoint, ensure_ascii=False)}
Validation: {validation_output}
Public test changed: {has_public_test_change(repo)}

Fix syntax or test failures, add/update a deterministic public test if missing, and rerun the relevant
tests. Your FIRST tool call must edit the candidate or its public test. Do not make unrelated changes and
do not commit.
""".strip()
            last_phase = f"validation_repair_{repair_index + 1}"
            last_reason = run_harness(
                repair_prompt,
                last_phase,
                append=True,
                max_tool_uses=config.coding_tool_budget,
                implementation_only=True,
                progress_deadline_tools=1,
                progress_prefixes=("tests/", "evaluator_public/") if not has_public_test_change(repo) else (),
            )
            validation = validate_coding_candidate(repo)
            with trace_path.open("a", encoding="utf-8") as trace:
                trace.write(
                    json.dumps(
                        {
                            "type": "harness_validation",
                            "repair_attempt": repair_index + 1,
                            **validation,
                        }
                    )
                    + "\n"
                )

        missing = []
        if not has_public_test_change(repo):
            missing.append("public test/evaluation change")
        if not validation["ok"]:
            missing.append("fresh harness-owned validation")
        if missing:
            save_checkpoint(last_phase, "terminal_validation_failed")
            raise RuntimeError(
                "coding candidate is incomplete after external compaction: missing "
                + ", ".join(missing)
            )

    trace_text = trace_path.read_text(encoding="utf-8", errors="replace")

    status = run("git status --porcelain", repo, 30)["output"].strip()
    if status:
        persist_cross_job_wip(
            config, job, repo, base_commit, last_phase, "candidate_ready", trace_path
        )
        subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(generate_commit_description, config, job, repo)
                while True:
                    try:
                        commit_title, commit_body = future.result(timeout=25)
                        break
                    except FutureTimeout:
                        elapsed = round(time.monotonic() - started)
                        progress = {
                            "phase": "commit_description",
                            "model": config.model,
                            "elapsed_seconds": elapsed,
                        }
                        api.heartbeat(job, progress)
                        api.worker_heartbeat("running", str(job["id"]), progress)
        except Exception as exc:
            print(f"commit description fallback: {exc}", flush=True)
            commit_title, commit_body = normalize_commit_description({}, str(job["job_type"]))
        trailers = (
            f"Bonsai-Job-Type: {job['job_type']}\n"
            f"Bonsai-Job-ID: {job['id']}"
        )
        subprocess.run(
            [
                "git", "-C", str(repo), "commit",
                "-m", commit_title,
                "-m", commit_body,
                "-m", trailers,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    candidate_commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    changed = candidate_commit != base_commit
    changed_paths = (
        subprocess.check_output(
            ["git", "-C", str(repo), "diff", "--name-only", f"{base_commit}..{candidate_commit}"],
            text=True,
        ).splitlines()
        if changed
        else []
    )
    artifacts: list[str] = []
    if changed:
        subprocess.run(
            ["git", "-C", str(repo), "update-ref", f"refs/heads/{branch}", candidate_commit],
            check=True,
        )
        config.outbox_dir.mkdir(parents=True, exist_ok=True)
        bundle = config.outbox_dir / f"{job['id']}.bundle"
        subprocess.run(
            ["git", "-C", str(repo), "bundle", "create", str(bundle), f"refs/heads/{branch}"],
            check=True,
        )
        artifacts.append(api.upload(str(job["id"]), bundle, "application/x-git-bundle"))
    checkpoint_files = sorted(repo.parent.glob("checkpoint-*.json"))
    for checkpoint_file in checkpoint_files:
        artifacts.append(api.upload(str(job["id"]), checkpoint_file, "application/json"))
    artifacts.append(api.upload(str(job["id"]), trace_path, "application/x-ndjson"))
    summary = trace_text[-4000:].strip() or "OpenCode completed without textual summary"
    return (
        {
            "summary": summary,
            "job_type": job["job_type"],
            "harness": "opencode",
            "model": config.model,
            "base_commit": base_commit,
            "candidate_commit": candidate_commit,
            "branch": branch,
            "changed": changed,
            "changed_paths": changed_paths,
            "candidate_requested": changed,
            "external_checkpoints": [path.name for path in checkpoint_files],
            "duration_seconds": round(time.monotonic() - started, 2),
        },
        artifacts,
    )


def main() -> None:
    config = Config.from_env()
    config.runs_dir.mkdir(parents=True, exist_ok=True)
    config.outbox_dir.mkdir(parents=True, exist_ok=True)
    config.wip_dir.mkdir(parents=True, exist_ok=True)
    startup_reap = reap_df_probe_processes()
    api = Api(config)
    print(
        f"Bonsai lab agent started with {config.model}; runtime_cleanup={startup_reap}",
        flush=True,
    )
    while True:
        job: dict[str, Any] | None = None
        try:
            api.worker_heartbeat("idle")
            job = api.lease()
            if job is None:
                time.sleep(config.poll_seconds)
                continue
            print(f"leased job {job['id']} type={job['job_type']}", flush=True)
            api.worker_heartbeat("running", str(job["id"]), {"phase": "preparing"})
            result, artifacts = execute_job(config, api, job)
            api.complete(job, result, artifacts)
            api.worker_heartbeat("idle", details={"last_job_id": str(job["id"])})
            print(f"completed job {job['id']} artifacts={len(artifacts)}", flush=True)
        except Exception as exc:
            emergency_reap = reap_df_probe_processes()
            if emergency_reap["targets"]:
                print(f"reaped DF probes after worker exception: {emergency_reap}", flush=True)
            print(f"job failed: {exc}", flush=True)
            if job is not None and OBJECTIVE_ID.fullmatch(str(job.get("objective_id") or "")):
                run_repositories = sorted(
                    config.runs_dir.glob(f"{job['id']}-*/repo"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
                if run_repositories:
                    try:
                        failed_repo = run_repositories[0]
                        persist_cross_job_wip(
                            config,
                            job,
                            failed_repo,
                            str(job.get("base_commit") or ""),
                            "worker_exception",
                            repr(exc),
                            failed_repo.parent / "opencode-trace.jsonl",
                        )
                    except Exception as wip_exc:
                        print(f"failed to persist cross-job WIP: {wip_exc}", flush=True)
            try:
                api.worker_heartbeat(
                    "error",
                    str(job["id"]) if job is not None else None,
                    {"error": repr(exc)[-2000:]},
                )
            except Exception as heartbeat_exc:
                print(f"failed to report worker status: {heartbeat_exc}", flush=True)
            if job is not None:
                try:
                    api.fail(job, repr(exc), retryable=not isinstance(exc, GraphBlockedError))
                except Exception as report_exc:
                    print(f"failed to report error: {report_exc}", flush=True)
            time.sleep(config.poll_seconds)


if __name__ == "__main__":
    main()
