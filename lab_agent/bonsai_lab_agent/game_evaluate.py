"""Drop-in v4 evaluate_job for the trusted evaluator (the production cutover).

ADDITIVE: this is a NEW module — it does NOT modify evaluator.py. The cutover is a
single change in evaluator.main(): call `game_evaluate.evaluate_job_v4(config, job)`
instead of `evaluate_job(config, job)` (or gate it behind BONSAI_SUITE=v4). Reversible
by reverting that one line.

It reuses the evaluator's own checkout/controller helpers (lazy-imported so this module
stays importable + unit-testable without the server-only evaluator present), invokes the
untrusted controller for action intents, and scores real gameplay via game_scorer. A
regime_key is attached so the orchestrator resets the champion when the scoring regime
changes (else the smoke-era 1.0 freezes it forever).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any

from bonsai_lab_agent import game_scorer
from bonsai_lab_agent.persistent_controller import make_persistent_controller_fn
from bonsai_lab_agent.scoring import CALIBRATION

DEFAULT_HORIZON = int(os.environ.get("BONSAI_SCORE_HORIZON", "3600"))
DEFAULT_K = int(os.environ.get("BONSAI_SCORE_K", "5"))
DF_VERSION = os.environ.get("BONSAI_DF_VERSION", "53.15")
DFHACK_VERSION = os.environ.get("BONSAI_DFHACK_VERSION", "53.15-r2")
# Renew the job lease well inside the control plane's lease_seconds (=120s) — a single
# episode (up to ~10 min at H=36000) far exceeds it, so per-episode heartbeats alone
# would let the lease expire mid-episode and the job get re-leased.
HEARTBEAT_INTERVAL = int(os.environ.get("BONSAI_HEARTBEAT_SECONDS", "45"))


def _uncalibrated(submission_id, horizon: int) -> dict[str, Any]:
    return {
        "submission_id": submission_id,
        "suite_name": game_scorer.SUITE_NAME, "suite_version": game_scorer.SUITE_VERSION,
        "score": 0.0, "verdict": "uncalibrated_horizon", "failure_kind": "config",
        "summary": {"horizon_ticks": horizon,
                    "reason": "no live CALIBRATION endpoints for this horizon"},
        "metrics": [],
    }


def evaluate_job_v4(config, job: dict[str, Any], api=None) -> dict[str, Any]:
    """Score one submission by running K real gameplay episodes. Signature is
    drop-in compatible with the smoke `evaluate_job(config, job)`; pass the optional
    `api` (EvaluatorApi) so the long K-run eval heartbeats the job lease between
    episodes (a gameplay eval takes ~2-20 min vs the smoke's seconds)."""
    # lazy import: keeps this module importable without the server-only evaluator
    from bonsai_lab_agent.evaluator import prepare_checkout, controller_command

    payload = job.get("payload") or {}
    submission_id = payload.get("submission_id")
    manifest = payload.get("controller_manifest") or {}
    horizon = int(payload.get("horizon_ticks") or DEFAULT_HORIZON)
    k = int(payload.get("k") or DEFAULT_K)

    cal = CALIBRATION.get(horizon)
    if not cal or cal.get("noop") is None or cal.get("ref") is None:
        return _uncalibrated(submission_id, horizon)

    repo = prepare_checkout(config, job)
    command = controller_command(repo, manifest)
    def controller_factory():
        return make_persistent_controller_fn(
            command, str(repo), round_timeout=config.controller_timeout_seconds)

    on_episode = None
    stop = threading.Event()
    hb_thread = None
    if api is not None:
        def on_episode(done: int, total: int) -> None:
            try:
                api.heartbeat(job, {"phase": "gameplay", "episode": done, "of": total,
                                    "horizon_ticks": horizon})
            except Exception:
                pass

        def _keepalive() -> None:
            # renew the lease every HEARTBEAT_INTERVAL s for the WHOLE eval — a single
            # episode can exceed lease_seconds (120), so per-episode heartbeats alone
            # would let the lease expire mid-episode.
            while not stop.wait(HEARTBEAT_INTERVAL):
                try:
                    api.heartbeat(job, {"phase": "gameplay", "keepalive": True})
                except Exception:
                    pass

        hb_thread = threading.Thread(target=_keepalive, daemon=True)
        hb_thread.start()

    try:
        result = game_scorer.score_submission(
            None, horizon_ticks=horizon, k=k, controller_factory=controller_factory,
            noop_composite=cal["noop"], ref_composite=cal["ref"], on_episode=on_episode)
    finally:
        stop.set()
        if hb_thread is not None:
            hb_thread.join(timeout=2)

    result["submission_id"] = submission_id
    result["regime_key"] = game_scorer.regime_key(
        scenario_id=payload.get("scenario_id", "bonsaifort2"),
        save_sha256=payload.get("save_sha256"),
        df_version=DF_VERSION, dfhack_version=DFHACK_VERSION,
        plugin_set_hash=payload.get("plugin_set_hash"),
        horizon_ticks=horizon, k=k)
    result["result_hash"] = hashlib.sha256(
        json.dumps(result["summary"], sort_keys=True, default=str).encode()).hexdigest()
    return result
