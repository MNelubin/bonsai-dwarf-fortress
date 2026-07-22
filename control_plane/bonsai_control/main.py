import asyncio
import hashlib
import json
import os
import secrets
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from psycopg import Connection

from .auth import require_admin, require_lab
from .db import close_pool, connection as db_connection, open_pool
from .schemas import (
    ControllerSubmissionCreate,
    Heartbeat,
    JobCreate,
    JobFailure,
    JobResult,
    ObjectiveCreate,
    WorkerHeartbeat,
)
from .settings import get_settings


templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(title="Bonsai Control Plane", version="0.6.0", lifespan=lifespan)


def _event(
    connection: Connection,
    event_type: str,
    actor_type: str,
    actor_id: str,
    aggregate_type: str,
    aggregate_id: str | None,
    payload: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO bonsai.events
            (event_type, actor_type, actor_id, aggregate_type, aggregate_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            event_type,
            actor_type,
            actor_id,
            aggregate_type,
            aggregate_id,
            json.dumps(payload or {}, default=str),
        ),
    )


def _lease_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _valid_commit(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise HTTPException(status_code=422, detail="invalid git commit hash")
    return value


def _submission_hash(git_commit: str, manifest: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"git_commit": git_commit, "manifest": manifest},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _validate_controller_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(manifest)
    kind = normalized.setdefault("kind", "python_callable")
    normalized.setdefault("protocol", "jsonl-v1")
    if normalized["protocol"] != "jsonl-v1":
        raise HTTPException(status_code=422, detail="only jsonl-v1 is currently supported")
    if kind == "python_callable":
        entrypoint = normalized.setdefault("entrypoint", "player.baseline:baseline_policy")
        if not isinstance(entrypoint, str) or ":" not in entrypoint or len(entrypoint) > 300:
            raise HTTPException(status_code=422, detail="invalid Python controller entrypoint")
    elif kind == "command":
        argv = normalized.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 32
            or any(not isinstance(value, str) or not value for value in argv)
        ):
            raise HTTPException(status_code=422, detail="command manifest needs a bounded argv")
    else:
        raise HTTPException(status_code=422, detail="unsupported controller kind")
    return normalized


def _verify_lease(connection: Connection, job_id: UUID, token: str, worker_id: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT * FROM bonsai.jobs
        WHERE id = %s AND state = 'leased' AND lease_owner = %s
          AND lease_expires_at > now()
        FOR UPDATE
        """,
        (job_id, worker_id),
    ).fetchone()
    if row is None or not secrets.compare_digest(row["lease_token_hash"], _lease_hash(token)):
        raise HTTPException(status_code=409, detail="invalid or expired lease")
    return row


@app.get("/health")
def health() -> dict[str, Any]:
    with db_connection() as connection:
        now = connection.execute("SELECT now() AS now").fetchone()["now"]
    return {"status": "ok", "database": "ok", "time": now}


@app.get("/api/v1/system")
def system_state() -> dict[str, Any]:
    with db_connection() as connection:
        row = connection.execute("SELECT * FROM bonsai.system_state WHERE singleton = true").fetchone()
    return row


@app.post("/api/v1/control/{mode}")
def set_mode(mode: str, _: str = Depends(require_admin)) -> dict[str, Any]:
    if mode not in {"running", "paused", "emergency_stop"}:
        raise HTTPException(status_code=400, detail="unsupported mode")
    with db_connection() as connection, connection.transaction():
        connection.execute(
            "UPDATE bonsai.system_state SET mode = %s, updated_at = now() WHERE singleton = true",
            (mode,),
        )
        _event(connection, "system.mode_changed", "human", "admin", "system", "singleton", {"mode": mode})
    return {"mode": mode}


@app.post("/api/v1/objectives", status_code=status.HTTP_201_CREATED)
def create_objective(payload: ObjectiveCreate, _: str = Depends(require_admin)) -> dict[str, Any]:
    with db_connection() as connection, connection.transaction():
        row = connection.execute(
            """
            INSERT INTO bonsai.objectives
                (title, description, priority, cycle_interval_seconds, status, created_by)
            VALUES (%s, %s, %s, %s, 'active', 'human')
            RETURNING *
            """,
            (payload.title, payload.description, payload.priority, payload.cycle_interval_seconds),
        ).fetchone()
        _event(connection, "objective.created", "human", "admin", "objective", str(row["id"]), row)
    return row


@app.get("/api/v1/objectives")
def list_objectives() -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            "SELECT * FROM bonsai.objectives ORDER BY priority DESC, created_at"
        ).fetchall()


@app.post("/api/v1/submissions", status_code=status.HTTP_201_CREATED)
def create_submission(
    payload: ControllerSubmissionCreate, worker_id: str = Depends(require_lab)
) -> dict[str, Any]:
    manifest = _validate_controller_manifest(payload.manifest)
    content_hash = _submission_hash(payload.git_commit, manifest)
    with db_connection() as connection, connection.transaction():
        row = connection.execute(
            """
            INSERT INTO bonsai.controller_submissions
                (objective_id, source_job_id, git_commit, content_hash, manifest)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (objective_id, content_hash) DO UPDATE SET updated_at = now()
            RETURNING *
            """,
            (
                payload.objective_id,
                payload.source_job_id,
                payload.git_commit,
                content_hash,
                json.dumps(manifest),
            ),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO bonsai.objective_evaluation_state (objective_id, submissions_seen)
            VALUES (%s, 1)
            ON CONFLICT (objective_id) DO UPDATE SET
                submissions_seen = bonsai.objective_evaluation_state.submissions_seen + 1,
                updated_at = now()
            """,
            (payload.objective_id,),
        )
        _event(
            connection,
            "submission.admitted",
            "lab",
            worker_id,
            "submission",
            str(row["id"]),
            {"git_commit": payload.git_commit, "manifest": manifest},
        )
    return row


@app.get("/api/v1/submissions")
def list_submissions(limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT s.*, e.score AS latest_score, e.verdict AS latest_verdict
            FROM bonsai.controller_submissions s
            LEFT JOIN LATERAL (
                SELECT score, verdict FROM bonsai.experiments
                WHERE submission_id = s.id ORDER BY completed_at DESC NULLS LAST LIMIT 1
            ) e ON true
            ORDER BY s.created_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()


@app.get("/api/v1/experiments")
def list_experiments(limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with db_connection() as connection:
        return connection.execute(
            "SELECT * FROM bonsai.experiments ORDER BY started_at DESC LIMIT %s", (limit,)
        ).fetchall()


@app.post("/api/v1/jobs", status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, _: str = Depends(require_admin)) -> dict[str, Any]:
    with db_connection() as connection, connection.transaction():
        row = connection.execute(
            """
            INSERT INTO bonsai.jobs
                (objective_id, job_type, priority, payload, constraints, base_commit, max_attempts)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                payload.objective_id,
                payload.job_type,
                payload.priority,
                json.dumps(payload.payload),
                json.dumps(payload.constraints),
                payload.base_commit,
                payload.max_attempts,
            ),
        ).fetchone()
        _event(connection, "job.queued", "human", "admin", "job", str(row["id"]), {"job_type": row["job_type"]})
    return row


@app.get("/api/v1/jobs")
def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with db_connection() as connection:
        return connection.execute(
            "SELECT * FROM bonsai.jobs ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()


@app.post("/api/v1/jobs/lease", response_model=None)
def lease_job(capability: str = "agent", worker_id: str = Depends(require_lab)) -> Any:
    if capability not in {"agent", "evaluator"}:
        raise HTTPException(status_code=400, detail="unsupported worker capability")
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    with db_connection() as connection, connection.transaction():
        mode = connection.execute(
            "SELECT mode FROM bonsai.system_state WHERE singleton = true FOR UPDATE"
        ).fetchone()["mode"]
        if mode != "running":
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        row = connection.execute(
            """
            SELECT * FROM bonsai.jobs
            WHERE state = 'queued' AND available_at <= now()
              AND CASE WHEN %s = 'evaluator'
                       THEN job_type = 'experiment_cycle'
                       ELSE job_type <> 'experiment_cycle'
                  END
            ORDER BY priority DESC, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """,
            (capability,),
        ).fetchone()
        if row is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        leased = connection.execute(
            """
            UPDATE bonsai.jobs
            SET state = 'leased', lease_owner = %s, lease_token_hash = %s,
                lease_expires_at = now() + make_interval(secs => %s),
                attempts = attempts + 1, started_at = COALESCE(started_at, now()), updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (worker_id, _lease_hash(token), settings.lease_seconds, row["id"]),
        ).fetchone()
        _event(connection, "job.leased", "lab", worker_id, "job", str(row["id"]), {"attempt": leased["attempts"]})
        if leased["job_type"] == "experiment_cycle":
            submission_id = (leased["payload"] or {}).get("submission_id")
            connection.execute(
                """
                INSERT INTO bonsai.experiments
                    (job_id, submission_id, baseline_commit, candidate_commit, state,
                     suite_name, suite_version, budget_seconds)
                VALUES (%s, %s, %s, %s, 'running', %s, %s, %s)
                ON CONFLICT (job_id) DO UPDATE SET state = 'running', started_at = now()
                """,
                (
                    leased["id"],
                    submission_id,
                    leased["base_commit"],
                    leased["base_commit"],
                    (leased["payload"] or {}).get("suite_name", "controller_contract_live_smoke"),
                    (leased["payload"] or {}).get("suite_version", "1"),
                    (leased["constraints"] or {}).get("wall_time_seconds", 180),
                ),
            )
            if submission_id:
                connection.execute(
                    "UPDATE bonsai.controller_submissions SET state = 'evaluating', updated_at = now() WHERE id = %s",
                    (submission_id,),
                )
    leased["lease_token"] = token
    leased.pop("lease_token_hash", None)
    return leased


@app.post("/api/v1/jobs/{job_id}/heartbeat")
def heartbeat(
    job_id: UUID,
    payload: Heartbeat,
    lease_token: str,
    worker_id: str = Depends(require_lab),
) -> dict[str, Any]:
    settings = get_settings()
    with db_connection() as connection, connection.transaction():
        _verify_lease(connection, job_id, lease_token, worker_id)
        row = connection.execute(
            """
            UPDATE bonsai.jobs
            SET lease_expires_at = now() + make_interval(secs => %s),
                progress = %s, updated_at = now()
            WHERE id = %s RETURNING id, lease_expires_at, progress
            """,
            (settings.lease_seconds, json.dumps(payload.progress), job_id),
        ).fetchone()
    return row


@app.post("/api/v1/workers/heartbeat")
def worker_heartbeat(
    payload: WorkerHeartbeat,
    worker_id: str = Depends(require_lab),
) -> dict[str, Any]:
    with db_connection() as connection, connection.transaction():
        previous = connection.execute(
            "SELECT * FROM bonsai.workers WHERE worker_id = %s FOR UPDATE", (worker_id,)
        ).fetchone()
        row = connection.execute(
            """
            INSERT INTO bonsai.workers
                (worker_id, status, model, harness, version, current_job_id, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (worker_id) DO UPDATE SET
                status = EXCLUDED.status,
                model = EXCLUDED.model,
                harness = EXCLUDED.harness,
                version = EXCLUDED.version,
                current_job_id = EXCLUDED.current_job_id,
                details = EXCLUDED.details,
                last_seen_at = now(),
                updated_at = now()
            RETURNING *
            """,
            (
                worker_id,
                payload.status,
                payload.model,
                payload.harness,
                payload.version,
                payload.current_job_id,
                json.dumps(payload.details),
            ),
        ).fetchone()
        changed = previous is None or any(
            previous[field] != row[field]
            for field in ("status", "model", "harness", "version", "current_job_id")
        )
        if changed:
            _event(
                connection,
                "worker.status_changed",
                "lab",
                worker_id,
                "worker",
                worker_id,
                {
                    "status": row["status"],
                    "model": row["model"],
                    "harness": row["harness"],
                    "version": row["version"],
                    "current_job_id": row["current_job_id"],
                },
            )
    return row


@app.post("/api/v1/jobs/{job_id}/complete")
def complete_job(
    job_id: UUID,
    payload: JobResult,
    lease_token: str,
    worker_id: str = Depends(require_lab),
) -> dict[str, Any]:
    with db_connection() as connection, connection.transaction():
        job = _verify_lease(connection, job_id, lease_token, worker_id)
        reported_base = _valid_commit(payload.result.get("base_commit"))
        candidate_commit = _valid_commit(payload.result.get("candidate_commit"))
        if reported_base and job["base_commit"] and reported_base != job["base_commit"]:
            raise HTTPException(status_code=409, detail="worker base_commit differs from trusted job baseline")
        if payload.status == "candidate" and (not candidate_commit or candidate_commit == job["base_commit"]):
            raise HTTPException(status_code=422, detail="candidate job must report a new candidate_commit")
        if job["job_type"] == "experiment_cycle" and payload.status != "completed":
            raise HTTPException(
                status_code=422,
                detail="experiment results are measurements and must complete, not become candidates or rejects",
            )
        row = connection.execute(
            """
            UPDATE bonsai.jobs
            SET state = %s, result = %s, artifact_hashes = %s,
                base_commit = COALESCE(base_commit, %s), candidate_commit = %s,
                lease_owner = NULL, lease_token_hash = NULL, lease_expires_at = NULL,
                completed_at = now(), updated_at = now()
            WHERE id = %s RETURNING *
            """,
            (
                payload.status,
                json.dumps(payload.result),
                payload.artifact_hashes,
                reported_base,
                candidate_commit,
                job_id,
            ),
        ).fetchone()
        if payload.status == "candidate":
            connection.execute(
                """
                INSERT INTO bonsai.git_changes
                    (job_id, base_commit, candidate_commit, branch_name, changed_paths,
                     promotion_state, evidence)
                VALUES (%s, %s, %s, %s, %s, 'draft', %s)
                """,
                (
                    job_id,
                    row["base_commit"],
                    candidate_commit,
                    payload.result.get("branch"),
                    payload.result.get("changed_paths", []),
                    json.dumps({"artifact_hashes": payload.artifact_hashes}),
                ),
            )
        if job["job_type"] == "experiment_cycle":
            experiment_result = payload.result
            submission_id = experiment_result.get("submission_id") or (job["payload"] or {}).get(
                "submission_id"
            )
            score = experiment_result.get("score")
            if not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
                raise HTTPException(status_code=422, detail="experiment score must be in [0, 1]")
            metrics = experiment_result.get("metrics") or []
            if not isinstance(metrics, list) or len(metrics) > 200:
                raise HTTPException(status_code=422, detail="invalid experiment metrics")
            experiment = connection.execute(
                """
                UPDATE bonsai.experiments
                SET submission_id = %s, state = 'completed', summary = %s,
                    suite_name = %s, suite_version = %s, score = %s, verdict = %s,
                    failure_kind = %s, result_artifact_hash = %s,
                    completed_at = now()
                WHERE job_id = %s
                RETURNING *
                """,
                (
                    submission_id,
                    json.dumps(experiment_result.get("summary") or {}),
                    experiment_result.get("suite_name"),
                    str(experiment_result.get("suite_version") or ""),
                    float(score),
                    experiment_result.get("verdict"),
                    experiment_result.get("failure_kind"),
                    experiment_result.get("result_hash"),
                    job_id,
                ),
            ).fetchone()
            if experiment is None:
                raise HTTPException(status_code=409, detail="experiment lease record is missing")
            for metric in metrics:
                if not isinstance(metric, dict) or not isinstance(metric.get("name"), str):
                    raise HTTPException(status_code=422, detail="invalid metric object")
                value = metric.get("value")
                if not isinstance(value, (int, float)):
                    raise HTTPException(status_code=422, detail="metric value must be numeric")
                connection.execute(
                    """
                    INSERT INTO bonsai.metrics
                        (experiment_id, episode_id, name, value, unit, tags)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        experiment["id"],
                        metric.get("episode_id"),
                        metric["name"][:200],
                        float(value),
                        metric.get("unit"),
                        json.dumps(metric.get("tags") or {}),
                    ),
                )
            evaluation_state = connection.execute(
                """
                INSERT INTO bonsai.objective_evaluation_state (objective_id)
                VALUES (%s)
                ON CONFLICT (objective_id) DO UPDATE SET updated_at = now()
                RETURNING *
                """,
                (job["objective_id"],),
            ).fetchone()
            improved = evaluation_state["best_score"] is None or float(score) > float(
                evaluation_state["best_score"]
            )
            connection.execute(
                """
                UPDATE bonsai.objective_evaluation_state
                SET champion_submission_id = CASE WHEN %s THEN %s ELSE champion_submission_id END,
                    best_score = CASE WHEN %s THEN %s ELSE best_score END,
                    evaluations_completed = evaluations_completed + 1,
                    consecutive_no_improvement = CASE WHEN %s THEN 0 ELSE consecutive_no_improvement + 1 END,
                    updated_at = now()
                WHERE objective_id = %s
                """,
                (improved, submission_id, improved, float(score), improved, job["objective_id"]),
            )
            if submission_id:
                connection.execute(
                    "UPDATE bonsai.controller_submissions SET state = 'scored', updated_at = now() WHERE id = %s",
                    (submission_id,),
                )
            _event(
                connection,
                "experiment.scored",
                "evaluator",
                worker_id,
                "experiment",
                str(experiment["id"]),
                {
                    "submission_id": submission_id,
                    "score": float(score),
                    "verdict": experiment_result.get("verdict"),
                    "improved_champion": improved,
                },
            )
        _event(connection, f"job.{payload.status}", "lab", worker_id, "job", str(job_id), payload.result)
    return row


@app.post("/api/v1/jobs/{job_id}/fail")
def fail_job(
    job_id: UUID,
    payload: JobFailure,
    lease_token: str,
    worker_id: str = Depends(require_lab),
) -> dict[str, Any]:
    with db_connection() as connection, connection.transaction():
        job = _verify_lease(connection, job_id, lease_token, worker_id)
        retry = payload.retryable and job["attempts"] < job["max_attempts"]
        state = "queued" if retry else "failed"
        row = connection.execute(
            """
            UPDATE bonsai.jobs
            SET state = %s, error = %s, available_at = CASE WHEN %s THEN now() + interval '60 seconds' ELSE available_at END,
                lease_owner = NULL, lease_token_hash = NULL, lease_expires_at = NULL, updated_at = now(),
                completed_at = CASE WHEN %s THEN NULL ELSE now() END
            WHERE id = %s RETURNING *
            """,
            (state, payload.error, retry, retry, job_id),
        ).fetchone()
        if job["job_type"] == "experiment_cycle":
            submission_id = (job["payload"] or {}).get("submission_id")
            connection.execute(
                """
                UPDATE bonsai.experiments
                SET state = %s, summary = summary || %s,
                    completed_at = CASE WHEN %s THEN NULL ELSE now() END
                WHERE job_id = %s
                """,
                (
                    "queued" if retry else "failed",
                    json.dumps({"last_error": payload.error[-4000:]}),
                    retry,
                    job_id,
                ),
            )
            if submission_id:
                connection.execute(
                    "UPDATE bonsai.controller_submissions SET state = %s, updated_at = now() WHERE id = %s",
                    ("queued" if retry else "admitted", submission_id),
                )
        _event(connection, "job.retry_scheduled" if retry else "job.failed", "lab", worker_id, "job", str(job_id), {"error": payload.error})
    return row


@app.get("/api/v1/events")
def list_events(after_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 1000))
    with db_connection() as connection:
        return connection.execute(
            "SELECT * FROM bonsai.events WHERE id > %s ORDER BY id LIMIT %s",
            (after_id, limit),
        ).fetchall()


@app.put("/api/v1/artifacts/{expected_sha256}", status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    expected_sha256: str,
    request: Request,
    job_id: UUID | None = None,
    media_type: str = "application/octet-stream",
    worker_id: str = Depends(require_lab),
) -> dict[str, Any]:
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise HTTPException(status_code=400, detail="invalid sha256")
    settings = get_settings()
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.artifact_max_bytes:
        raise HTTPException(status_code=413, detail="artifact too large")

    artifact_root = Path(settings.artifact_dir)
    target_dir = artifact_root / expected_sha256[:2]
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target_dir, prefix=".upload-", delete=False) as output:
            temporary_path = Path(output.name)
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.artifact_max_bytes:
                    raise HTTPException(status_code=413, detail="artifact too large")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected_sha256:
            raise HTTPException(status_code=422, detail="sha256 mismatch")
        target = target_dir / expected_sha256
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    with db_connection() as connection, connection.transaction():
        connection.execute(
            """
            INSERT INTO bonsai.artifacts
                (sha256, size_bytes, media_type, storage_path, producing_job_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (sha256) DO NOTHING
            """,
            (
                expected_sha256,
                size,
                media_type,
                str(target),
                job_id,
                json.dumps({"uploaded_by": worker_id}),
            ),
        )
        _event(
            connection,
            "artifact.stored",
            "lab",
            worker_id,
            "artifact",
            expected_sha256,
            {"size_bytes": size, "job_id": job_id},
        )
    return {"sha256": expected_sha256, "size_bytes": size, "stored": True}


@app.get("/artifacts/{artifact_sha256}")
def download_artifact(artifact_sha256: str) -> FileResponse:
    if len(artifact_sha256) != 64 or any(c not in "0123456789abcdef" for c in artifact_sha256):
        raise HTTPException(status_code=400, detail="invalid sha256")
    with db_connection() as connection:
        artifact = connection.execute(
            "SELECT * FROM bonsai.artifacts WHERE sha256 = %s", (artifact_sha256,)
        ).fetchone()
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact_root = Path(get_settings().artifact_dir).resolve()
    stored_path = Path(artifact["storage_path"]).resolve()
    if not stored_path.is_relative_to(artifact_root) or not stored_path.is_file():
        raise HTTPException(status_code=404, detail="artifact file unavailable")
    return FileResponse(
        stored_path,
        media_type=artifact["media_type"],
        filename=f"{artifact_sha256}.artifact",
    )


@app.get("/api/v1/events/stream")
async def stream_events(after_id: int = 0) -> StreamingResponse:
    async def generate():
        cursor = after_id
        while True:
            with db_connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM bonsai.events WHERE id > %s ORDER BY id LIMIT 200", (cursor,)
                ).fetchall()
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\ndata: {json.dumps(row, default=str)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    with db_connection() as connection:
        state = connection.execute("SELECT * FROM bonsai.system_state WHERE singleton = true").fetchone()
        jobs = connection.execute(
            """
            SELECT j.*, o.title AS objective_title,
                   CASE WHEN j.started_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (COALESCE(j.completed_at, now()) - j.started_at))
                   END AS duration_seconds
            FROM bonsai.jobs j
            LEFT JOIN bonsai.objectives o ON o.id = j.objective_id
            ORDER BY j.created_at DESC LIMIT 25
            """
        ).fetchall()
        objectives = connection.execute(
            """
            SELECT o.*, s.best_score, s.evaluations_completed, s.consecutive_no_improvement,
                   s.cooldown_until, s.champion_submission_id
            FROM bonsai.objectives o
            LEFT JOIN bonsai.objective_evaluation_state s ON s.objective_id = o.id
            ORDER BY o.priority DESC, o.created_at LIMIT 25
            """
        ).fetchall()
        events = connection.execute(
            "SELECT * FROM bonsai.events ORDER BY id DESC LIMIT 30"
        ).fetchall()
        workers = connection.execute(
            "SELECT * FROM bonsai.workers ORDER BY last_seen_at DESC"
        ).fetchall()
        artifacts = connection.execute(
            "SELECT * FROM bonsai.artifacts ORDER BY created_at DESC LIMIT 25"
        ).fetchall()
        promotions = connection.execute(
            """
            SELECT g.*, j.state AS job_state, j.result->>'model' AS model
            FROM bonsai.git_changes g
            JOIN bonsai.jobs j ON j.id = g.job_id
            ORDER BY g.created_at DESC LIMIT 25
            """
        ).fetchall()
        submissions = connection.execute(
            """
            SELECT s.*, e.score AS latest_score, e.verdict AS latest_verdict
            FROM bonsai.controller_submissions s
            LEFT JOIN LATERAL (
                SELECT score, verdict FROM bonsai.experiments
                WHERE submission_id = s.id ORDER BY completed_at DESC NULLS LAST LIMIT 1
            ) e ON true
            ORDER BY s.created_at DESC LIMIT 25
            """
        ).fetchall()
        experiments = connection.execute(
            """
            SELECT e.*, s.git_commit, j.objective_id
            FROM bonsai.experiments e
            LEFT JOIN bonsai.controller_submissions s ON s.id = e.submission_id
            JOIN bonsai.jobs j ON j.id = e.job_id
            ORDER BY e.started_at DESC LIMIT 25
            """
        ).fetchall()
        counts = connection.execute(
            """
            SELECT
                count(*) FILTER (WHERE state = 'queued') AS queued,
                count(*) FILTER (WHERE state = 'leased') AS running,
                count(*) FILTER (WHERE state = 'candidate') AS candidates,
                count(*) FILTER (WHERE state = 'failed') AS failed,
                count(*) AS total
            FROM bonsai.jobs
            """
        ).fetchone()
    for job in jobs:
        job["error_tail"] = (job["error"] or "")[-2_000:]
    for worker in workers:
        worker["online"] = worker["last_seen_at"] >= now - timedelta(seconds=90)
    github_url = settings.github_repo.rstrip("/")
    if github_url and not github_url.startswith(("http://", "https://")):
        github_url = f"https://github.com/{github_url}"
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "state": state,
            "jobs": jobs,
            "objectives": objectives,
            "events": events,
            "workers": workers,
            "artifacts": artifacts,
            "promotions": promotions,
            "submissions": submissions,
            "experiments": experiments,
            "counts": counts,
            "github_url": github_url,
            "now": now,
        },
    )
