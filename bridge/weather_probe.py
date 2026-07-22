"""Deterministic weather probe for Dwarf Fortress.

This module queries the DF runtime for the current weather state and
returns a JSON‑serialisable dictionary containing the basic weather
attributes.  The implementation follows the pattern used by other
probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_weather_snapshot():
    """Return current weather data via Lua.

    The Lua expression extracts ``df.global.weather`` fields that are
    known to be present ("isRainy", "isStormy", "isSnowy",
    "temperature", "humidity") and prints a JSON object with these
    values.  If the weather subsystem is not initialized the script
    returns an empty object.
    """
    return (
        "local json = require('json');"
        "local w = df.global.weather or {};"
        "local result = {};"
        "result.is_rainy   = w.isRainy or false;"
        "result.is_stormy  = w.isStormy or false;"
        "result.is_snowy   = w.isSnowy or false;"
        "result.temperature = tonumber(w.temperature) or nil;"
        "result.humidity    = tonumber(w.humidity) or nil;"
        "print(json.encode(result));"
    )


def probe_weather(timeout: int = 20) -> Optional[Dict[str, object]]:
    """Query the live DFHack process for the current weather.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary with keys ``is_rainy``, ``is_stormy``, ``is_snowy``,
        ``temperature`` and ``humidity`` on success, or ``None`` if the
        probe fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_weather_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
