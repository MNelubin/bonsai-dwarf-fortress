import json
import os

_CONTRACTS_PATH = os.path.join(os.path.dirname(__file__), "contracts.json")

with open(_CONTRACTS_PATH) as _f:
    CONTRACT_SCHEMA = json.load(_f)

# Validation helpers


def validate_observe(obs):
    """Return True if obs conforms to the 'observe' contract shape.

    Checks required key presence, then validates field types against the
    schema definition for stricter conformance.
    """
    required = CONTRACT_SCHEMA["bridge_api"]["observe"]["output"]["required"]
    if not all(k in obs for k in required):
        return False
    props = CONTRACT_SCHEMA["bridge_api"]["observe"]["output"]["properties"]
    for key, spec in props.items():
        if key not in obs:
            continue
        val = obs[key]
        expected = spec.get("type")
        nullable = spec.get("nullable")
        if val is None and nullable:
            continue
        if val is None:
            return False
        if expected == "integer" and not isinstance(val, int):
            return False
        if expected == "string" and not isinstance(val, str):
            return False
        if expected == "boolean" and not isinstance(val, bool):
            return False
        if expected == "array" and not isinstance(val, list):
            return False
    return True


def validate_act_result(result):
    """Return True if result has the required (ok, message) fields."""
    return "ok" in result and "message" in result


def validate_episode_metrics(metrics):
    """Return True if episode output meets the contract schema."""
    fields = [
        "seed", "steps_taken", "final_tick", "survivors", "actions_used", "outcome"
    ]
    return all(f in metrics for f in fields)


def validate_episode_outcome(outcome):
    """Return True if outcome is one of the allowed contract values."""
    return outcome in {"success", "failure", "timeout"}


def validate_act_input(action):
    """Return True if action dict has a valid command field."""
    return isinstance(action, dict) and (
        "command" in action or "name" in action
    )
