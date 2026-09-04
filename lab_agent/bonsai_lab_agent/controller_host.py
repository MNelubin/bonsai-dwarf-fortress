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
            if action is not None and not isinstance(action, dict):
                raise TypeError("controller must return an action object or null")
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
