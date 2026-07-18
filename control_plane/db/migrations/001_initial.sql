BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS bonsai AUTHORIZATION bonsai_owner;

CREATE TABLE IF NOT EXISTS bonsai.system_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    mode text NOT NULL DEFAULT 'running' CHECK (mode IN ('running', 'paused', 'emergency_stop')),
    autonomy_mode text NOT NULL DEFAULT 'automatic_gated' CHECK (autonomy_mode IN ('draft_only', 'automatic_gated')),
    current_baseline_commit text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bonsai.objectives (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id uuid REFERENCES bonsai.objectives(id),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    priority integer NOT NULL DEFAULT 100,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'blocked')),
    cycle_interval_seconds integer NOT NULL DEFAULT 300 CHECK (cycle_interval_seconds >= 30),
    last_job_at timestamptz,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bonsai.jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    objective_id uuid REFERENCES bonsai.objectives(id),
    job_type text NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'leased', 'completed', 'candidate', 'rejected', 'failed', 'cancelled')),
    priority integer NOT NULL DEFAULT 100,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    constraints jsonb NOT NULL DEFAULT '{}'::jsonb,
    progress jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    artifact_hashes text[] NOT NULL DEFAULT '{}',
    base_commit text,
    candidate_commit text,
    lease_owner text,
    lease_token_hash text,
    lease_expires_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 2,
    error text,
    available_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_ready_idx ON bonsai.jobs (priority DESC, created_at) WHERE state = 'queued';
CREATE INDEX IF NOT EXISTS jobs_lease_idx ON bonsai.jobs (lease_expires_at) WHERE state = 'leased';

CREATE TABLE IF NOT EXISTS bonsai.events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_uuid uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    event_type text NOT NULL,
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    previous_hash text,
    event_hash text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_aggregate_idx ON bonsai.events (aggregate_type, aggregate_id, id);
CREATE INDEX IF NOT EXISTS events_created_idx ON bonsai.events (created_at, id);

CREATE TABLE IF NOT EXISTS bonsai.experiments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES bonsai.jobs(id),
    baseline_commit text,
    candidate_commit text,
    state text NOT NULL DEFAULT 'running',
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS bonsai.metrics (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    experiment_id uuid NOT NULL REFERENCES bonsai.experiments(id),
    episode_id text,
    name text NOT NULL,
    value double precision NOT NULL,
    unit text,
    tags jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bonsai.artifacts (
    sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text NOT NULL,
    storage_path text NOT NULL,
    retention_class text NOT NULL DEFAULT 'standard',
    producing_job_id uuid REFERENCES bonsai.jobs(id),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bonsai.git_changes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES bonsai.jobs(id),
    base_commit text NOT NULL,
    candidate_commit text,
    branch_name text,
    changed_paths text[] NOT NULL DEFAULT '{}',
    promotion_state text NOT NULL DEFAULT 'draft',
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    promoted_at timestamptz
);

CREATE TABLE IF NOT EXISTS bonsai.approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action text NOT NULL,
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    decision text NOT NULL,
    actor text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION bonsai.reject_event_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'bonsai.events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS events_append_only ON bonsai.events;
CREATE TRIGGER events_append_only
BEFORE UPDATE OR DELETE ON bonsai.events
FOR EACH ROW EXECUTE FUNCTION bonsai.reject_event_mutation();

INSERT INTO bonsai.system_state (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

INSERT INTO bonsai.objectives
    (title, description, priority, status, cycle_interval_seconds, created_by)
SELECT
    'Build a deterministic DFHack bridge and 30-day CPU baseline',
    'Create reset/observe/act/advance primitives, then run a reproducible rules-based baseline.',
    100,
    'active',
    300,
    'bootstrap'
WHERE NOT EXISTS (SELECT 1 FROM bonsai.objectives);

ALTER TABLE bonsai.system_state OWNER TO bonsai_owner;
ALTER TABLE bonsai.objectives OWNER TO bonsai_owner;
ALTER TABLE bonsai.jobs OWNER TO bonsai_owner;
ALTER TABLE bonsai.events OWNER TO bonsai_owner;
ALTER TABLE bonsai.experiments OWNER TO bonsai_owner;
ALTER TABLE bonsai.metrics OWNER TO bonsai_owner;
ALTER TABLE bonsai.artifacts OWNER TO bonsai_owner;
ALTER TABLE bonsai.git_changes OWNER TO bonsai_owner;
ALTER TABLE bonsai.approvals OWNER TO bonsai_owner;
ALTER FUNCTION bonsai.reject_event_mutation() OWNER TO bonsai_owner;

REVOKE ALL ON SCHEMA bonsai FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA bonsai FROM PUBLIC;
GRANT USAGE ON SCHEMA bonsai TO bonsai_app;
GRANT SELECT, INSERT, UPDATE ON bonsai.system_state, bonsai.objectives, bonsai.jobs,
    bonsai.experiments, bonsai.metrics, bonsai.artifacts, bonsai.git_changes, bonsai.approvals TO bonsai_app;
GRANT SELECT, INSERT ON bonsai.events TO bonsai_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bonsai TO bonsai_app;

COMMIT;

