"""Controller invocation for the v4 gameplay scorer.

Bridges the trusted evaluator's existing controller protocol (jsonl-v1, see
evaluator.run_controller) to game_scorer's `controller_fn(obs) -> action intents`.
The untrusted agent's controller is invoked as a subprocess with the pinned T0
observation and returns action INTENTS, which game_scorer then sanitizes
(allow-list) and dispatches deterministically — the agent never touches DF state.

The controller may answer with a single `action` object OR a list of intents; both
are accepted so a setup-style fort policy can emit its whole T0 plan at once.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Callable


def make_controller_fn(command: list[str], repo: str, timeout: int = 60
                       ) -> Callable[[dict], list[dict]]:
    """Return a `controller_fn(obs) -> list[action-intent]` that invokes the agent's
    controller subprocess (jsonl-v1) with a single observation. Never raises into the
    scorer — a controller crash/timeout yields an empty action list (episode proceeds
    as a no-op, which the metric scores at baseline)."""

    def controller_fn(obs_dict: dict) -> list[dict]:
        request = json.dumps(
            {"type": "observation", "episode_id": "scored", "step": 0,
             "observation": obs_dict},
            separators=(",", ":"),
        )
        try:
            proc = subprocess.run(
                command, cwd=repo, input=request + "\n",
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if proc.returncode != 0:
            return []
        actions: list[dict] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(resp, dict) or resp.get("error"):
                continue
            a = resp.get("action")
            if isinstance(a, dict):
                actions.append(a)
            elif isinstance(a, list):
                actions.extend(x for x in a if isinstance(x, dict))
        return actions

    return controller_fn
