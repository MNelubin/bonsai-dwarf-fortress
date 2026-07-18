import asyncio
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from psycopg import Connection

from .auth import require_admin, require_lab
from .db import close_pool, connection as db_connection, open_pool
from .schemas import Heartbeat, JobCreate, JobFailure, JobResult, ObjectiveCreate
from .settings import get_settings


templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(title="Bonsai Control Plane", version="0.1.0", lifespan=lifespan)


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


@app.post("/api/v1/jobs/{job_id}/complete")
def complete_job(
    job_id: UUID,
    payload: JobResult,
    lease_token: str,
    worker_id: str = Depends(require_lab),
) -> dict[str, Any]:
    with db_connection() as connection, connection.transaction():
        _verify_lease(connection, job_id, lease_token, worker_id)
        row = connection.execute(
            """
            UPDATE bonsai.jobs
            SET state = %s, result = %s, artifact_hashes = %s,
                lease_owner = NULL, lease_token_hash = NULL, lease_expires_at = NULL,
                completed_at = now(), updated_at = now()
            WHERE id = %s RETURNING *
            """,
            (payload.status, json.dumps(payload.result), payload.artifact_hashes, job_id),
        ).fetchone()
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
    with db_connection() as connection:
        state = connection.execute("SELECT * FROM bonsai.system_state WHERE singleton = true").fetchone()
        jobs = connection.execute(
            "SELECT * FROM bonsai.jobs ORDER BY created_at DESC LIMIT 25"
        ).fetchall()
        objectives = connection.execute(
            "SELECT * FROM bonsai.objectives ORDER BY priority DESC, created_at LIMIT 25"
        ).fetchall()
        events = connection.execute(
            "SELECT * FROM bonsai.events ORDER BY id DESC LIMIT 30"
        ).fetchall()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"state": state, "jobs": jobs, "objectives": objectives, "events": events, "now": datetime.now(timezone.utc)},
    )
