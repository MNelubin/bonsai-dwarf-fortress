# Real gameplay scorer — suite v4 (`gameplay_survival_development`)

## TL;DR for the operator

**Done & proven** (branch `scorer-build`, ~19 commits, all trusted modules pre-staged +
verified on the server; 36 unit tests): a statistical DF gameplay scorer that replaces
the degenerate ~1.0 smoke score. Discrimination proven live (no-op 0 → developing 0.857
→ reference 1.0), validated end-to-end k=1 **and** k=3 (trustworthy), calibrated at all
three horizons, heartbeat-safe for the 120s job lease, needs **no control-plane changes**.

**To go live — a single reversible flip** (details below): add the `BONSAI_SUITE==v4`
gate at `evaluator.py:~447`, set `BONSAI_SUITE=v4` in the `bonsai-evaluator` env, restart,
restore autonomy. Revert = unset the env var.

**Two decisions only you can make** (everything technical is closed):
1. **Interaction model** — v4 uses one-shot SETUP (controller returns T0 development
   intents). Your 93 submissions use a step-loop `advance` baseline that develops nothing
   → would score 0. Fix cheaply by (a) pointing the objective prompt at "return a T0
   setup plan" + giving `player.baseline` a couple of `create_stockpile`/`set_labor`
   intents, or (b) building the hybrid interactive loop (bigger). See "Interaction model".
2. **When to flip** — verify one real eval, then restore autonomy.

Everything else in this doc is the how/why.

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

**STATUS: pre-staged, verified, and proven end-to-end.** All trusted modules (`scoring.py`,
`live_episode.py`, `game_scorer.py`, `controller_invoke.py`, `game_evaluate.py`) are
deployed to the installed package and import cleanly alongside the running evaluator
(additive — cannot break it). The DFHack scripts + `bonsai_episode.sh` are in
`/srv/df-bonsai/current/`. Discrimination is proven and **all three rungs are
live-calibrated** (H=3600/12000/36000, all +0.055 no-op→ref). The **full v4 path was
proven end-to-end on the server** (a real controller → `make_controller_fn` → sanitize
→ live episode → score 0.857 for a 4-stockpile policy). `score_submission` heartbeats
between episodes via `on_episode`, so a long K-run eval keeps its job lease.
**The entire cutover is a single reversible flip** owned by the operator:

- **Flip (safest, env-gated, defaults to smoke):** at `evaluator.py:~447`, replace
  `result = evaluate_job(config, job)` with:
  ```python
  if os.environ.get("BONSAI_SUITE") == "v4":
      from bonsai_lab_agent import game_evaluate
      result = game_evaluate.evaluate_job_v4(config, job, api=api)
  else:
      result = evaluate_job(config, job)          # smoke default (unchanged)
  ```
  Then set `BONSAI_SUITE=v4` (and optionally `BONSAI_SCORE_HORIZON`, `BONSAI_SCORE_K`)
  in the `bonsai-evaluator` systemd env, and restart. Revert = unset the env var.
- **Champion reset is NOT required for the flip.** Promotion (`promoter.inspect_candidate`)
  is currently `gate_mode: bootstrap_static_v1` — it gates on STATIC SAFETY only (secret
  scan, syntax parse, size limit) and does **not** compare the evaluation score against a
  champion/best_score. So flipping to v4 simply changes the *recorded* score (smoke →
  gameplay); promotion behaviour is unchanged and nothing is "frozen" by the smoke-era
  1.0. `game_evaluate` still attaches `regime_key` — reset the champion on its change
  ONLY once promotion becomes score-gated (a separate future evolution).
- **Job lease is handled — no control-plane change needed.** The control plane's
  `lease_seconds=120` would expire mid-episode (an H=36000 episode is ~10 min), but
  `evaluate_job_v4(config, job, api=api)` runs a background thread that heartbeats every
  `HEARTBEAT_INTERVAL` (45s, env-tunable) for the whole eval, renewing the lease. Just
  pass `api=api` at the flip (the snippet above does). Optionally still raise
  `lease_seconds` for headroom, but it is not required.
- Restore autonomy: start `bonsai-df-runtime`, `bonsai-evaluator`, `bonsai-lab-agent`
  (CT123) + `bonsai-orchestrator` (CT124); POST `control/running`.

### Legacy step detail (superseded by the pre-staged flip above)

1. **Verify discrimination live** (blocker): run `bonsai_episode.sh 36000 0` (no-op)
   and `... 36000 0 bonsai-ref-setup` (reference) with `bonsai-df-runtime` UP and the
   reaper/evaluator/orchestrator stopped; confirm reference composite > no-op with the
   trust gate. Calibrate `scoring.CALIBRATION[H] = {noop, ref}` for H ∈ {3600, 12000, 36000}.
2. **Deploy** `scoring.py`, `live_episode.py`, `game_scorer.py` into the installed
   trusted package (`/opt/bonsai-lab-agent/venv/.../bonsai_lab_agent/`) and the
   `dfhack/*` scripts into `/srv/df-bonsai/current/hack/scripts/` +
   `bonsai_episode.sh` into `/srv/df-bonsai/current/`.
3. **Patch `evaluator.evaluate_job`**: after `prepare_checkout` + `controller_command`,
   replace the fixture/smoke path with (all building blocks exist + tested):
   ```python
   from bonsai_lab_agent import game_scorer
   from bonsai_lab_agent.controller_invoke import make_controller_fn
   from bonsai_lab_agent.scoring import CALIBRATION
   H = 3600                                   # active ladder rung (3600/12000/36000)
   cal = CALIBRATION[H]                        # {noop, ref}; must be calibrated for H
   controller_fn = make_controller_fn(command, str(repo), config.controller_timeout_seconds)
   result = game_scorer.score_submission(
       controller_fn, horizon_ticks=H, k=5,
       noop_composite=cal["noop"], ref_composite=cal["ref"])
   return {**result, "submission_id": submission_id,
           "result_hash": hashlib.sha256(json.dumps(result["summary"], sort_keys=True,
                                                     default=str).encode()).hexdigest()}
   ```
   Optionally keep the contract smoke as a cheap gate-0 (run it first; only score
   gameplay if it passes). Set `regime_key = hash(save_sha256, df/dfhack ver,
   plugin_set, scorer weights, H)`; **reset `best_score`/champion when `regime_key`
   changes** (else the smoke-era 1.0 freezes the champion forever). v4 scores stay in
   `[0,1]` so the `control_plane main.py:524` clamp is fine.
   CAVEAT: `score_submission` runs K live DF episodes (~2–10 min each depending on H
   and host load), so raise the evaluator job timeout / heartbeat accordingly.
4. **Restore autonomy**: start `bonsai-df-runtime`, `bonsai-evaluator`,
   `bonsai-lab-agent` (CT123) + `bonsai-orchestrator` (CT124); POST `control/running`.
   The K2 agent now climbs the REAL score.

## Interaction model — the ONE integration decision left for the owner

This is not a bug; it's a design reconciliation the owner should make before/at the flip.

- **v4 uses a one-shot SETUP model:** the controller is invoked once with the pinned T0
  observation and returns action *intents* (`set_labor`, `designate_dig`,
  `create_stockpile`, `add_workorder`); the evaluator dispatches them at T0, then the
  episode advances to the horizon and is scored.
- **The existing 93 agent submissions all use `player.baseline:baseline_policy`**, a
  **step-loop** policy that returns `{"command": "advance", ...}` repeatedly (advance,
  check survivors, advance…). Under v4's one-shot setup, a policy that returns only
  `advance` develops nothing → **scores at the no-op baseline (0)**. So out of the box,
  v4 would score every current submission ~0 (no learning gradient) until the agent
  writes policies that return development intents.
- v4 now hands the controller a **policy-compatible + discoverable** observation
  (`controller_observation`): the v4 scored fields PLUS `cur_tick`/`gametype`/`paused`/
  `units` (so legacy policies don't crash) PLUS `available_actions` (so the agent can
  discover the verbs). But the *interaction model* still differs.

**Owner's choice:**
1. **Keep one-shot setup (recommended, already built):** point the objective/prompt at
   "return a T0 setup plan of development intents"; update `player.baseline` to emit a
   couple of `create_stockpile`/`set_labor` intents (so the floor isn't a flat 0), and
   let the agent climb from there. Minimal work — the scorer already supports this.
2. **Add a hybrid interactive loop:** extend the episode driver so the controller is
   re-invoked each chunk (observe → intents → apply → advance chunk → observe…), which
   also honors step-loop `advance` returns. This matches the legacy convention but is a
   real change to the episode driver (keep DF alive across steps; observe/apply/advance
   as separate ops) + live testing. Left unbuilt — it's a design decision, not a defect.

Everything else in the cutover is closed; this is the substantive call the owner makes.

## Known follow-ups
- `dug_tiles` is observed as 0 (TODO: T0 tiletype snapshot + diff over the fort z-range).
- `add_workorder` uses `CustomReaction` (v50 has no `BrewDrink` job_type name); refine
  to real production reactions for stronger food/drink development signal.
- `embark_scenario` catalog table (save-grain provenance) + `start_state_hash` re-verify.
