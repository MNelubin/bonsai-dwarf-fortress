import json
import time

from .db import close_pool, connection as db_connection, open_pool
from .settings import get_settings


DEFAULT_CONSTRAINTS = {
    "editable_paths": ["bridge/", "game_runner/", "player/", "skills/", "curricula/", "tests/", "docs/"],
    "wall_time_seconds": 3600,
    "llm_request_limit": 40,
    "episode_budget": 20,
    "promotion_mode": "automatic_if_gated",
}


def tick() -> None:
    with db_connection() as connection, connection.transaction():
        expired = connection.execute(
            """
            UPDATE bonsai.jobs
            SET state = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                available_at = CASE WHEN attempts < max_attempts THEN now() + interval '60 seconds' ELSE available_at END,
                error = concat_ws(E'\n', error, 'lease expired'),
                lease_owner = NULL, lease_token_hash = NULL, lease_expires_at = NULL, updated_at = now(),
                completed_at = CASE WHEN attempts < max_attempts THEN NULL ELSE now() END
            WHERE state = 'leased' AND lease_expires_at <= now()
            RETURNING id, state
            """
        ).fetchall()
        for job in expired:
            connection.execute(
                """
                INSERT INTO bonsai.events
                    (event_type, actor_type, actor_id, aggregate_type, aggregate_id, payload)
                VALUES (%s, 'control', 'orchestrator', 'job', %s, %s)
                """,
                ("job.requeued" if job["state"] == "queued" else "job.failed", str(job["id"]), json.dumps({"reason": "lease expired"})),
            )

        mode = connection.execute(
            "SELECT mode FROM bonsai.system_state WHERE singleton = true"
        ).fetchone()["mode"]
        if mode != "running":
            return

        objective = connection.execute(
            """
            SELECT o.*
            FROM bonsai.objectives o
            WHERE o.status = 'active'
              AND (o.last_job_at IS NULL OR o.last_job_at + make_interval(secs => o.cycle_interval_seconds) <= now())
              AND NOT EXISTS (
                  SELECT 1 FROM bonsai.jobs j
                  WHERE j.objective_id = o.id AND j.state IN ('queued', 'leased', 'candidate')
              )
            ORDER BY o.priority DESC, o.created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if objective is None:
            return

        job = connection.execute(
            """
            INSERT INTO bonsai.jobs
                (objective_id, job_type, priority, payload, constraints, max_attempts)
            VALUES (%s, 'research_cycle', %s, %s, %s, 2)
            RETURNING id
            """,
            (
                objective["id"],
                objective["priority"],
                json.dumps({"objective": objective["title"], "description": objective["description"]}),
                json.dumps(DEFAULT_CONSTRAINTS),
            ),
        ).fetchone()
        connection.execute(
            "UPDATE bonsai.objectives SET last_job_at = now(), updated_at = now() WHERE id = %s",
            (objective["id"],),
        )
        connection.execute(
            """
            INSERT INTO bonsai.events
                (event_type, actor_type, actor_id, aggregate_type, aggregate_id, payload)
            VALUES ('job.queued', 'control', 'orchestrator', 'job', %s, %s)
            """,
            (str(job["id"]), json.dumps({"objective_id": str(objective["id"]), "automatic": True})),
        )


def main() -> None:
    settings = get_settings()
    open_pool()
    try:
        while True:
            try:
                tick()
            except Exception as exc:  # service manager captures the traceback context
                print(f"orchestrator tick failed: {exc}", flush=True)
            time.sleep(settings.scheduler_interval_seconds)
    finally:
        close_pool()


if __name__ == "__main__":
    main()
