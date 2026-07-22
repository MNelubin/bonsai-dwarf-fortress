import hashlib
import json
import re
import time
from datetime import datetime

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

EXPERIMENT_CONSTRAINTS = {
    "wall_time_seconds": 180,
    "controller_timeout_seconds": 30,
    "episode_budget": 4,
    "promotion_mode": "measurement_only",
}


def failure_fingerprint(error: str | None) -> str | None:
    if not error:
        return None
    normalized = error.lower()
    normalized = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "<uuid>", normalized)
    normalized = re.sub(r"\b[0-9a-f]{40,64}\b", "<hash>", normalized)
    normalized = re.sub(r"/[^\s:'\"]+", "<path>", normalized)
    normalized = re.sub(r"\b\d+\b", "<n>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()[-2000:]
    return hashlib.sha256(normalized.encode()).hexdigest() if normalized else None


def submission_hash(git_commit: str, manifest: dict[str, object]) -> str:
    canonical = json.dumps(
        {"git_commit": git_commit, "manifest": manifest},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def summary_tail(value: object, limit: int = 2_000) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[-limit:]


def should_start_cooldown(
    repeated_fingerprint: str | None,
    latest_failure_completed_at: datetime | None,
    evaluation_state_updated_at: datetime | None,
) -> bool:
    return bool(
        repeated_fingerprint
        and latest_failure_completed_at
        and (
            evaluation_state_updated_at is None
            or latest_failure_completed_at > evaluation_state_updated_at
        )
    )


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
              AND COALESCE(
                    (SELECT cooldown_until FROM bonsai.objective_evaluation_state s
                     WHERE s.objective_id = o.id),
                    '-infinity'::timestamptz
                  ) <= now()
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

        connection.execute(
            """
            INSERT INTO bonsai.objective_evaluation_state (objective_id)
            VALUES (%s) ON CONFLICT (objective_id) DO NOTHING
            """,
            (objective["id"],),
        )

        recent_failures = connection.execute(
            """
            SELECT id, error, completed_at FROM bonsai.jobs
            WHERE objective_id = %s AND state = 'failed' AND error IS NOT NULL
            ORDER BY completed_at DESC NULLS LAST, created_at DESC LIMIT 3
            """,
            (objective["id"],),
        ).fetchall()
        fingerprints = [failure_fingerprint(row["error"]) for row in recent_failures]
        repeated_fingerprint = (
            fingerprints[0]
            if len(fingerprints) == 3 and fingerprints[0] and len(set(fingerprints)) == 1
            else None
        )
        evaluation_state = connection.execute(
            "SELECT * FROM bonsai.objective_evaluation_state WHERE objective_id = %s FOR UPDATE",
            (objective["id"],),
        ).fetchone()
        if should_start_cooldown(
            repeated_fingerprint,
            recent_failures[0]["completed_at"] if recent_failures else None,
            evaluation_state["updated_at"],
        ):
            connection.execute(
                """
                UPDATE bonsai.objective_evaluation_state
                SET last_failure_fingerprint = %s, repeated_failure_count = 3,
                    cooldown_until = now() + interval '10 minutes', updated_at = now()
                WHERE objective_id = %s
                """,
                (repeated_fingerprint, objective["id"]),
            )
            connection.execute(
                "UPDATE bonsai.objectives SET last_job_at = now(), updated_at = now() WHERE id = %s",
                (objective["id"],),
            )
            connection.execute(
                """
                INSERT INTO bonsai.events
                    (event_type, actor_type, actor_id, aggregate_type, aggregate_id, payload)
                VALUES ('objective.cooldown_started', 'control', 'orchestrator', 'objective', %s, %s)
                """,
                (
                    str(objective["id"]),
                    json.dumps(
                        {
                            "failure_fingerprint": repeated_fingerprint,
                            "repeated_count": 3,
                            "cooldown_seconds": 600,
                            "reason": "three identical terminal failures",
                        }
                    ),
                ),
            )
            return

        default_manifest: dict[str, object] = {
            "kind": "python_callable",
            "protocol": "jsonl-v1",
            "entrypoint": "player.baseline:baseline_policy",
        }
        latest_promoted_coding = connection.execute(
            """
            SELECT j.id AS job_id, g.candidate_commit
            FROM bonsai.git_changes g
            JOIN bonsai.jobs j ON j.id = g.job_id
            WHERE j.objective_id = %s AND j.job_type = 'coding_cycle'
              AND g.promotion_state = 'promoted' AND g.candidate_commit IS NOT NULL
            ORDER BY g.promoted_at DESC LIMIT 1
            """,
            (objective["id"],),
        ).fetchone()
        if latest_promoted_coding is not None:
            digest = submission_hash(latest_promoted_coding["candidate_commit"], default_manifest)
            inserted_submission = connection.execute(
                """
                INSERT INTO bonsai.controller_submissions
                    (objective_id, source_job_id, git_commit, content_hash, manifest)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (objective_id, content_hash) DO NOTHING
                RETURNING id
                """,
                (
                    objective["id"],
                    latest_promoted_coding["job_id"],
                    latest_promoted_coding["candidate_commit"],
                    digest,
                    json.dumps(default_manifest),
                ),
            ).fetchone()
            if inserted_submission is not None:
                connection.execute(
                    """
                    UPDATE bonsai.objective_evaluation_state
                    SET submissions_seen = submissions_seen + 1, updated_at = now()
                    WHERE objective_id = %s
                    """,
                    (objective["id"],),
                )
                connection.execute(
                    """
                    INSERT INTO bonsai.events
                        (event_type, actor_type, actor_id, aggregate_type, aggregate_id, payload)
                    VALUES ('submission.admitted', 'control', 'orchestrator', 'submission', %s, %s)
                    """,
                    (
                        str(inserted_submission["id"]),
                        json.dumps(
                            {
                                "automatic": True,
                                "git_commit": latest_promoted_coding["candidate_commit"],
                                "source_job_id": str(latest_promoted_coding["job_id"]),
                            }
                        ),
                    ),
                )

        unscored_submission = connection.execute(
            """
            SELECT * FROM bonsai.controller_submissions
            WHERE objective_id = %s AND state = 'admitted'
            ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
            """,
            (objective["id"],),
        ).fetchone()

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
                "summary_tail": summary_tail(summary),
                "score": (previous["result"] or {}).get("score"),
                "verdict": (previous["result"] or {}).get("verdict"),
                "failure_kind": (previous["result"] or {}).get("failure_kind"),
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
        last_coding_at = connection.execute(
            """
            SELECT max(g.promoted_at) AS promoted_at
            FROM bonsai.git_changes g
            JOIN bonsai.jobs j ON j.id = g.job_id
            WHERE j.objective_id = %s
              AND j.job_type = 'coding_cycle'
              AND g.promotion_state = 'promoted'
            """,
            (objective["id"],),
        ).fetchone()["promoted_at"]
        discovery_promotions_since_coding = connection.execute(
            """
            SELECT count(*) AS count
            FROM bonsai.git_changes g
            JOIN bonsai.jobs j ON j.id = g.job_id
            WHERE j.objective_id = %s
              AND j.job_type = 'discovery_cycle'
              AND g.promotion_state = 'promoted'
              AND g.promoted_at > COALESCE(%s::timestamptz, '-infinity'::timestamptz)
            """,
            (objective["id"], last_coding_at),
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
            discovery_promotions_since_coding=discovery_promotions_since_coding,
            has_unscored_submission=unscored_submission is not None,
            last_experiment_failure_kind=(previous["result"] or {}).get("failure_kind")
            if previous and previous["job_type"] == "experiment_cycle"
            else None,
        )
        constraints = {
            "discovery_cycle": DISCOVERY_CONSTRAINTS,
            "coding_cycle": CODING_CONSTRAINTS,
            "experiment_cycle": EXPERIMENT_CONSTRAINTS,
        }[decision.job_type]

        job_base_commit = system_state["current_baseline_commit"]
        experiment_payload: dict[str, object] = {}
        if decision.job_type == "experiment_cycle":
            if unscored_submission is None:
                raise RuntimeError("policy selected experiment_cycle without an admitted submission")
            job_base_commit = unscored_submission["git_commit"]
            experiment_payload = {
                "submission_id": str(unscored_submission["id"]),
                "controller_manifest": unscored_submission["manifest"],
                "suite_name": "controller_contract_live_smoke",
                "suite_version": "2",
            }

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
                            "discovery_promotions_since_coding": discovery_promotions_since_coding,
                        },
                        **experiment_payload,
                    }
                ),
                json.dumps(constraints),
                job_base_commit,
            ),
        ).fetchone()
        if decision.job_type == "experiment_cycle" and unscored_submission is not None:
            connection.execute(
                "UPDATE bonsai.controller_submissions SET state = 'queued', updated_at = now() WHERE id = %s",
                (unscored_submission["id"],),
            )
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
