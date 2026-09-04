"""Deterministic stockpile progress probe for Dwarf Fortress.

This module queries the DF runtime for the total number of stockpiles in the fort
and returns a JSON‑serialisable dictionary with a single key "stockpile_count".
The implementation follows the pattern used by other probes in the repository
and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_stockpile_snapshot() -> str:
    """Return the total number of stockpiles via Lua.

    The Lua expression counts the entries in ``df.global.world.stockpiles.all``
    and prints the result as JSON.
    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.stockpiles then
            for _ in ipairs(df.global.world.stockpiles.all) do
                count = count + 1;
            end
        end
        print(json.encode{{stockpile_count=count}});
        """
    )


def probe_stockpile_count(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of stockpiles.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'stockpile_count': <int>}`` on success, or ``None`` if the probe
        fails or the DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_stockpile_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
