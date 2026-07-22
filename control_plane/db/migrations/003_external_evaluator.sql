BEGIN;

CREATE TABLE IF NOT EXISTS bonsai.controller_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    objective_id uuid NOT NULL REFERENCES bonsai.objectives(id),
    source_job_id uuid REFERENCES bonsai.jobs(id),
    git_commit text NOT NULL CHECK (git_commit ~ '^[0-9a-f]{40}$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    manifest jsonb NOT NULL,
    state text NOT NULL DEFAULT 'admitted'
        CHECK (state IN ('admitted', 'queued', 'evaluating', 'scored', 'invalid')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (objective_id, content_hash)
);

CREATE TABLE IF NOT EXISTS bonsai.objective_evaluation_state (
    objective_id uuid PRIMARY KEY REFERENCES bonsai.objectives(id),
    champion_submission_id uuid REFERENCES bonsai.controller_submissions(id),
    best_score double precision,
    submissions_seen integer NOT NULL DEFAULT 0,
    evaluations_completed integer NOT NULL DEFAULT 0,
    consecutive_no_improvement integer NOT NULL DEFAULT 0,
    max_evaluations integer NOT NULL DEFAULT 40 CHECK (max_evaluations > 0),
    max_no_improvement integer NOT NULL DEFAULT 10 CHECK (max_no_improvement > 0),
    last_failure_fingerprint text,
    repeated_failure_count integer NOT NULL DEFAULT 0,
    cooldown_until timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE bonsai.experiments
    ADD COLUMN IF NOT EXISTS submission_id uuid REFERENCES bonsai.controller_submissions(id),
    ADD COLUMN IF NOT EXISTS suite_name text,
    ADD COLUMN IF NOT EXISTS suite_version text,
    ADD COLUMN IF NOT EXISTS score double precision,
    ADD COLUMN IF NOT EXISTS verdict text,
    ADD COLUMN IF NOT EXISTS failure_kind text,
    ADD COLUMN IF NOT EXISTS budget_seconds integer,
    ADD COLUMN IF NOT EXISTS result_artifact_hash text;

CREATE UNIQUE INDEX IF NOT EXISTS experiments_job_unique_idx ON bonsai.experiments(job_id);
CREATE INDEX IF NOT EXISTS submissions_objective_state_idx
    ON bonsai.controller_submissions(objective_id, state, created_at);
CREATE INDEX IF NOT EXISTS experiments_submission_idx
    ON bonsai.experiments(submission_id, completed_at);
CREATE INDEX IF NOT EXISTS metrics_experiment_name_idx
    ON bonsai.metrics(experiment_id, name);

INSERT INTO bonsai.objective_evaluation_state (objective_id)
SELECT id FROM bonsai.objectives
ON CONFLICT (objective_id) DO NOTHING;

ALTER TABLE bonsai.controller_submissions OWNER TO bonsai_owner;
ALTER TABLE bonsai.objective_evaluation_state OWNER TO bonsai_owner;
GRANT SELECT, INSERT, UPDATE ON bonsai.controller_submissions,
    bonsai.objective_evaluation_state TO bonsai_app;

COMMIT;
