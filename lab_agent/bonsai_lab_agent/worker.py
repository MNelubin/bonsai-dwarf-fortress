from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    control_url: str
    lab_token: str
    model: str
    baseline_repo: Path
    baseline_remote: str
    runs_dir: Path
    outbox_dir: Path
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

    def fail(self, job: dict[str, Any], error: str) -> None:
        self.request(
            "POST",
            f"/api/v1/jobs/{job['id']}/fail",
            {"error": error[-20_000:], "retryable": True},
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
            if line
        )
    return paths


def serializable_working_tree_paths(repo: Path) -> list[str]:
    """Return stable JSON-safe paths for prompts and API payloads."""
    return sorted(working_tree_paths(repo))


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


def trace_has_live_game_probe(trace_path: Path) -> bool:
    """Require an actual bounded interaction with the installed DF runtime."""
    if not trace_path.is_file():
        return False
    execution_markers = (
        "dfhack-run",
        "dwarfort",
        "dwarf_fortress",
        "probe_dfhack",
        "bridge/probe.py",
    )
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
        if "timeout " in command and any(marker in command for marker in execution_markers):
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
    diff_stat = run("git diff --stat", repo, 30)["output"][-4000:]
    diff_excerpt = run("git diff --unified=2 --no-ext-diff", repo, 30)["output"][:14000]
    return {
        "from_phase": phase,
        "stop_reason": reason,
        "previous_gate_error": previous_error[-4000:],
        "changed_paths": changed,
        "diff_stat": diff_stat,
        "diff_excerpt": diff_excerpt,
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

    return {
        "ok": all(command["exit_code"] == 0 for command in commands),
        "commands": commands,
    }


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
            except FutureTimeout:
                elapsed = round(time.monotonic() - started)
                if elapsed > config.harness_timeout:
                    raise TimeoutError(
                        f"structured synthesis exceeded {config.harness_timeout} seconds"
                    )
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

Run at least one bounded executable probe with `timeout` against a real DF/DFHack entry point, script,
raw, save, or runtime API. Capture exact stdout/stderr/exit status and extract actual field names,
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

{mode_instructions}

Execution discipline is mandatory:
1. Inspect narrowly with `file`, `find -maxdepth`, `grep -m`, and bounded output; never dump a whole
   binary or directory tree.
2. Before reading any unknown path under /srv/df-bonsai, run `file` on it. Only read known text
   extensions such as .lua, .txt, .md, .json, .proto, .py, or .rst. Never use cat/head on an
   executable, shared object, archive, image, database, or extensionless unknown file.
3. Check `git status --short` before finishing and summarize exact files and verification evidence.
""".strip()

    started = time.monotonic()
    last_heartbeat = 0.0
    requested_wall_time = int((job.get("constraints") or {}).get("wall_time_seconds", config.harness_timeout))
    job_wall_time = min(config.harness_timeout, max(300, requested_wall_time))
    def run_harness(
        harness_prompt: str,
        phase: str,
        append: bool,
        max_tool_uses: int | None = None,
        phase_timeout: int | None = None,
        implementation_only: bool = False,
    ) -> str:
        nonlocal last_heartbeat
        budget_exhausted = False
        controlled_stop_reason: str | None = None
        phase_started = time.monotonic()
        effective_phase_timeout = phase_timeout or config.phase_timeout
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
                    if max_tool_uses is not None and trace_path.exists():
                        tool_uses = trace_phase_tool_use_count(trace_path, phase)
                        if tool_uses >= max_tool_uses:
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

    discovery_tool_budget = min(
        24,
        max(8, int((job.get("constraints") or {}).get("discovery_tool_budget", 16))),
    )
    last_phase = "opencode"
    last_reason = run_harness(
        prompt,
        "opencode",
        append=False,
        max_tool_uses=discovery_tool_budget if discovery_mode else config.coding_tool_budget,
    )

    if not trace_has_live_game_probe(trace_path):
        checkpoint = store_external_checkpoint(
            repo, trace_path, last_phase, last_reason, previous_error
        )
        probe_recovery_prompt = f"""
You are a fresh bounded RUNTIME-PROBE phase for Bonsai Dwarf Fortress. Do not restart broad repository
research. The deterministic checkpoint below is the complete handoff from the previous process.

Checkpoint: {json.dumps(checkpoint, ensure_ascii=False)}

Your first tool call must use `timeout` with an installed runtime entry point under /srv/df-bonsai/current
(dfhack-run, dwarfort, or the repository's real bridge probe). Preserve the exact command, exit status,
stdout/stderr, and any concrete fields or blocker. In coding mode, leave useful evidence in the working
tree only when it directly supports executable implementation. Do not commit.
""".strip()
        last_phase = "live_game_probe_recovery"
        last_reason = run_harness(
            probe_recovery_prompt,
            last_phase,
            append=True,
            max_tool_uses=8,
            phase_timeout=min(240, config.phase_timeout),
            implementation_only=True,
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
            checkpoint = store_external_checkpoint(
                repo, trace_path, last_phase, last_reason, previous_error
            )
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
leave changes uncommitted. You have a fresh tool budget; spend it on edits and validation, not rediscovery.
""".strip()
            last_phase = continuation_phase
            last_reason = run_harness(
                continuation_prompt,
                continuation_phase,
                append=True,
                max_tool_uses=config.coding_tool_budget,
                implementation_only=True,
            )
            if (
                working_tree_paths(repo)
                and last_reason == "completed"
                and not trace_ended_with_degenerate_stop(trace_path)
            ):
                break

    if not discovery_mode and working_tree_paths(repo):
        validation = validate_coding_candidate(repo)
        with trace_path.open("a", encoding="utf-8") as trace:
            trace.write(json.dumps({"type": "harness_validation", **validation}) + "\n")

        repair_attempts = min(3, max(1, config.validation_repair_attempts))
        for repair_index in range(repair_attempts):
            if has_public_test_change(repo) and validation["ok"]:
                break
            checkpoint = store_external_checkpoint(
                repo, trace_path, last_phase, "validation_failed", previous_error
            )
            validation_output = json.dumps(validation, ensure_ascii=False)[-24000:]
            repair_prompt = f"""
You are a fresh TEST-AND-REPAIR phase. Do not research or redesign. Repair the existing candidate using
the exact harness-owned validation result and compact checkpoint below.

Checkpoint: {json.dumps(checkpoint, ensure_ascii=False)}
Validation: {validation_output}
Public test changed: {has_public_test_change(repo)}

Fix syntax or test failures, add/update a deterministic public test if missing, and rerun the relevant
tests. Do not make unrelated changes and do not commit.
""".strip()
            last_phase = f"validation_repair_{repair_index + 1}"
            last_reason = run_harness(
                repair_prompt,
                last_phase,
                append=True,
                max_tool_uses=config.coding_tool_budget,
                implementation_only=True,
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
            raise RuntimeError(
                "coding candidate is incomplete after external compaction: missing "
                + ", ".join(missing)
            )

    trace_text = trace_path.read_text(encoding="utf-8", errors="replace")

    status = run("git status --porcelain", repo, 30)["output"].strip()
    if status:
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
    api = Api(config)
    print(f"Bonsai lab agent started with {config.model}", flush=True)
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
            print(f"job failed: {exc}", flush=True)
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
                    api.fail(job, repr(exc))
                except Exception as report_exc:
                    print(f"failed to report error: {report_exc}", flush=True)
            time.sleep(config.poll_seconds)


if __name__ == "__main__":
    main()
