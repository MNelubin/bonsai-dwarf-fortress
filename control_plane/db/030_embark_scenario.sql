-- embark_scenario: SAVE-grain provenance for the gameplay scorer. A scenario is a
-- pinned, read-only, active-embarked fort save at a paused T0 (the real determinism
-- anchor — a generated world is inactive; scoring plays one specific embark). The
-- scorer binds scenario_id, never world_id. On redeploy, re-verify start_state_hash;
-- a mismatch marks the scenario 'drifted' (excluded from scoring).
CREATE TABLE IF NOT EXISTS bonsai.embark_scenario (
    scenario_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    world_id         uuid NOT NULL REFERENCES bonsai.world_catalog(id) ON DELETE RESTRICT,
    scenario_kind    text NOT NULL DEFAULT 'fixed_save'
                       CHECK (scenario_kind IN ('fixed_save', 'world_choose')),
    label            text,
    save_path        text NOT NULL,
    save_sha256      text,                    -- sha256 of the save dir (fill on redeploy)
    start_tick       bigint NOT NULL,         -- absolute: cur_year*1e6 + cur_year_tick
    start_state_hash text,                    -- hash(scored T0 observation); drift check
    n_start_dwarves  integer NOT NULL,
    resource_flags   jsonb NOT NULL DEFAULT '{}'::jsonb,
    hazard_flags     jsonb NOT NULL DEFAULT '{}'::jsonb,
    difficulty_tier  text NOT NULL DEFAULT 'baseline',
    split            text NOT NULL DEFAULT 'train'
                       CHECK (split IN ('train', 'validation', 'holdout')),
    df_version       text NOT NULL,
    dfhack_version   text NOT NULL,
    plugin_set_hash  text,
    status           text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'drifted', 'retired')),
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (world_id, save_path, df_version, dfhack_version)
);
ALTER TABLE bonsai.embark_scenario OWNER TO bonsai_owner;
GRANT SELECT, INSERT, UPDATE ON bonsai.embark_scenario TO bonsai_app;

-- The pinned scenario used by the gameplay scorer (world "The Planets of Dawning").
INSERT INTO bonsai.embark_scenario
    (world_id, scenario_kind, label, save_path, start_tick, start_state_hash,
     n_start_dwarves, resource_flags, hazard_flags, difficulty_tier, split,
     df_version, dfhack_version, status)
VALUES
    ('6d96eb45-c084-4292-842e-dcd8e9c4c5e7', 'fixed_save', 'bonsaifort2',
     '/srv/df-bonsai/current/save/bonsaifort2', 2016801,
     '5a05efa5396b788d3e91739869af20959c3a74bed5b9df9e134da53413afa321',
     7, '{"food":12,"drink":12}'::jsonb,
     '{"surface":"savage","cavern_breached":true,"wildlife":"heavy"}'::jsonb,
     'baseline', 'holdout', '53.15', '53.15-r2', 'active')
ON CONFLICT (world_id, save_path, df_version, dfhack_version) DO NOTHING;
