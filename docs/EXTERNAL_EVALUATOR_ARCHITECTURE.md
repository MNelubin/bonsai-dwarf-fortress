# External evaluator loop

## Purpose

The coding agent may inspect and experiment with the live DFHack API directly, but it does not
decide whether its own controller is better. A separate evaluator worker leases only
`experiment_cycle` jobs, checks out the exact promoted commit, runs a bounded suite, and stores
structured measurements in PostgreSQL.

Code admission and game quality are deliberately separate:

1. promotion gates answer whether a commit is safe, reproducible, typed, linted, and tested;
2. evaluator suites measure behaviour and score controllers;
3. a low score never rejects or reverts a promoted commit;
4. only a better score changes the objective champion;
5. repeated infrastructure failures trigger a finite cooldown, not an infinite rejection loop.

## Controller contract

A `controller_submission` points at an immutable Git commit and a JSON manifest. The first
protocol is JSON Lines v1. The evaluator writes one request per line:

```json
{"type":"observation","episode_id":"fixture-0","step":0,"observation":{}}
```

The controller responds with exactly one line:

```json
{"action":{"command":"observe"}}
```

or `{"action": null}` to stop. Manifests can select either a Python callable such as
`player.baseline:baseline_policy` or an arbitrary argv command implementing the same protocol.
This allows rules, a tiny CPU model, a planner, an LLM-backed policy, or a hybrid without changing
the evaluator.

## Stages

- `controller_contract_v1`: deterministic fixtures, protocol validation, determinism, latency.
- `live_df_api_smoke_v1`: bounded read-only contact with the supervised DFHack runtime.
- later suites: resettable pinned saves, short survival curricula, then the expensive 30-day suite.

The early stages are not substitutes for the 30-day benchmark. They make failures cheap and
classify them before GPU time is spent on another coding cycle.

## Scheduling graph

`discovery -> coding -> promotion -> submission -> experiment -> coding/discovery`

The orchestrator always evaluates an unscored promoted submission before asking the LLM for more
code. An evaluator/game-API failure routes one bounded discovery cycle. A controller-quality result
routes a coding cycle with the score and evidence in the handoff. Repeated identical failures pause
that objective for a cooldown and preserve all evidence.

## Trust boundary

The evaluator is a distinct systemd service and worker capability. The coding worker cannot lease
its jobs. Candidate controller code runs as a bounded subprocess and communicates over JSONL.
The current deployment shares the DF lab LXC because that is where the supervised game exists;
moving the evaluator service into a dedicated LXC later will not change the database or controller
protocol.

The direct `bonsai-df-probe` route remains available to discovery and coding cycles. It is an
exploration surface, while evaluator results are the comparable measurement surface.
