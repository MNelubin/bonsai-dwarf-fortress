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
from .schemas import Heartbeat, JobCreate, JobFailure, JobResult, ObjectiveCreate, WorkerHeartbeat
from .settings import get_settings


templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(title="Bonsai Control Plane", version="0.4.0", lifespan=lifespan)


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
def lease_job(worker_id: str = Depends(require_lab)) -> Any:
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
            ORDER BY priority DESC, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
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
            "SELECT * FROM bonsai.objectives ORDER BY priority DESC, created_at LIMIT 25"
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
            "counts": counts,
            "github_url": github_url,
            "now": now,
        },
    )
