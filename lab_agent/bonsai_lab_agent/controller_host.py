from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable


def load_callable(repo: Path, entrypoint: str) -> Callable[[dict[str, Any]], Any]:
    module_name, separator, attribute = entrypoint.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("entrypoint must be module.path:callable")
    sys.path.insert(0, str(repo.resolve()))
    target: Any = importlib.import_module(module_name)
    for part in attribute.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise TypeError(f"{entrypoint} is not callable")
    return target


def serve(policy: Callable[[dict[str, Any]], Any]) -> int:
    for raw_line in sys.stdin:
        response: dict[str, Any]
        try:
            request = json.loads(raw_line)
            if request.get("type") != "observation" or not isinstance(
                request.get("observation"), dict
            ):
                raise ValueError("expected an observation request")
            action = policy(request["observation"])
            # A round may carry SEVERAL intents. The host only ever accepted one dict or
            # null - the one-shot contract from the contract-smoke era - while every
            # stepped policy, including all four reference tiers, returns a list. So the
            # host answered {"error": "TypeError: controller must return an action object
            # or null"} on every single round, the fort was never told to do anything,
            # and the episode scored the no-op floor with no failure anywhere to see it.
            # Measured live: v3_survival scored exactly 1.0 called in-process by the
            # calibration driver and 0.0 through this host on the same save.
            # persistent_controller._extract_actions has always accepted
            # {"action": [...]}; only this end refused to send it.
            if action is not None and not isinstance(action, (dict, list)):
                raise TypeError("controller must return an action, a list of actions, or null")
            if isinstance(action, list) and any(not isinstance(item, dict) for item in action):
                raise TypeError("every action in the list must be an object")
            response = {"action": action}
        except Exception as exc:
            response = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, separators=(",", ":"), default=str), flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--entrypoint", required=True)
    args = parser.parse_args()
    raise SystemExit(serve(load_callable(args.repo, args.entrypoint)))


if __name__ == "__main__":
    main()
