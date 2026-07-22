"""Deterministic item value probe for Dwarf Fortress.

This module queries the DF runtime for the total monetary value of all items present,
and returns a JSON‑serialisable dictionary with a single key "total_value".  The
implementation follows the pattern used by other probes in the repository and does
not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_item_value_snapshot():
    """Return total item value via Lua.

    The Lua expression iterates ``df.global.world.items.all`` and sums the values
    returned by ``dfhack.items.getValue``.  The result is printed as JSON so the
    Python side can parse it safely.
    """
    return (
        "local json=require('json');" +
        "local total=0;" +
        "if df.global and df.global.world and df.global.world.items then" +
        "    for i,itm in ipairs(df.global.world.items.all) do" +
        "        local v=dfhack.items.getValue(itm) or 0;" +
        "        total=total+v;" +
        "    end" +
        "end" +
        "print(json.encode{{total_value=total}});"
    )


def probe_total_item_value(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the total monetary value of all items.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'total_value': <int>}`` on success, or ``None`` if the probe fails
        or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_item_value_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
