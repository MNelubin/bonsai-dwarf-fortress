# Next Objectives

All milestones M1–M6 (knowledge base, JSON contract, episode runner, 30-day baseline,
curricula, CPU inference policy) are implemented and tested in stub mode against the
EpisodeRunner.  The smallest falsifiable improvements target real DFHack integration.

## Objective A — Live DFHack observe probe
**Hypothesis:** `core.lua` can call `df.global.cur_year_tick` inside a headless DF process
and receive a non-`nil` integer once a save is loaded.

**Experiment:**
1. Launch `dwarfort` in text/headless mode with `DFHack` injected.
2. Load a minimal pre-made save (or create via `createmap`).
3. Execute `lua dofile(bridge/core.lua)` and capture JSON from `bridge.observe()`.
4. Assert `cur_year_tick` is an integer ≥ 0 and `units` is a list.

**Failure modes:** API drift in 53.15-r2, missing save directory, or segfault on headless
launch.  If the script cannot load, fall back to `dfhack.query()` CLI.

## Objective B — Deterministic seed-to-state reproducibility
**Hypothesis:** Two episodes loaded from the same pinned save with identical action sequences
produce byte-identical observation traces (modulo monotonic bridge tick counter).

**Experiment:**
1. Pin a save at a known path (`/srv/df-bonsai/state/saves/dark_kelp`).
2. Run two back-to-back stub episodes with `seed=42`, compare JSON traces step by step.
3. Assert all observation diffs are zero outside the `tick` field.

**Failure modes:** Internal DF RNG seeded from wall clock, or filesystem timestamps
leaking into observations.  Mitigate by fixing the worldgen seed in save options.

## Objective C — Skill-chained episode survives 7 real game days ✅ stub-verified
**Status:** `player/skill_chain.py` implemented. `make_skill_chain(*skills)` returns a
callable policy that the EpisodeRunner accepts. Curriculum level
`survive_7_days_skill_chain` added and tested deterministically (53/53 tests pass).

**What works:**
- Skill composition: `StartFortress → AdvanceTimeStep(ticks=5*D) → CheckSurvivors`
- Per-step FIFO action buffer with `_reset()` for episode boundaries
- Terminal detection when all skills return None
- 7-day tick threshold reached in stub episodes (≥604,800 ticks advanced)

**Remaining:** live DF test requires headless `dwarfort` launch + save load cycle.
See Objective A (live observe probe) as the prerequisite.

**Failure modes:** Live DF takes too long for CI; bound wall clock at 120 s per episode.
