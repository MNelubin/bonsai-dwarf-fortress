# Autonomy loop audit — 2026-07-22

## Incident

The autonomous coding loop was paused after making no useful progress for several hours.
The services were alive and jobs were being scheduled, but the same terminal patch failure was
repeated after every cooldown.

## Evidence

In the preceding 24 hours the control database recorded:

- 1,068 failed coding jobs and 17 completed coding jobs;
- about 49,104 seconds of failed coding-job runtime;
- 723 failures with `empty old is only valid for a new file`;
- 1,280 `worker.status_changed` events in two hours;
- two evaluator runs whose result did not contain a parsed live game state.

The event storm came from the coding worker and external evaluator authenticating as the same
`bonsai-lab` worker. The coding graph collected useful proposal diagnostics, but wrote them only to
its trace. The next model attempt received the short exception without the current file bytes or
hash. At the orchestration layer, three matching failures started a ten-minute cooldown; after the
cooldown the exact same path was scheduled again indefinitely.

## Corrections

1. The coding edit protocol now has explicit `replace`, `create`, and `replace_file` operations.
   Full replacement of a tracked file requires the SHA-256 of its current contents, so repair is
   possible without permitting a blind overwrite.
2. A rejected proposal now hands the next graph node bounded current file content, size, and
   SHA-256. An identical rejected proposal is detected and cannot consume the next attempt silently.
   Generic objectives also receive lexically ranked implementation sources; previously a tool-free
   node could see only its invented WIP test and had no implementation file available to edit.
3. Failure epochs survive cooldown boundaries. One three-failure epoch gets one cooldown/recovery
   epoch. If the same fingerprint survives it, the objective is blocked and a paused successor is
   activated (or a bounded successor objective is created). A successful coding promotion clears
   the failure epoch.
4. Cooldown detection now considers the latest terminal jobs, not the latest failures anywhere in
   history. A successful terminal job therefore breaks a failure sequence.
5. The agent and evaluator send separate worker IDs. This removes their shared-row status flapping
   and makes dashboard health meaningful.
6. The evaluator parser accepts ANSI-prefixed, pretty-printed DFHack markers. Evaluator suite v3
   cannot receive a passing score when live game state is absent: its maximum in that case is 0.6.
7. The dashboard shows repeated-failure count, fingerprint, and an actionable error class.
8. Patch-protocol variants share one terminal failure fingerprint, so superficial changes in an
   exception string cannot reset the retry epoch.

## Verification before deployment

- lab agent: 81 pytest tests passed, Ruff passed, MyPy passed for all seven source files;
- control plane: 30 pytest tests passed and Ruff passed;
- MyPy passed for the clean typed control-plane modules (`auth.py`, `cycle_policy.py`);
- full control-plane MyPy still reports pre-existing psycopg row-shape typing debt and is not being
  hidden with global ignores;
- a live guarded DFHack probe returned a valid `bonsai-game-state-v1` object and a successful
  `BONSAI_PROBE_RESULT` marker.

## Remaining boundary

Suite v3 is an independent controller-contract and live-game-API smoke test. It is deliberately not
presented as a fortress episode or 30-day gameplay score. Longer experiments remain available to the
agent through the game API, but promotion must not infer gameplay quality from this smoke score.
