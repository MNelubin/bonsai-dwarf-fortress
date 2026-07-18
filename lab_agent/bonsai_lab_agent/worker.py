from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"enum": ["inspect", "read", "write", "shell", "finish"]},
        "path": {"type": "string"},
        "content": {"type": "string"},
        "command": {"type": "string"},
        "timeout": {"type": "integer"},
        "summary": {"type": "string"},
        "candidate": {"type": "boolean"},
    },
    "required": ["action"],
}


@dataclass(frozen=True)
class Config:
    control_url: str
    lab_token: str
    ollama_url: str
    model: str
    baseline_repo: Path
    runs_dir: Path
    outbox_dir: Path
    poll_seconds: int
    max_steps: int
    shell_timeout: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            control_url=os.environ["BONSAI_CONTROL_URL"].rstrip("/"),
            lab_token=os.environ["BONSAI_LAB_TOKEN"],
            ollama_url=os.environ.get("BONSAI_OLLAMA_URL", "http://100.96.0.4:11434").rstrip("/"),
            model=os.environ.get("BONSAI_MODEL", "qwen3:30b"),
            baseline_repo=Path(os.environ.get("BONSAI_BASELINE_REPO", "/srv/bonsai-agent/workspace")),
            runs_dir=Path(os.environ.get("BONSAI_RUNS_DIR", "/srv/bonsai-agent/runs")),
            outbox_dir=Path(os.environ.get("BONSAI_OUTBOX_DIR", "/srv/bonsai-agent/outbox")),
            poll_seconds=int(os.environ.get("BONSAI_POLL_SECONDS", "10")),
            max_steps=int(os.environ.get("BONSAI_MAX_STEPS", "24")),
            shell_timeout=int(os.environ.get("BONSAI_SHELL_TIMEOUT", "600")),
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

    def complete(self, job: dict[str, Any], result: dict[str, Any], artifacts: list[str]) -> None:
        completion_status = (
            "candidate" if result.get("changed") and result.get("candidate_requested") else "completed"
        )
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


def run(command: str, cwd: Path, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.run(
        ["/bin/bash", "-lc", command],
        cwd=cwd,
        text=True,
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


def safe_path(repo: Path, relative: str) -> Path:
    target = (repo / relative).resolve()
    target.relative_to(repo.resolve())
    return target


def inspect(repo: Path) -> dict[str, Any]:
    return {
        "git": run("git status --short --branch", repo, 30),
        "files": run(
            "find . -maxdepth 3 -type f -not -path './.git/*' -printf '%p\\n' | sort | head -400",
            repo,
            30,
        ),
        "df_release": "/srv/df-bonsai/current",
        "dfhack": "/srv/df-bonsai/current/dfhack",
        "dfhack_run": "/srv/df-bonsai/current/dfhack-run",
    }


def ollama_step(config: Config, messages: list[dict[str, str]]) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "stream": False,
        "format": ACTION_SCHEMA,
        "messages": messages,
        "options": {"temperature": 0.2, "num_ctx": 32768},
    }
    request = urllib.request.Request(
        f"{config.ollama_url}/api/chat",
        method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        result = json.loads(response.read())
    content = result.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("Ollama returned an empty action")
    return json.loads(content)


def prepare_run(config: Config, job: dict[str, Any]) -> tuple[Path, str, str]:
    run_id = f"{job['id']}-{int(time.time())}"
    run_root = config.runs_dir / run_id
    repo = run_root / "repo"
    run_root.mkdir(parents=True, exist_ok=False)
    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(config.baseline_repo), str(repo)],
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
    trace_path = repo.parent / "agent-trace.jsonl"
    stop = threading.Event()
    progress: dict[str, Any] = {"phase": "starting", "step": 0, "model": config.model}

    def heartbeat_loop() -> None:
        while not stop.wait(40):
            try:
                api.heartbeat(job, progress.copy())
            except Exception as exc:
                print(f"heartbeat failed: {exc}", flush=True)

    heartbeat = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat.start()
    system_prompt = f"""
You are the autonomous senior coding/research agent for Bonsai Dwarf Fortress.
You run as root inside the isolated, disposable Debian LXC lab. You may use the whole container,
the installed Steam Dwarf Fortress 53.15 + DFHack 53.15-r2 at /srv/df-bonsai/current, and the
credential-free repository clone at {repo}. Ollama is on the separate GPU host.

Objective: {json.dumps(job.get('payload', {}), ensure_ascii=False)}
Constraints: {json.dumps(job.get('constraints', {}), ensure_ascii=False)}

Long-term target: create a deterministic DFHack bridge (reset/observe/act/advance), reproducible
headless episodes, curricula and metrics, then distill a very lightweight CPU inference policy.
Start with the smallest tested improvement that advances the objective. Inspect before editing.
Do not attempt to access control-plane, PostgreSQL, GitHub, Steam, or lab API credentials and never
print secrets. The trusted publisher will reject changes to protected paths. Prefer edits under
bridge/, game_runner/, player/, skills/, curricula/, evaluator_public/, tests/, and docs/.

Return exactly one JSON action per turn. `shell` is a real root shell in the lab and can run tests or
DFHack; `write` replaces a file under the repo. Never use an interactive command. When the change is
tested and coherent, use `finish` with a precise summary and candidate=true.
""".strip()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({"initial_observation": inspect(repo)}, default=str)},
    ]
    try:
        summary = "step budget exhausted"
        candidate_requested = False
        for step in range(1, config.max_steps + 1):
            progress.update({"phase": "agent_loop", "step": step})
            action = ollama_step(config, messages)
            with trace_path.open("a", encoding="utf-8") as trace:
                trace.write(json.dumps({"step": step, "action": action}, ensure_ascii=False) + "\n")
            name = action.get("action")
            if name == "inspect":
                observation: Any = inspect(repo)
            elif name == "read":
                target = safe_path(repo, action.get("path", ""))
                observation = {"path": str(target.relative_to(repo)), "content": target.read_text(errors="replace")[:120_000]}
            elif name == "write":
                target = safe_path(repo, action.get("path", ""))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(action.get("content", ""), encoding="utf-8")
                observation = {"written": str(target.relative_to(repo)), "bytes": target.stat().st_size}
            elif name == "shell":
                timeout = min(max(int(action.get("timeout", config.shell_timeout)), 1), config.shell_timeout)
                observation = run(action.get("command", ""), repo, timeout)
            elif name == "finish":
                summary = action.get("summary", "agent finished")
                candidate_requested = bool(action.get("candidate", True))
                break
            else:
                observation = {"error": f"unsupported action: {name}"}
            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
            messages.append({"role": "user", "content": json.dumps({"tool_result": observation}, ensure_ascii=False, default=str)})

        progress.update({"phase": "packaging", "step": progress["step"]})
        status = run("git status --porcelain", repo, 30)["output"].strip()
        artifacts: list[str] = []
        candidate_commit = base_commit
        if status and candidate_requested:
            subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", f"agent: {summary[:120]}"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            candidate_commit = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()
            config.outbox_dir.mkdir(parents=True, exist_ok=True)
            bundle = config.outbox_dir / f"{job['id']}.bundle"
            subprocess.run(["git", "-C", str(repo), "bundle", "create", str(bundle), branch], check=True)
            artifacts.append(api.upload(str(job["id"]), bundle, "application/x-git-bundle"))
        trace_hash = api.upload(str(job["id"]), trace_path, "application/x-ndjson")
        artifacts.append(trace_hash)
        return (
            {
                "summary": summary,
                "model": config.model,
                "base_commit": base_commit,
                "candidate_commit": candidate_commit,
                "branch": branch,
                "changed": bool(status),
                "candidate_requested": candidate_requested,
            },
            artifacts,
        )
    finally:
        stop.set()
        heartbeat.join(timeout=2)


def main() -> None:
    config = Config.from_env()
    config.runs_dir.mkdir(parents=True, exist_ok=True)
    config.outbox_dir.mkdir(parents=True, exist_ok=True)
    api = Api(config)
    print(f"Bonsai lab agent started with {config.model}", flush=True)
    while True:
        job: dict[str, Any] | None = None
        try:
            job = api.lease()
            if job is None:
                time.sleep(config.poll_seconds)
                continue
            print(f"leased job {job['id']} type={job['job_type']}", flush=True)
            result, artifacts = execute_job(config, api, job)
            api.complete(job, result, artifacts)
            print(f"completed job {job['id']} artifacts={len(artifacts)}", flush=True)
        except Exception as exc:
            print(f"job failed: {exc}", flush=True)
            if job is not None:
                try:
                    api.fail(job, repr(exc))
                except Exception as report_exc:
                    print(f"failed to report error: {report_exc}", flush=True)
            time.sleep(config.poll_seconds)


if __name__ == "__main__":
    main()
