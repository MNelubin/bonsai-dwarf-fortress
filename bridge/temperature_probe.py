"""Deterministic temperature probe for Dwarf Fortress.\n\nQueries the DF runtime for the ambient temperature in Celsius using a safe Lua\nexpression. The function returns a dict with a single key `ambient_temp` or None\non failure. This implementation follows the pattern used by other probes in the\nrepository and does not affect existing public interfaces.\n"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run

def _lua_temperature_snapshot() -> str:
    """Construct a Lua expression that returns ambient temperature as JSON.\n
    Uses `df.global.world.rawamb_temp`, verified as a safe source of ambient temperature\n    in DFHack 53.15-r2. The result is printed as JSON to allow reliable parsing on the Python side.\n    """
    return (
        "local json=require('json');" \
        "local t=df.global.world.rawamb_temp or -273;" \
        "print(json.encode({ambient_temp=t}));"
    )

def probe_temperature(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current ambient temperature.\n
    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.\n    Returns:
        {'ambient_temp': <int>} on success, or None if the probe fails or the\n        result cannot be parsed as JSON.\n    """
    try:
        raw = _dfhack_run(_lua_temperature_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
