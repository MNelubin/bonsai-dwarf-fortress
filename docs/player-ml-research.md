# The player as an ML problem — what exists, what fits, what to try first

Written 2026-09-13 while `evolve5` runs. This is the research the owner asked for: not a
survey, but the shortlist of methods that fit OUR problem, with the reasons and the order.

## What the problem actually is

Before choosing methods, the shape of the thing:

| property | value | consequence |
|---|---|---|
| observation | 52 hand-built scalars per round (counts, logs, flags, `built_by_type`) | tabular, low-dimensional: MLPs and linear models are the right family, not convnets or transformers |
| action | multi-label over 18 discrete keys, count baked into the key (`designate_dig\|24`) | the policy cannot learn *how much*; only *which* |
| decisions per episode | 24 (up to a month), 288 for a year | short horizon per decision; credit assignment is not the hard part |
| reward | one composite at the END of the episode | sparse — but every round's obs lets us compute the composite *so far*, so a dense per-round signal exists for free |
| episode cost | 90 s fresh / 250 s mature / 200–500 s hungry month; 12 in parallel | ~100 episodes per hour total; sample efficiency matters more than compute |
| noise | fresh spread ±0.006, mature ±0.0008; hungry ±0.05 | fresh and mature are nearly deterministic; hungry is not |
| inference | pure Python on the lab; numpy on the workstation; no torch | anything we train must export to a few thousand floats and a forward pass we can write by hand |
| teacher | a program (`v3_survival`), improved by hand whenever the player finds a rule | imitation is cheap and always available; the loop *program → net → program* is our unusual asset |

So: **small tabular policy, expensive noisy evaluations, a strong programmatic teacher.**
That rules a lot out and points at a few things hard.

## 1. The black-box search we already run — and the three free upgrades

We run a cross-entropy method (elite mean → next mean, Gaussian noise) over ~4k output
weights, 12 candidates a generation. The literature on exactly this regime says three
things, all cheap:

1. **Mirrored (antithetic) sampling.** Sample 6 perturbations and their negatives instead
   of 12 independent ones. Same 12 episodes, roughly half the gradient-estimate variance;
   OpenAI-ES and CMA-ES both adopt it. With our 0.006 spread on fresh, this is the
   difference between a generation telling us something and not.
2. **Rank-based fitness shaping.** Rank the candidates and use centred ranks as weights
   rather than raw scores. Robust to one outlier episode (a Forgotten Beast round) that
   would otherwise drag the mean. CMA-ES uses it for exactly this reason.
3. **Augmented Random Search's two tricks** (Mania, Guy & Recht 2018 — *linear* policies
   trained by random search matched MuJoCo state of the art at 15× the sample efficiency):
   use only the **top-b directions**, and **divide the update by the std of the collected
   rewards** so the step size self-adjusts. Their result also says something about our
   architecture: for a 52-dim observation a linear policy may already be enough, and we
   have never measured that. (Section 4.)

Beyond those: **CMA-ES proper** learns a covariance and would find that `designate_dig`
and `set_labor MINE` move together — but the full covariance is 4k² and 12 samples a
generation cannot estimate it. **sep-CMA-ES** (diagonal covariance) is the fit: per-weight
step sizes, linear cost, works with small populations. It replaces our single `sigma`
with 4k of them. Medium effort; worth it after the free three.

**Elite re-evaluation.** Our `best_ever` is the best of a noisy draw — a winner's curse.
The evolve4 champion re-measured 0.6666 → 0.6153 for two reasons, but this one is
generic and will recur. Re-play the incumbent each generation alongside the candidates
and let it be replaced; never trust a single-episode best.

## 2. Use the reward we throw away

Every round we compute the observation, and `scoring.raw_components` can be computed from
any (T0, obs_now) pair. That is a **dense per-round composite** we currently discard.
Two uses, no new infrastructure:

- **Potential-based shaping for evolution fitness**: fitness = final composite (unchanged
  definition) but log the per-round curve. A policy that reaches 0.6 in round 8 and one
  that reaches it in round 23 tie today; they should not — and the curve tells us where a
  candidate lost.
- **Filtered / weighted behaviour cloning** (the simplest offline RL that works on
  hundreds of episodes, not millions): collect trajectories from the *whole population*
  of every evolution run — we already write them to disk and delete them — then train
  imitation on rows weighted by their episode's normalised score (advantage-weighted
  regression in spirit). The student then learns from what worked across 240 episodes
  instead of from one teacher. This is what turns evolution's by-products into data.

**Return-conditioned supervised learning** (Upside-Down RL, Reward-Conditioned Policies,
Decision Transformer's idea without the transformer): add the episode's normalised score
as an *input feature* at training time, feed a target of 1.2 at play time. Costs one
feature and nothing else. The convergence literature says it works when the environment
is near-deterministic and the data covers the target return — true on fresh and mature
(spread 0.006 / 0.0008), false on the hungry month. So: try it on the fed forts, expect
nothing on hungry.

## 3. The action head is the real architecture limit

The Student outputs one sigmoid per action *key*, and the count is inside the key. So it
can choose `designate_dig|24` or `designate_dig|48` as unrelated labels, and it can never
say 36. Everything the player has "discovered" so far has been *which* and *when*; *how
much* was set by the teacher's `dig_request()`.

Factor the head: **one logit per verb** (does this verb fire) **plus one regression per
verb with a count** (how many, on a log scale, clipped to the catalogue range). Same MLP
body, ~12 verbs + ~6 counts instead of 18 keys. Imitation trains it directly from the teacher's counts; evolution
then moves counts continuously instead of jumping between labels. This is the one change
that lets the player exceed the teacher on *quantities* — the dimension where the teacher
is most obviously hand-tuned (DIG_MIN 12, DIG_MAX 120, CHOP_BATCH 5, `slaughter_animal 3`).

## 4. Layers and width: what to measure, and why deeper is not it

The owner's instinct — play with layer counts and parameters — is right to test and
probably wrong in direction. For 52 tabular inputs and 18 outputs, the evidence (ARS,
and the tabular-ML literature generally) is that **capacity is not the bottleneck**; data
and objective are. What we should sweep, cheaply, on the imitation task (seconds per fit,
held-out F1 per label as the metric):

| variant | params | question it answers |
|---|---|---|
| linear (0 hidden) | ~1.0k | is the teacher linearly separable in our features? if F1 ≈ MLP, evolve the linear one — half the weights, smoother landscape |
| 1 × 32 | ~2.3k | current 64 halved |
| 1 × 64 | ~4.6k | current |
| 1 × 128 | ~9.1k | more width |
| 2 × 64 | ~8.9k | does depth buy anything the width did not |

Measured 2026-09-13 on the 52-feature v3 trajectories (9 episodes: 5 fresh, 2 mature,
2 hungry month; 216 rows; leave-one-episode-out, predictions pooled):

    layers   params   macro-F1   exact-set
    linear     1060     0.931      0.875
    1 x 32     2356     0.989      0.986
    1 x 64     4692     0.989      0.986
    1 x 128    9364     0.989      0.986
    2 x 64     8852     0.990      0.991

So the teacher is NOT linearly separable in our features (the threat hold and the hunger
rule are conjunctions), one hidden layer of 32 is already the whole story, and depth buys
0.001 -- a single row. Capacity is not where the player's ceiling is; §3 (the action
head) and the data are. `student_v3.json` ships at 1 x 64 for continuity with the
evolved weights.

Then the two or three survivors go to the lab for one k=3 ladder each. Expect the linear
model to lose on a few labels (the threat hold is an AND of conditions) and 1×64 to be
enough; if 2×64 wins on held-out F1 but loses live, that is overfitting to the teacher's
quirks and we keep 1×64.

Cheaper than any of that and more likely to matter: **the threshold**. 0.5 on every
label is arbitrary; per-label thresholds tuned on held-out precision/recall (or a single
global one swept 0.3–0.7 live) changes behaviour more than a layer does.

**Recurrence** (GRU) is the other architectural knob people reach for. Not yet: our
observation already carries `round`, `rounds_total`, `previous_action_feedback` and the
`built_by_type` memory the fort itself keeps. If a case appears where the policy needs
what it saw three rounds ago and the fort does not remember it for it, **frame-stack**
the last two feature vectors (104 inputs) before reaching for a recurrent cell — same
family, no new training machinery.

## 5. Distil the player back into a program (close the loop the other way)

The teacher is code; the player is weights; the rule that the player found (bank the
digging early) went into the code *by hand*. VIPER (Bastani, Pu & Solar-Lezama 2018)
does this mechanically: fit a **decision tree** to the network's decisions with DAgger,
weighting states by how much the choice matters there. Trees are tiny, verifiable, run
anywhere, and — for us — *read like tier rules*. A tree that says "if wood < 8 and round
< 4: chop" is a `tiers.py` line. This is how the `program → net → program` loop stops
needing me to read traces.

## 6. Diversity instead of one champion

Selecting on the summed normalised score across three scenarios (what `evolve5` does)
is the right minimum. The next step when the scenarios pull in different directions is
**quality-diversity (MAP-Elites)**: keep an archive of elites indexed by behaviour (dug,
buildings, food gained), not one best. The archive *is* a curriculum of policies for the
teacher to read, and the winning strategy on the hungry month (butcher) is a different
cell from the winning strategy on the mature fort (dig, hold). CMA-ME exists for this;
for our scale a hand-rolled 3-D grid is enough.

## What NOT to do, and why

- **Policy gradients (PPO, SAC).** ~100 episodes/hour, 24 decisions each: 2 400
  transitions an hour. PPO wants millions. Random search / ES is the right regime for
  expensive, few, noisy evaluations, which is the ARS point.
- **Transformers / Decision Transformer as a model.** Sequence length 24, tabular
  inputs, no pretraining data: the *idea* (return conditioning) transfers; the model
  does not.
- **Gradient-boosted trees as the policy.** Best-in-class for tabular imitation, and
  we could fit one in seconds — but it cannot be evolved and we would have to write a
  tree-ensemble forward pass in pure Python for the lab. Use trees for §5
  (distillation), not for play.
- **NEAT / topology evolution.** Overkill for a 52→18 map; spend the episodes on
  weights.
- **A large LLM in the loop during play.** Out by PROJECT_VISION. Oracle only.

## Order of work (effort vs. what it can move)

1. **Free upgrades to `evolve.py`**: mirrored sampling, rank shaping, incumbent
   re-evaluation. An afternoon; every later run benefits.
2. **Architecture sweep on imitation** (linear / 1×32 / 1×64 / 1×128 / 2×64, plus
   threshold): minutes on the workstation, then one ladder for the top two.
3. **Factored action head** (verb logit + count regression). The one change that lets
   the player own the quantities.
4. **Population trajectories → weighted imitation** (keep what evolution deletes; train
   on it weighted by normalised score). Return-conditioning as a one-feature experiment
   on the fed forts.
5. **sep-CMA-ES** in place of the single sigma.
6. **VIPER-style tree distillation** of whatever champion stands, read as candidate
   tier rules.
7. **MAP-Elites** archive when the scenarios start disagreeing about the champion.

## Sources

- Mania, Guy, Recht — *Simple random search provides a competitive approach to
  reinforcement learning* (ARS), 2018. https://arxiv.org/abs/1803.07055
- Salimans et al. — *Evolution Strategies as a Scalable Alternative to RL*, 2017 (mirrored
  sampling, fitness shaping). https://arxiv.org/abs/1703.03864
- Hansen — *The CMA Evolution Strategy: a tutorial* (rank-based weights; sep-CMA-ES in
  Ros & Hansen 2008). https://arxiv.org/abs/1604.00772
- Weng — *Evolution Strategies* overview. https://lilianweng.github.io/posts/2019-09-05-evolution-strategies/
- Bastani, Pu, Solar-Lezama — *Verifiable RL via Policy Extraction* (VIPER), 2018.
  https://arxiv.org/abs/1805.08328
- Schmidhuber / Srivastava et al. — *Upside-Down RL*, 2019; Kumar, Peng, Levine —
  *Reward-Conditioned Policies*, 2019; Brandfonbrener et al. — *When does return-
  conditioned supervised learning work for offline RL?*, 2022.
  https://arxiv.org/abs/1912.02877 , https://arxiv.org/abs/1912.13465 , https://par.nsf.gov/servlets/purl/10386429
- Ross, Gordon, Bagnell — *DAgger*, 2011. https://arxiv.org/abs/1011.0686
- Mouret & Clune — *Illuminating search spaces by mapping elites* (MAP-Elites), 2015;
  Fontaine et al. — *CMA-ME*, 2020. https://arxiv.org/abs/1504.04909 , https://arxiv.org/abs/1912.02400
- Bai et al. — *Evolutionary Reinforcement Learning: A Survey*, 2023. https://arxiv.org/abs/2303.04150
