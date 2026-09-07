# Real gameplay scorer — suite v4 (`gameplay_survival_development`)

## TL;DR for the operator

**Historical live proof:** the statistical scorer discriminated no-op 0 → developing
0.857 → reference 1.0 and was calibrated at all three horizons. The current
`scorer-build` implementation has since moved to the stepped persistent interaction
model and must receive a fresh live proof before deployment.

**To go live — a single reversible flip** (details below): add the `BONSAI_SUITE==v4`
gate at `evaluator.py:~447`, set `BONSAI_SUITE=v4` in the `bonsai-evaluator` env, restart,
restore autonomy. Revert = unset the env var.

**Remaining operator step:** run one isolated fresh-save and one mature-save evaluation,
then flip only after the receipts, replay and score agree.

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
| `lab_agent/bonsai_lab_agent/session.py` | one live DF: boot, load, observe, dispatch, advance — the single place that talks to DFHack |
| `lab_agent/bonsai_lab_agent/stepped_episode.py` | the ONLY episode driver: observe → decide → sanitize → dispatch → advance a chunk, repeat |
| `lab_agent/bonsai_lab_agent/game_scorer.py` | suite v4 flow: sanitize agent action intents → deterministic dispatch → K episodes → aggregate → result dict |
| `lab_agent/bonsai_lab_agent/dfhack/*.lua,*.sh` | frame-based advance, observer, reachability, wildlife toggle, **deterministic action dispatch**, phased session runner |
| `lab_agent/bonsai_lab_agent/dfhack/probes/` | one-off research scripts; nothing in the runtime calls them and they are not packaged |

**Trust boundary:** the untrusted agent supplies a controller mapping `obs → action
intents`. The evaluator `sanitize_actions()` allow-lists them (`set_labor`,
`designate_dig`, `create_stockpile`, `add_workorder`, `advance`) and dispatches them
via `bonsai-apply-actions.lua` — the agent never runs DFHack or touches DF state.

### Closed-loop action feedback

Each decision after T0 receives `previous_action_feedback`. The receipt records the
requested and accepted intents, gate repairs/refusals, bounded DFHack output, elapsed
ticks, and the observed gameplay delta. This lets a persistent controller stop
repeating an invalid action, satisfy a missing prerequisite, and verify that an accepted
action actually changed the fort. The same gate messages remain in the replay decision
track for audit.

The live observation also carries a trusted `dependencies` view: reachable/claimable
wood, stone, blocks, bars, beds, barrels, seeds and plants; built versus unfinished
workshops and relevant workshop types; active/unassigned/manager jobs; and active
manager-order work remaining. Missing fields from an older deployed observer remain
`null` instead of becoming a false zero. Replay rounds retain both pre- and post-action
dependency snapshots.

## Metric

`score = survival_gate × (0.30·provisioning + 0.20·comfort + 0.50·development)`,
baseline-subtracted `(agent − noop)/(ref − noop)` clamped `[0,1]`, reported as the
K-run **median** with a distribution-free CI. `survival_gate` is a hard multiplier
(any wipe → 0). Observables (ground truth, `bonsai-observe.lua`): T0-cohort survival,
hunger/thirst sums, fort food/drink counts, buildings, dug tiles, completed
workorders, `stress_danger` (count over a threshold). **Excluded:** wildlife/unit
totals, raw item total, raw stress sum.

## Deployment / cutover (execute once a live discrimination proof passes)

**STATUS: historical one-shot path proven; current stepped path awaits live proof.** The
earlier server run proved a real controller → sanitize → live episode → score 0.857 and
all three horizons were calibrated. Current code replaces per-round cold starts with
`persistent_controller.py`, adds dependency observations and action receipts, and adds
the real brewing reaction. These newer changes are locally tested but must not be called
deployed until the isolated fresh/mature runs pass. `score_submission` still heartbeats
between episodes, so a long K-run eval keeps its job lease.
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

### How it actually runs now

The section that stood here described a cutover that has since happened, in terms of
files that no longer exist. Kept short and true instead:

* One episode driver. `stepped_episode.run_stepped_episode` over `session.DFSession`,
  which boots and loads through `bonsai_session.sh` in phases. The one-shot
  `bonsai_episode.sh` runner and the `live_episode.py` module that wrapped it are gone;
  they were a second driver with a second OBS parser and a second EpisodeObs adapter,
  and the copies had drifted — the legacy adapter read a `dug` key the observer never
  emitted, scoring every episode's excavation as zero.
* Endpoints are keyed by `(save, horizon)`, not by horizon alone, and `ref` is the best
  MEASURED tier for that pair rather than a fixed rung of the ladder. Use
  `scoring.calibration_for(save, horizon)`, which returns `None` for a pair nobody has
  measured; the evaluator turns that into `uncalibrated_horizon` rather than a number
  computed against a different fort's baseline.
* `BONSAI_SUITE=v4` routes the evaluator to `game_evaluate.evaluate_job_v4`.


## Interaction model — stepped and persistent

The evaluator now runs `observe → decide → sanitize → apply → advance → observe` for
every round. One controller subprocess remains alive for the whole episode, so it can
compact and retain its own working state instead of cold-starting 24 times. A fresh
process is created for each of the K statistical episodes, preventing cross-episode
state and context leakage.

Round 0 carries the full action schema. Later rounds reference it and carry the current
dependency state plus `previous_action_feedback`: gate repairs/refusals, bounded DFHack
output and actual gameplay deltas. A controller crash or timeout degrades the remaining
rounds of that episode to no-op and is recorded in `controller_processes`; it never turns
an agent failure into evaluator infrastructure failure.

## Known follow-ups
- Live-measure the added dependency-observer cost on the 73-level mature save.
- Verify `brew_drink` against both a fresh farm-grown plant and the mature fort's owned
  reachable barrels; generic `add_workorder` intentionally still rejects fake BrewDrink.
- `embark_scenario` catalog table (save-grain provenance) + `start_state_hash` re-verify.
