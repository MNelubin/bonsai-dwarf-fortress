import json
import time

from .cycle_policy import choose_cycle
from .db import close_pool, connection as db_connection, open_pool
from .settings import get_settings


CODING_CONSTRAINTS = {
    "editable_paths": ["bridge/", "game_runner/", "player/", "skills/", "curricula/", "tests/", "docs/"],
    "wall_time_seconds": 1800,
    "llm_request_limit": 24,
    "discovery_tool_budget_before_write": 6,
    "episode_budget": 20,
    "promotion_mode": "automatic_if_gated",
}

DISCOVERY_CONSTRAINTS = {
    "editable_paths": ["knowledge/"],
    "wall_time_seconds": 1800,
    "llm_request_limit": 24,
    "discovery_tool_budget_before_first_note": 8,
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

        system_state = connection.execute(
            "SELECT mode, current_baseline_commit FROM bonsai.system_state WHERE singleton = true"
        ).fetchone()
        if system_state["mode"] != "running" or not system_state["current_baseline_commit"]:
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

        previous = connection.execute(
            """
            SELECT id, job_type, state, result, error
            FROM bonsai.jobs
            WHERE objective_id = %s AND state IN ('completed', 'rejected', 'failed', 'cancelled')
            ORDER BY completed_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (objective["id"],),
        ).fetchone()
        previous_cycle = None
        if previous is not None:
            summary = previous["result"].get("summary") if previous["result"] else None
            previous_cycle = {
                "job_id": str(previous["id"]),
                "job_type": previous["job_type"],
                "state": previous["state"],
                "model": (previous["result"] or {}).get("model"),
                "changed": (previous["result"] or {}).get("changed"),
                "error": previous["error"],
                "summary_tail": (summary or "")[-2_000:],
            }

        last_discovery_at = connection.execute(
            """
            SELECT max(g.promoted_at) AS promoted_at
            FROM bonsai.git_changes g
            JOIN bonsai.jobs j ON j.id = g.job_id
            WHERE j.objective_id = %s
              AND j.job_type = 'discovery_cycle'
              AND g.promotion_state = 'promoted'
            """,
            (objective["id"],),
        ).fetchone()["promoted_at"]
        promoted_coding_since_discovery = 0
        if last_discovery_at is not None:
            promoted_coding_since_discovery = connection.execute(
                """
                SELECT count(*) AS count
                FROM bonsai.git_changes g
                JOIN bonsai.jobs j ON j.id = g.job_id
                WHERE j.objective_id = %s
                  AND j.job_type = 'coding_cycle'
                  AND g.promotion_state = 'promoted'
                  AND g.promoted_at > %s
                """,
                (objective["id"], last_discovery_at),
            ).fetchone()["count"]
        recent_coding_states = connection.execute(
            """
            SELECT state
            FROM bonsai.jobs
            WHERE objective_id = %s
              AND job_type = 'coding_cycle'
              AND state IN ('completed', 'rejected', 'failed', 'cancelled')
            ORDER BY completed_at DESC NULLS LAST, created_at DESC
            LIMIT 4
            """,
            (objective["id"],),
        ).fetchall()
        consecutive_coding_failures = 0
        for recent in recent_coding_states:
            if recent["state"] not in {"failed", "rejected"}:
                break
            consecutive_coding_failures += 1
        decision = choose_cycle(
            has_promoted_discovery=last_discovery_at is not None,
            last_job_type=previous["job_type"] if previous else None,
            last_job_state=previous["state"] if previous else None,
            last_job_changed=(previous["result"] or {}).get("changed") if previous else None,
            promoted_coding_since_discovery=promoted_coding_since_discovery,
            consecutive_coding_failures=consecutive_coding_failures,
        )
        constraints = (
            DISCOVERY_CONSTRAINTS if decision.job_type == "discovery_cycle" else CODING_CONSTRAINTS
        )

        job = connection.execute(
            """
            INSERT INTO bonsai.jobs
                (objective_id, job_type, priority, payload, constraints, base_commit, max_attempts)
            VALUES (%s, %s, %s, %s, %s, %s, 2)
            RETURNING id
            """,
            (
                objective["id"],
                decision.job_type,
                objective["priority"],
                json.dumps(
                    {
                        "objective": objective["title"],
                        "description": objective["description"],
                        "previous_cycle": previous_cycle,
                        "cycle_decision": {
                            "job_type": decision.job_type,
                            "reason": decision.reason,
                            "promoted_coding_since_discovery": promoted_coding_since_discovery,
                            "consecutive_coding_failures": consecutive_coding_failures,
                        },
                    }
                ),
                json.dumps(constraints),
                system_state["current_baseline_commit"],
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
            (
                str(job["id"]),
                json.dumps(
                    {
                        "objective_id": str(objective["id"]),
                        "automatic": True,
                        "job_type": decision.job_type,
                        "decision_reason": decision.reason,
                    }
                ),
            ),
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
