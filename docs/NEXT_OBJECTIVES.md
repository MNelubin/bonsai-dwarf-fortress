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

1. Either make comfort and provisioning able to move within a scored episode — a scenario
   that starts short of food or drink would do it — or stop weighting them as if they
   discriminate and say plainly that they are failure penalties.
2. Size `development`'s saturation scales (200 dug / 20 orders / 10 builds) from what a
   competent fort actually reaches at the chosen horizon, instead of from constants sized
   for a far longer run.
3. `k >= 3` is now mandatory. The fresh fort stopped being deterministic once the
   reference began felling timber and raising buildings: identical code measured 0.5854
   and 0.5921. Do not claim a win inside +/- 0.006.

## C — The autonomous agent

Only after A and B. The agent consumes exactly the contract in `actions/` and the
observation in `stepped_episode`, including `previous_action_feedback` — which is why a
verb that reports `REFUSED` while succeeding, or a threat channel that is always on, had
to be fixed first: those are the only channels it learns from.

Not started, deliberately. The K2 model line is out of scope by the owner's decision.
