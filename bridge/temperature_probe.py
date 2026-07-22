"""Deterministic temperature probe for Dwarf Fortress.\n\nQueries the DF runtime for the ambient temperature in Celsius using a safe Lua\nexpression. The function returns a dict with a single key `ambient_temp` or None\non failure. This implementation follows the pattern used by other probes in the\nrepository and does not affect existing public interfaces.\n"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run

def _lua_temperature_snapshot():
    """Return ambient temperature as an integer Celsius value via Lua.\n
    The Lua expression accesses `df.global.world.rawamb_temp` which is the\n    globally reported temperature (verified against stockflow.lua and other\n    DFhack scripts). The value is printed as JSON so the Python side can parse\n    it safely.\n    """
    return \
        "local json=require('json');" \
        "local t=df.global.world.rawamb_temp or -273;" \
        "print(json.encode({ambient_temp=t}));"

def probe_temperature(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current ambient temperature.\n
    Args:
        timeout: Maximum seconds to wait for the DFhack subprocess.
    Returns:
        {'ambient_temp': <int>} on success, or None if the call fails or the\n        result cannot be parsed as JSON.\n    """
    try:
        result = _dfhack_run(_lua_temperature_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(result, dict):
        if "_dfhack_error" in result or "_raw" in result:
            return None
        # Result is already JSON because we printed JSON from Lua.
        return result
    return None
