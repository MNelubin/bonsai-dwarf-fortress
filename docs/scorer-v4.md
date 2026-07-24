# Real gameplay scorer — suite v4 (`gameplay_survival_development`)

Replaces the degenerate smoke score (`evaluator.evaluation_outcome`, an API-contract
arithmetic `0.2 + 0.2·deterministic + 0.2·valid_actions + 0.4·live_ready` that always
lands ~1.0 and is explicitly "not a 30-day gameplay score") with a **statistical
gameplay score computed from DFHack ground truth the controller cannot forge**.

## Why statistical (not deterministic)

The DF fort sim is **not bit-reproducible** on reload — proven by exhaustive
reverse-engineering (see memory `bonsai-real-scorer-plan`). The residual
nondeterminism is DF's own render↔logic thread concurrency; it is uncontrollable
from outside (RNG pins, clock freeze, `random_device`/`mt_trandom` interposition,
single-core, `SCHED_FIFO` all fail). This is the *correct* formulation anyway: a good
policy must win over the **distribution** of random events (wildlife, later
monsters/sieges), not on one lucky seed.

Calibration (K=8 no-op episodes, full format) showed the **scored dwarf surface is
σ≈0** across independent episodes — survival, hunger, thirst, food, drink, buildings,
workorders are effectively deterministic; only wildlife counts and raw stress are
noisy (excluded; stress enters only as a coarse danger threshold). So K can be small
(≈3–5) with a distribution-free CI + trust gate as the guardrail.

## Components (all TRUSTED — never agent-writable)

| file | role |
|---|---|
| `lab_agent/bonsai_lab_agent/scoring.py` | metric: survival-gated development, K-run median + distribution-free median CI + trust gate |
| `lab_agent/bonsai_lab_agent/live_episode.py` | drives real DF via the bash runner, parses ground-truth OBS → `EpisodeObs` |
| `lab_agent/bonsai_lab_agent/game_scorer.py` | suite v4 flow: sanitize agent action intents → deterministic dispatch → K episodes → aggregate → result dict |
| `lab_agent/bonsai_lab_agent/dfhack/*.lua,*.sh` | frame-based advance, observer, wildlife toggle, **deterministic action dispatch**, canonical episode runner |

**Trust boundary:** the untrusted agent supplies a controller mapping `obs → action
intents`. The evaluator `sanitize_actions()` allow-lists them (`set_labor`,
`designate_dig`, `create_stockpile`, `add_workorder`, `advance`) and dispatches them
via `bonsai-apply-actions.lua` — the agent never runs DFHack or touches DF state.

## Metric

`score = survival_gate × (0.30·provisioning + 0.20·comfort + 0.50·development)`,
baseline-subtracted `(agent − noop)/(ref − noop)` clamped `[0,1]`, reported as the
K-run **median** with a distribution-free CI. `survival_gate` is a hard multiplier
(any wipe → 0). Observables (ground truth, `bonsai-observe.lua`): T0-cohort survival,
hunger/thirst sums, fort food/drink counts, buildings, dug tiles, completed
workorders, `stress_danger` (count over a threshold). **Excluded:** wildlife/unit
totals, raw item total, raw stress sum.

## Deployment / cutover (execute once a live discrimination proof passes)

1. **Verify discrimination live** (blocker): run `bonsai_episode.sh 36000 0` (no-op)
   and `... 36000 0 bonsai-ref-setup` (reference) with `bonsai-df-runtime` UP and the
   reaper/evaluator/orchestrator stopped; confirm reference composite > no-op with the
   trust gate. Calibrate `scoring.CALIBRATION[H] = {noop, ref}` for H ∈ {3600, 12000, 36000}.
2. **Deploy** `scoring.py`, `live_episode.py`, `game_scorer.py` into the installed
   trusted package (`/opt/bonsai-lab-agent/venv/.../bonsai_lab_agent/`) and the
   `dfhack/*` scripts into `/srv/df-bonsai/current/hack/scripts/` +
   `bonsai_episode.sh` into `/srv/df-bonsai/current/`.
3. **Patch `evaluator.evaluate_job`**: after `prepare_checkout` + `controller_command`,
   call `game_scorer.score_submission(controller_fn, horizon_ticks=H, k=K,
   noop_composite=CAL[H].noop, ref_composite=CAL[H].ref)` where `controller_fn(obs)`
   invokes the agent's controller (reuse the jsonl-v1 protocol: write the pinned T0
   obs, read back action intents). Return its result dict instead of the smoke result.
   Set `regime_key = hash(save_sha256, df/dfhack ver, plugin_set, scorer weights, H)`;
   **reset `best_score`/champion when `regime_key` changes** (else the smoke-era 1.0
   freezes the champion forever). Relax the `score∈[0,1]` clamp check in
   `control_plane main.py:524` if needed (v4 stays in [0,1]).
4. **Restore autonomy**: start `bonsai-df-runtime`, `bonsai-evaluator`,
   `bonsai-lab-agent` (CT123) + `bonsai-orchestrator` (CT124); POST `control/running`.
   The K2 agent now climbs the REAL score.

## Known follow-ups
- `dug_tiles` is observed as 0 (TODO: T0 tiletype snapshot + diff over the fort z-range).
- `add_workorder` uses `CustomReaction` (v50 has no `BrewDrink` job_type name); refine
  to real production reactions for stronger food/drink development signal.
- `embark_scenario` catalog table (save-grain provenance) + `start_state_hash` re-verify.
