"""Deterministic faction morale probe for Dwarf Fortress.

This module queries the DF runtime for the morale status of each faction and
returns a JSON‑serialisable mapping from faction identifier to a numeric morale
value. The implementation follows the pattern used by other probes in the
repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_faction_morale_snapshot():
    """Return faction morale data via Lua.

    The Lua expression walks ``df.global.world.factions.all`` and builds a JSON
    object mapping ``faction.id`` to the integer ``faction.morale`` (where
    ``0`` means neutral, positive values good morale, negative poor morale).
    """
    return (
        "local json = require('json');"
        "local result = {};"
        "if df.global and df.global.world and df.global.world.factions then"
        "    for _,f in ipairs(df.global.world.factions.all) do"
        "        result[f.id] = f.morale or 0;"
        "    end"
        "end"
        "print(json.encode(result));"
    )


def probe_faction_morale(timeout: int = 20) -> Optional[Dict[int, int]]:
    """Query the live DFHack process for current faction morale.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary mapping faction IDs to their integer morale values, or
        ``None`` if the probe fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_faction_morale_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
