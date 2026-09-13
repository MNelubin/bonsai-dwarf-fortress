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

0. **On a FED fort, horizons above ~12000 ticks measure nothing.** Swept the fresh
   embark at 3600 / 12000 / 33600, k=2. Twelve thousand and thirty-three thousand six
   hundred are identical to six decimals for EVERY tier -- v0 0.478571, v1 0.531472 with
   93 dug, v3 0.569934 with 93 dug and 3 builds -- because the fort finishes what it can
   and then stands still for the remaining 21600 ticks. Only 3600 vs 12000 differ. The
   long horizon earns its keep only when the fort is in trouble: see the hungry scenario
   below, where a month separates the tiers by 0.26.

   The 93-tile plateau is NOT the dig verb running out of levels. That was the obvious
   explanation and it was built and measured twice, losing both times: cutting on every
   standable level raised 12000 to 108 but dropped the calibrated 3600 horizon from 84 to
   69 and the mature fort from 111 to 98; making it depth-first with a near frontier put
   3600 back and returned 12000 to exactly 93, while the mature fort stayed 30% down,
   because on a mountain fort the surface levels are standable and full of wall so the
   budget goes to chambers far from the miners. Reverted; the reasoning is kept in the
   code so it is not rebuilt a third time.

   What a competent fort actually reaches, against the saturation scales it is measured
   with (now 100 dug / 10 orders / 3 builds): dug 83-94 and builds 3 on the fresh embark
   at 3600, so development can reach its ceiling; orders stays 0 there because the embark
   arrives with fifteen barrels.

1. DONE, as a scenario. **A scenario is a save plus a prep script**
   (`BONSAI_EPISODE_PREP`, `scenario_id() = "save+prep"`), because DFHack cannot write a
   save headless. `bonsai-prep-hungry` strips every food and drink item from the wagon
   and sets the citizens' hunger and thirst near the edge. Over a fort-month (33600
   ticks), k=3:

       ourfort16-final + bonsai-prep-hungry, 33600   composite   what happened
       v0_idle                                       0.163       nobody eats
       v2_reactive                                   0.195       same, with a stockpile
       v1_developer                                  0.276       206 tiles, dead dwarves
       v3_survival                                   0.421       butchers, food 0 -> 42, comfort 0.939

   Nobody had a way out until `slaughter_animal` existed: the embark carries seven
   animals and no verb could turn them into food. The rule is in `v3_survival` (BUTCHER
   labour, a Butchers shop, `slaughter_animal 3` once) and the pair is in CALIBRATION.
   Comfort and provisioning finally carry signal here: 0.442 vs 0.939, 0.25 vs 0.50.
   A gathering rule was tried on the same scenario and removed - it never moved
   provisioning inside a month.

2. DONE. Saturation scales are 100 dug / 10 orders / 3 builds, sized from what the
   reference reaches at 3600; workshops count once per kind, so eight stills are one
   still and the champion's building trick stopped paying.
3. `k >= 3` is now mandatory. The fresh fort stopped being deterministic once the
   reference began felling timber and raising buildings: identical code measured 0.5854
   and 0.5921. Do not claim a win inside +/- 0.006.

4. **Decision density follows the calendar past a month.** 24 rounds from three days to
   a fort-month (a decision every ~1.2 days at the top); beyond that `rounds_for()` caps
   the chunk at 1400 ticks, so a fort-year is 288 decisions and not one a fortnight. Both
   calibrated horizons still land on exactly 24, so no endpoint moved.
5. **DFHack automations stay OFF.** Read on the lab 2026-09-13: autobutcher, autofarm,
   seedwatch, autoclothing, autofish, autolabor - all disabled. Nothing to switch off to
   help learning, and nothing switched on to do the player's work for it. Exposing one
   (say `autobutcher`) as a verb would let the policy delegate the whole mechanic; the
   line taken is the raw verb (`slaughter_animal`) so the chain - labour, shop, order -
   is the thing learned. Revisit only if a mechanic turns out to be unreachable through
   raw verbs.

## C — The player (was: "the autonomous agent")

The player is a compact CPU model, per PROJECT_VISION: no large language model in the
loop during play. A language model may act as an occasional oracle (`player/oracle_llm.py`)
whose answers become training data; it must never be the thing that plays.

Stage B, imitation — DONE. `player/imitation.py` (52 features, append-only; older
weights carried forward by `widen.py`), reversible action labels, a pure-Python Student,
`collect_trajectories`, `train_imitation` (numpy, CPU, seconds), `evaluate_student`. The
student reproduces v3_survival: fresh 0.5980 vs 0.5971, mature 0.616001 to the digit.

Stage C, improvement against the scorer — RUNNING. `player/evolve.py` is a cross-entropy
method over the Student's output layer, twelve candidates a generation played in
parallel. The first run (25 generations, 50 minutes) reported fresh 0.6666 / mature
0.6342 against the teacher's 0.5971 / 0.6160. Half of that was real and half was a
hole: it found the mature fort's opening on its own -- bank the digging before the
threat locks you out, 132 tiles at round 0 -- and it also found that eight stills were
eight buildings. Once workshops counted once per kind and the rule had absorbed the
dig bank, the same weights re-measured (k=3, 2026-09-13):

    champion (student_evolved_v1, widened to 52)   composite   normalised
    ourfort16-final, 3600                          0.6153      0.99
    region3-lab, 3600                              0.6334      0.99
    ourfort16-final + hungry, 33600                0.2622      0.38   (never butchers)

Parity with the teacher on the fed forts, and no idea what to do when the wagon is
empty, because the teacher only learned that after the champion was trained.

Two things were then measured side by side (k=3, 2026-09-13, normalised in brackets):

    weights                                  fresh          mature         hungry month     sum
    student_v3 (imitation, factored head)    0.6187 [1.01]  0.6227 [0.88]  0.4215 [1.00]    2.89
    evolve5 champion (CEM, 20 gens)          0.6116 [0.96]  0.6602 [1.26]  0.2045 [0.16]    2.38
    evolve5's own claim for that champion    0.6125 [0.97]  0.6602 [1.26]  0.3062 [0.55]    2.78

The imitation student that simply KNOWS the butcher chain beats twenty generations of
search that did not start with it. The CEM champion found something real on the mature
fort — 0.6602 three times to the digit, one more order and one building over the teacher
— and paid for it on the hungry month, where its single selection episode said 0.31 and
three said 0.20. That gap is the winner's curse the ARS method exists to remove: the
shipped model is now the re-played mean, never the best candidate. Kept as
`student_evolved_v2_cem.json` for the mature-fort trick it carries.

`evolve6` runs ARS from `student_v3` on all three scenarios. Whatever it ships has been
measured on every scenario as itself.

Weights: `player/weights/student_evolved_v1.json` (3968 params, 88 KB); the per-
generation log beside it.

Next for the player, in order: (1) read what the CEM champion does on the mature fort
(one more order, one building) and, if it is a rule, put it in the teacher; (2) keep
the trajectories every evolution run deletes and train on them weighted by normalised
score (docs/player-ml-research.md §2); (3) DAgger on the states where student and
teacher disagree; (4) a fort-year scenario now that decision density follows the
calendar. The architecture question is closed for now: docs/player-ml-research.md §4.

## C′ — What "autonomous" meant before

Only after A and B. The agent consumes exactly the contract in `actions/` and the
observation in `stepped_episode`, including `previous_action_feedback` — which is why a
verb that reports `REFUSED` while succeeding, or a threat channel that is always on, had
to be fixed first: those are the only channels it learns from.

Not started, deliberately. The K2 model line is out of scope by the owner's decision.
