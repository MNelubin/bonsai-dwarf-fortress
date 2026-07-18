from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
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
    prompt = f"""
Work autonomously as the senior coding and research agent for Bonsai Dwarf Fortress.

Objective payload: {json.dumps(job.get('payload', {}), ensure_ascii=False)}
Constraints: {json.dumps(job.get('constraints', {}), ensure_ascii=False)}
Previous cycle outcome: {json.dumps(previous_cycle, ensure_ascii=False)}

You are root inside an isolated Debian LXC containing Steam Dwarf Fortress 53.15 and DFHack
53.15-r2 at /srv/df-bonsai/current. This repository clone has no GitHub, PostgreSQL, Steam, or
control-plane credentials. Never search for or print secrets. You may inspect the whole lab, run
non-interactive shell commands and game probes, and edit this repository.

Long-term target: a deterministic DFHack bridge with reset/observe/act/advance, reproducible
headless episodes and metrics, curricula, then a tiny CPU inference player. Make the smallest
coherent improvement that advances the objective. Verify installed DFHack APIs from actual scripts,
symbols, docs or a controlled probe; do not invent APIs. Never cat binary files. Prefer changes in
bridge/, game_runner/, player/, skills/, curricula/, evaluator_public/, tests/, and docs/. Run useful
tests. Do not modify protected control_plane/, db/, evaluator_private/, infra/, security/ or .github/.
Finish only when the working tree contains a tested, reviewable improvement; explain the evidence.
Automatic promotion only accepts bridge/, game_runner/, player/, skills/, curricula/,
evaluator_public/, tests/, and docs/. Every candidate must add or update a public test or evaluator
artifact. Do not add symlinks, submodules, secrets, generated binaries, or files over 2 MiB.

Execution discipline is mandatory:
1. Use at most 6 discovery tool calls before the first write/edit. Inspect narrowly with `file`,
   `find -maxdepth`, `grep -m`, and bounded output; never dump a whole binary or directory tree.
2. Before reading any unknown path under /srv/df-bonsai, run `file` on it. Only read known text
   extensions such as .lua, .txt, .md, .json, .proto, .py, or .rst. Never use cat/head on an
   executable, shared object, archive, image, database, or extensionless unknown file.
3. Create a small coherent implementation early. If live game control is not yet supportable, add a
   deterministic bridge protocol/contract, captured verified API findings, and executable pure tests.
4. You MUST change at least one implementation or documentation file and at least one file under
   tests/ or evaluator_public/. Run those tests. A prose answer with a clean git tree is a rejected
   cycle. Check `git status --short` before finishing.
""".strip()

    command = [
        config.opencode_bin,
        "run",
        "--auto",
        "--format",
        "json",
        "--model",
        config.model,
        prompt,
    ]
    started = time.monotonic()
    last_heartbeat = 0.0
    with trace_path.open("w", encoding="utf-8") as trace:
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
                if elapsed - last_heartbeat >= 35:
                    try:
                        api.heartbeat(
                            job,
                            {
                                "phase": "opencode",
                                "model": config.model,
                                "elapsed_seconds": round(elapsed),
                            },
                        )
                        api.worker_heartbeat(
                            "running",
                            str(job["id"]),
                            {"elapsed_seconds": round(elapsed), "phase": "opencode"},
                        )
                    except Exception as exc:
                        print(f"heartbeat failed: {exc}", flush=True)
                    last_heartbeat = elapsed
                time.sleep(2)
            return_code = process.returncode
        finally:
            stop_process_group(process)

    trace_text = trace_path.read_text(encoding="utf-8", errors="replace")
    if return_code != 0:
        raise RuntimeError(f"OpenCode exited {return_code}: {trace_text[-6000:]}")

    status = run("git status --porcelain", repo, 30)["output"].strip()
    if status:
        subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "agent: OpenCode research cycle"],
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
