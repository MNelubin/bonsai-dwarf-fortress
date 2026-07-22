from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvaluatorConfig:
    control_url: str
    lab_token: str
    baseline_repo: Path
    runs_dir: Path
    poll_seconds: int
    controller_timeout_seconds: int
    probe_bin: str
    dfhack_run: str

    @classmethod
    def from_env(cls) -> "EvaluatorConfig":
        return cls(
            control_url=os.environ["BONSAI_CONTROL_URL"].rstrip("/"),
            lab_token=os.environ["BONSAI_LAB_TOKEN"],
            baseline_repo=Path(
                os.environ.get("BONSAI_BASELINE_REPO", "/srv/bonsai-agent/workspace")
            ),
            runs_dir=Path(
                os.environ.get("BONSAI_EVALUATOR_RUNS_DIR", "/srv/bonsai-evaluator/runs")
            ),
            poll_seconds=int(os.environ.get("BONSAI_EVALUATOR_POLL_SECONDS", "10")),
            controller_timeout_seconds=int(
                os.environ.get("BONSAI_CONTROLLER_TIMEOUT_SECONDS", "30")
            ),
            probe_bin=os.environ.get(
                "BONSAI_DF_PROBE_BIN", "/opt/bonsai-lab-agent/venv/bin/bonsai-df-probe"
            ),
            dfhack_run=os.environ.get(
                "BONSAI_DFHACK_RUN", "/srv/df-bonsai/current/dfhack-run"
            ),
        )


class EvaluatorApi:
    def __init__(self, config: EvaluatorConfig):
        self.config = config

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self.config.control_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "X-Bonsai-Lab-Token": self.config.lab_token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"control API {exc.code}: {exc.read().decode(errors='replace')[:2000]}"
            ) from exc

    def lease(self) -> dict[str, Any] | None:
        status, body = self.request(
            "POST", "/api/v1/jobs/lease", query={"capability": "evaluator"}
        )
        return None if status == 204 else body

    def heartbeat(self, job: dict[str, Any], progress: dict[str, Any]) -> None:
        self.request(
            "POST",
            f"/api/v1/jobs/{job['id']}/heartbeat",
            {"progress": progress},
            {"lease_token": job["lease_token"]},
        )

    def worker_heartbeat(
        self, status: str, job_id: str | None = None, details: dict[str, Any] | None = None
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
                "model": "none",
                "harness": "external-evaluator",
                "version": version,
                "current_job_id": job_id,
                "details": details or {},
            },
        )

    def complete(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        self.request(
            "POST",
            f"/api/v1/jobs/{job['id']}/complete",
            {"status": "completed", "result": result, "artifact_hashes": []},
            {"lease_token": job["lease_token"]},
        )

    def fail(self, job: dict[str, Any], error: str) -> None:
        self.request(
            "POST",
            f"/api/v1/jobs/{job['id']}/fail",
            {"error": error[-20_000:], "retryable": True},
            {"lease_token": job["lease_token"]},
        )


def prepare_checkout(config: EvaluatorConfig, job: dict[str, Any]) -> Path:
    commit = str(job.get("base_commit") or "")
    if len(commit) != 40:
        raise ValueError("experiment job has no immutable 40-character base commit")
    target = config.runs_dir / str(job["id"]) / "repo"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(
        ["git", "clone", "--no-checkout", "--shared", str(config.baseline_repo), str(target)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        subprocess.run(
            ["git", "-C", str(target), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "-C", str(target), "fetch", "--depth=1", "origin", commit],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    subprocess.run(
        ["git", "-C", str(target), "checkout", "--detach", commit],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return target


def controller_command(repo: Path, manifest: dict[str, Any]) -> list[str]:
    kind = manifest.get("kind", "python_callable")
    if kind == "python_callable":
        entrypoint = manifest.get("entrypoint", "player.baseline:baseline_policy")
        if not isinstance(entrypoint, str) or len(entrypoint) > 300:
            raise ValueError("invalid Python controller entrypoint")
        return [
            sys.executable,
            "-m",
            "bonsai_lab_agent.controller_host",
            "--repo",
            str(repo),
            "--entrypoint",
            entrypoint,
        ]
    if kind == "command":
        argv = manifest.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 32
            or any(not isinstance(value, str) or not value for value in argv)
        ):
            raise ValueError("command controller requires a non-empty argv string list")
        return argv
    raise ValueError(f"unsupported controller kind: {kind}")


def fixture_observations() -> list[dict[str, Any]]:
    return [
        {"gametype": None, "cur_tick": 0, "paused": True, "units": []},
        {
            "gametype": "DWARF_FORTRESS",
            "cur_tick": 86400,
            "paused": False,
            "units": [{"id": 1, "civ_id": 1, "killed": False}],
        },
        {
            "gametype": "DWARF_FORTRESS",
            "cur_tick": 30 * 86400,
            "paused": True,
            "units": [{"id": 1, "civ_id": 1, "killed": False}],
        },
        {
            "gametype": "DWARF_FORTRESS",
            "cur_tick": 86400,
            "paused": False,
            "units": [{"id": 1, "civ_id": 1, "killed": False}],
        },
    ]


def run_controller(
    command: list[str], repo: Path, observations: list[dict[str, Any]], timeout_seconds: int
) -> tuple[list[dict[str, Any]], float, str]:
    requests = [
        json.dumps(
            {
                "type": "observation",
                "episode_id": "contract-fixture",
                "step": index,
                "observation": observation,
            },
            separators=(",", ":"),
        )
        for index, observation in enumerate(observations)
    ]
    started = time.monotonic()
    process = subprocess.run(
        command,
        cwd=repo,
        input="\n".join(requests) + "\n",
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    latency = time.monotonic() - started
    if process.returncode != 0:
        raise RuntimeError(f"controller exited {process.returncode}: {process.stderr[-2000:]}")
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    if len(lines) != len(observations):
        raise RuntimeError(
            f"controller returned {len(lines)} lines for {len(observations)} observations"
        )
    responses: list[dict[str, Any]] = []
    for line in lines:
        response = json.loads(line)
        if not isinstance(response, dict) or response.get("error"):
            raise RuntimeError(f"controller protocol error: {response}")
        action = response.get("action")
        if action is not None and not isinstance(action, dict):
            raise RuntimeError("controller action must be an object or null")
        responses.append(response)
    return responses, latency, process.stderr[-2000:]


def live_df_probe(config: EvaluatorConfig) -> dict[str, Any]:
    command = [
        config.probe_bin,
        "--timeout",
        "30",
        "--",
        config.dfhack_run,
        "lua",
        "!df.global.cur_year",
    ]
    started = time.monotonic()
    process = subprocess.run(command, capture_output=True, text=True, timeout=45)
    output = (process.stdout + process.stderr)[-8000:]
    marker: dict[str, Any] | None = None
    for line in output.splitlines():
        if line.startswith("BONSAI_PROBE_RESULT "):
            marker = json.loads(line.removeprefix("BONSAI_PROBE_RESULT "))
    ready = bool(
        process.returncode == 0
        and marker
        and marker.get("runtime_ready") is True
        and marker.get("exit") == 0
    )
    return {
        "ready": ready,
        "duration_seconds": round(time.monotonic() - started, 3),
        "marker": marker,
        "output_tail": output[-1000:],
    }


def evaluate_job(config: EvaluatorConfig, job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") or {}
    submission_id = payload.get("submission_id")
    manifest = payload.get("controller_manifest") or {}
    repo = prepare_checkout(config, job)
    command = controller_command(repo, manifest)
    observations = fixture_observations()
    responses, latency, stderr_tail = run_controller(
        command, repo, observations, config.controller_timeout_seconds
    )
    deterministic = responses[1] == responses[3]
    valid_actions = all(
        response.get("action") is None or isinstance(response.get("action"), dict)
        for response in responses
    )
    live = live_df_probe(config)
    score = 0.35 + (0.25 if deterministic else 0.0) + (0.2 if valid_actions else 0.0)
    score += 0.2 if live["ready"] else 0.0
    score = round(score, 6)
    verdict = "admitted_for_gameplay" if score >= 0.8 else "needs_work"
    failure_kind = None if live["ready"] else "game_api"
    summary = {
        "controller_protocol": "jsonl-v1",
        "controller_kind": manifest.get("kind", "python_callable"),
        "deterministic": deterministic,
        "valid_actions": valid_actions,
        "responses": responses,
        "live_df": live,
        "stderr_tail": stderr_tail,
        "scope": "contract and live API smoke; not a 30-day gameplay score",
    }
    canonical = json.dumps(summary, sort_keys=True, default=str).encode()
    return {
        "submission_id": submission_id,
        "suite_name": "controller_contract_live_smoke",
        "suite_version": "1",
        "score": score,
        "verdict": verdict,
        "failure_kind": failure_kind,
        "summary": summary,
        "result_hash": hashlib.sha256(canonical).hexdigest(),
        "metrics": [
            {"name": "controller.score", "value": score, "unit": "ratio"},
            {"name": "controller.latency", "value": latency, "unit": "seconds"},
            {
                "name": "controller.deterministic",
                "value": 1.0 if deterministic else 0.0,
                "unit": "boolean",
            },
            {
                "name": "game_api.ready",
                "value": 1.0 if live["ready"] else 0.0,
                "unit": "boolean",
            },
        ],
    }


def main() -> None:
    config = EvaluatorConfig.from_env()
    config.runs_dir.mkdir(parents=True, exist_ok=True)
    api = EvaluatorApi(config)
    print("Bonsai external evaluator started", flush=True)
    while True:
        job: dict[str, Any] | None = None
        try:
            api.worker_heartbeat("idle")
            job = api.lease()
            if job is None:
                time.sleep(config.poll_seconds)
                continue
            api.worker_heartbeat("running", str(job["id"]), {"phase": "evaluate"})
            api.heartbeat(job, {"phase": "controller_contract", "model": "none"})
            result = evaluate_job(config, job)
            api.complete(job, result)
            api.worker_heartbeat("idle", details={"last_job_id": str(job["id"])})
            print(
                f"evaluated job {job['id']} score={result['score']} verdict={result['verdict']}",
                flush=True,
            )
        except Exception as exc:
            print(f"evaluation failed: {exc!r}", flush=True)
            try:
                api.worker_heartbeat(
                    "error", str(job["id"]) if job else None, {"error": repr(exc)[-2000:]}
                )
            except Exception:
                pass
            if job is not None:
                try:
                    api.fail(job, repr(exc))
                except Exception as report_exc:
                    print(f"failed to report evaluator error: {report_exc!r}", flush=True)
            time.sleep(config.poll_seconds)


if __name__ == "__main__":
    main()
