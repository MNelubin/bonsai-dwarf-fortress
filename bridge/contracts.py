import json
import os

_CONTRACTS_PATH = os.path.join(os.path.dirname(__file__), "contracts.json")

with open(_CONTRACTS_PATH) as _f:
    CONTRACT_SCHEMA = json.load(_f)

# Validation helpers
def validate_observe(obs):
    """Return True if obs conforms to the 'observe' contract shape."""
    required = CONTRACT_SCHEMA["bridge_api"]["observe"]["output"]["required"]
    return all(k in obs for k in required)


def validate_act_result(result):
    """Return True if result has the required (ok, message) fields."""
    return "ok" in result and "message" in result


def validate_episode_metrics(metrics):
    """Return True if episode output meets the contract schema."""
    fields = [
        "seed", "steps_taken", "final_tick", "survivors", "actions_used", "outcome"
    ]
    return all(f in metrics for f in fields)
