from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import signal
import subprocess
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

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            control_url=os.environ["BONSAI_CONTROL_URL"].rstrip("/"),
            lab_token=os.environ["BONSAI_LAB_TOKEN"],
            model=os.environ.get("BONSAI_MODEL", "ollama/qwen3.6:27b-64k"),
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


DISCOVERY_NOTE_PATH = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}\.md$")


def write_discovery_bundle(repo: Path, payload: dict[str, Any]) -> str:
    note_path = payload.get("note_path")
    index_markdown = payload.get("index_markdown")
    note_markdown = payload.get("note_markdown")
    if not isinstance(note_path, str) or DISCOVERY_NOTE_PATH.fullmatch(note_path) is None:
        raise ValueError("structured discovery returned an unsafe note_path")
    if not isinstance(index_markdown, str) or not 200 <= len(index_markdown) <= 50_000:
        raise ValueError("structured discovery returned an invalid INDEX.md")
    if not isinstance(note_markdown, str) or not 500 <= len(note_markdown) <= 100_000:
        raise ValueError("structured discovery returned an invalid focused note")
    required_markers = ("VERIFIED", "INFERRED", "OPEN", "53.15", "53.15-r2")
    if any(marker not in note_markdown for marker in required_markers):
        raise ValueError("structured discovery note lacks claim tags or exact version markers")
    relative_target = f"dfhack/{note_path}"
    if relative_target not in index_markdown:
        raise ValueError("structured discovery index does not link the focused note")
    knowledge = repo / "knowledge"
    focused = knowledge / "dfhack"
    focused.mkdir(parents=True, exist_ok=True)
    (knowledge / "INDEX.md").write_text(index_markdown.rstrip() + "\n", encoding="utf-8")
    (focused / note_path).write_text(note_markdown.rstrip() + "\n", encoding="utf-8")
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
- note_path is a basename such as bridge-primitives.md;
- index_markdown is a complete knowledge/INDEX.md and links the note as dfhack/<note_path>;
- note_markdown is a substantive focused note with every claim visibly tagged VERIFIED, INFERRED,
  or OPEN;
- cite exact source paths or bounded commands/results present in the trace;
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


def harness_environment(config: Config) -> dict[str, str]:
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
    previous_cycle = job.get("payload", {}).get("previous_cycle") or {}
    discovery_mode = job.get("job_type") == "discovery_cycle"
    if discovery_mode:
        mode_instructions = """
You are in DISCOVERY MODE. Do not implement or modify executable product code. Your only writable
tree is knowledge/. Build a durable, versioned knowledge library for later coding agents.

Within at most 8 discovery calls, create or update knowledge/INDEX.md and at least one focused note
under knowledge/dfhack/. Continue updating notes while you investigate instead of saving all writing
for the end. Each claim must be tagged VERIFIED, INFERRED, or OPEN; include the exact DF/DFHack
version, source path or bounded probe command, result, implications for reset/observe/act/advance,
and the next concrete coding recommendation. Deduplicate existing notes and link them from INDEX.md.
Do not touch bridge/, game_runner/, player/, tests/, docs/, control_plane/, lab_agent/, or infra/.
A prose chat answer with no knowledge/ commit is a rejected cycle.
""".strip()
    else:
        mode_instructions = """
You are in CODING MODE. Read knowledge/INDEX.md and the relevant focused notes before probing the
game. Treat VERIFIED notes as the starting point and explicitly record when reality contradicts
them. Use at most 4 external discovery calls before the first write/edit.

Create the smallest coherent implementation advancing reset/observe/act/advance, the episode
runner, evaluation, or the CPU player. You MUST modify an implementation or user-facing document
and add or update a deterministic test under tests/ or evaluator_public/. Run the tests. Do not
change knowledge/ in coding mode; unresolved questions are a reason for the next discovery cycle.
A clean git tree is a rejected cycle.
""".strip()
    prompt = f"""
Work autonomously as the senior agent for Bonsai Dwarf Fortress.

Objective payload: {json.dumps(job.get('payload', {}), ensure_ascii=False)}
Constraints: {json.dumps(job.get('constraints', {}), ensure_ascii=False)}
Previous cycle outcome: {json.dumps(previous_cycle, ensure_ascii=False)}

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
    def run_harness(
        harness_prompt: str,
        phase: str,
        append: bool,
        max_tool_uses: int | None = None,
    ) -> None:
        nonlocal last_heartbeat
        budget_exhausted = False
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
                trace.write(json.dumps({"type": "harness_phase", "phase": phase}) + "\n")
                trace.flush()
            process = subprocess.Popen(
                command,
                cwd=repo,
                env=harness_environment(config),
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
                    if elapsed > config.harness_timeout:
                        raise TimeoutError(f"OpenCode exceeded {config.harness_timeout} seconds")
                    if max_tool_uses is not None and trace_path.exists():
                        tool_uses = trace_path.read_text(
                            encoding="utf-8", errors="replace"
                        ).count('"type":"tool_use"')
                        if tool_uses >= max_tool_uses:
                            budget_exhausted = True
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
                        }
                    )
                    + "\n"
                )
            return
        if return_code != 0:
            trace_text = trace_path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"OpenCode exited {return_code}: {trace_text[-6000:]}")

    run_harness(prompt, "opencode", append=False, max_tool_uses=8 if discovery_mode else None)
    if discovery_mode and discovery_needs_synthesis(repo):
        synthesize_discovery(config, api, job, repo, trace_path, started)

    trace_text = trace_path.read_text(encoding="utf-8", errors="replace")

    status = run("git status --porcelain", repo, 30)["output"].strip()
    if status:
        subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", f"agent: {job['job_type']}"],
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
