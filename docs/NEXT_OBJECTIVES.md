# Next objectives

Rewritten 2026-09-07. What stood here described DF 53.15, stub mode, and the question of
whether a headless DFHack could return `cur_year_tick` at all. That was answered a long
time ago, and leaving it in place made the project look like it was still asking it.

The order below is the owner's and is not negotiable from the inside: **mechanics and
action coverage first, then the metric, and only then the autonomous agent.** An agent
built on broken mechanics scores noise, and an agent tuned against a broken metric learns
the wrong game.

## The one canonical path

    session.DFSession        boot / load / prep one fort, in phases (bonsai_session.sh)
    stepped_episode          observe -> decide -> sanitize -> dispatch -> advance, repeat
    actions/ (gate+catalog)  the agent-facing contract; expands and canonicalises intents
    bonsai-apply-actions.lua the deterministic dispatcher
    bonsai-observe.lua       the ground-truth observation
    scoring.py               survival-gated composite, endpoints per (save, horizon)
    game_evaluate            suite v4, what the evaluator actually calls

There is no second driver, no second observation adapter and no second episode runner. If
you find yourself adding one, that is the bug.

Both forts, always: `ourfort16-final` (fresh embark, 7 dwarves) and `region3-lab` (mature,
136 dwarves). Defects show up on one and not the other — the reference tier scores top on
the fresh fort and below idling on the mature one — so a change verified on a single save
is not verified.

## Throughput — how many forts, and where the time goes

Measured 2026-09-07 on CT123 (16 cores, 32 GB).

**Run up to 12 light forts at once, or 8 mature ones.** Twelve concurrent fresh-embark
episodes finished in 74s against 65s for a single one — 14% degradation for twelve times
the work — and all twelve succeeded. The mature save is memory-bound rather than CPU-bound:
each DF holds about 2.9 GB, so four of them already take 17 of the container's 32 GB.

The old rule said two. It came from `advance stalled` failures at four forts, which were
not load at all: `bonsai_episode.sh` killed every fort but the supervised one, three times
a run, so the neighbours died and reported a stall. That script is gone. The limit cost
about a 6x slowdown on every calibration for weeks.

Where an episode's time goes, after the fixes below:

    fresh, 3600 ticks   57-64s   boot+load ~32s, advance ~19s, observe ~5s
    mature, 3600 ticks  234-244s boot+load ~35s, advance ~150s, observe ~50s

Two things were fixed to get there, both verified score-for-score identical (fresh floor
0.467857 and mature floor 0.507812 to the last digit):

* **The observer's solid-tile scan** was 47% of a mature episode — about 7s per call
  against 0.2s on the fresh fort. The pinned box is 139x129x81 there, some 1.9M tiles, and
  the inner loop asked `df.tiletype.attrs[...]` per tile, paying a DFHack wrapper index
  1.9M times a round. Deciding solidity once into a plain Lua array cut it 5332ms to
  1692ms with an identical count.
* **The save menu walk** was 26s of a 51s boot: it clicked into every world in turn,
  sleeping three seconds a step, to find which one held the save. It now remembers the
  row per save and polls instead of sleeping — 26s to 10s, self-correcting if the memory
  is stale.

Reusing a booted DF across episodes was considered and MEASURED rather than assumed:
starting the process is only 3-4s of a ~50s boot, because the menu walk and the map load
dominate and a reused process pays both again. It would buy about 5% while risking the
`_G.BONSAI_*` state that makes episodes independent, so it was not built.

## A — Mechanics and action coverage

Done and measured: the threat channel (proximity, cancellations, real injuries), the
excavation counter (vegetation no longer scores as digging), the wood bootstrap (a fresh
embark can reach its first workshop and its first completed order), labour competition
(fort-wide switches starve everything but the last job switched on).

Open:

1. **Why the mature fort loses dwarves under the survival tier.** 13 of 136 against about
   2 for idling and for plain digging. The standing hypothesis is that outdoor work under
   Forgotten Beasts is simply fatal, which would make it the game being right. It is NOT
   proven. Settle it by ablation: run the tier without `create_stockpile food`, and again
   without `set_crop`/`build_farm_plot`, on `region3-lab`.
2. **The threat guard loses v2's cooldown.** `v3_survival` reads the current
   `under_threat` only, so it resumes sowing on the first clear round while `v2` is still
   holding for three. Tightening it changes measured behaviour on both forts, so it needs
   a measurement, not a patch.
3. **Verb coverage through the gate.** The 2026-09-05 audit wrote raw intents straight
   into the actions file and so mis-tested every gate-expanded verb. Re-run it through
   `actions.sanitize` before trusting any number from it.

## B — The metric

The composite is `survival x (0.30 provisioning + 0.20 comfort + 0.50 development)`.
Measured on both forts at 3600 and 33600 ticks: **comfort is 1.0 for every policy, and
provisioning is identical for every policy.** Half the weight carries no signal at any
horizon we run; all discrimination is development, and on the fresh fort `orders` is
structurally 0 because the embark arrives with fifteen barrels. Two live terms out of five.

0. **Do not run horizons above ~12000 ticks: they measure nothing.** Swept the fresh
   embark at 3600 / 12000 / 33600, k=2. Twelve thousand and thirty-three thousand six
   hundred are identical to six decimals for EVERY tier -- v0 0.478571, v1 0.531472 with
   93 dug, v3 0.569934 with 93 dug and 3 builds -- because the fort finishes what it can
   and then stands still for the remaining 21600 ticks. Only 3600 vs 12000 differ.

   The 93-tile plateau is NOT the dig verb running out of levels. That was the obvious
   explanation and it was built and measured twice, losing both times: cutting on every
   standable level raised 12000 to 108 but dropped the calibrated 3600 horizon from 84 to
   69 and the mature fort from 111 to 98; making it depth-first with a near frontier put
   3600 back and returned 12000 to exactly 93, while the mature fort stayed 30% down,
   because on a mountain fort the surface levels are standable and full of wall so the
   budget goes to chambers far from the miners. Reverted; the reasoning is kept in the
   code so it is not rebuilt a third time.

   What a competent fort actually reaches, against the saturation scales it is measured
   with: dug 93 against a scale of 200, orders 0 against 20, builds 3 against 10. Every
   scale is two to seven times what is achievable, so development spends its whole life
   in its own lower tail.

1. Either make comfort and provisioning able to move within a scored episode — a scenario
   that starts short of food or drink would do it — or stop weighting them as if they
   discriminate and say plainly that they are failure penalties.
2. Size `development`'s saturation scales (200 dug / 20 orders / 10 builds) from what a
   competent fort actually reaches at the chosen horizon, instead of from constants sized
   for a far longer run.
3. `k >= 3` is now mandatory. The fresh fort stopped being deterministic once the
   reference began felling timber and raising buildings: identical code measured 0.5854
   and 0.5921. Do not claim a win inside +/- 0.006.

## C — The player (was: "the autonomous agent")

The player is a compact CPU model, per PROJECT_VISION: no large language model in the
loop during play. A language model may act as an occasional oracle (`player/oracle_llm.py`)
whose answers become training data; it must never be the thing that plays.

Stage B, imitation — DONE. `player/imitation.py` (44 features, reversible action labels,
a pure-Python Student), `collect_trajectories`, `train_imitation` (numpy, CPU, seconds),
`evaluate_student`. The student reproduces v3_survival: fresh 0.5980 vs 0.5971, mature
0.616001 to the digit.

Stage C, improvement against the scorer — RUNNING and it works. `player/evolve.py` is a
cross-entropy method over the Student's output layer, twelve candidates a generation
played in parallel, mature fort as an unselected holdout. 25 generations, 50 minutes:

    k=3, 3600 ticks        evolved student   teacher v3   normalised
    ourfort16-final        0.6666            0.5971       1.54
    region3-lab            0.6342            0.6160       1.23

Everyone alive on both. It found, on its own, the mature fort's opening — bank the
digging before the threat locks you out — and carried it to the fresh embark where no
tier does it: 132 tiles designated at round 0, then the miners work all episode. The
whole final population sits above the teacher (worst of twelve 0.6514).

Weights: `player/weights/student_evolved_v1.json` (3968 params, 88 KB); the per-
generation log beside it.

Next for the player, in order: (1) evolve the hidden layer too, not only the output;
(2) feed the player's discoveries back into the tiers -- dig_request under-asks on the
fresh embark; (3) DAgger on the states where student and teacher disagree; (4) a
scarcity scenario so comfort and provisioning carry signal, which is the owner's call.

## C′ — What "autonomous" meant before

Only after A and B. The agent consumes exactly the contract in `actions/` and the
observation in `stepped_episode`, including `previous_action_feedback` — which is why a
verb that reports `REFUSED` while succeeding, or a threat channel that is always on, had
to be fixed first: those are the only channels it learns from.

Not started, deliberately. The K2 model line is out of scope by the owner's decision.
