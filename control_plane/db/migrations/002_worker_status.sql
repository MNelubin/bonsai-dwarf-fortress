BEGIN;

CREATE TABLE IF NOT EXISTS bonsai.workers (
    worker_id text PRIMARY KEY,
    worker_type text NOT NULL DEFAULT 'lab_agent',
    status text NOT NULL CHECK (status IN ('idle', 'running', 'error')),
    model text NOT NULL,
    harness text NOT NULL,
    version text NOT NULL,
    current_job_id uuid REFERENCES bonsai.jobs(id),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workers_last_seen_idx ON bonsai.workers (last_seen_at DESC);

ALTER TABLE bonsai.workers OWNER TO bonsai_owner;
REVOKE ALL ON bonsai.workers FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON bonsai.workers TO bonsai_app;

COMMIT;
