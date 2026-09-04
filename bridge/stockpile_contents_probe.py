"""Deterministic stockpile contents probe for Dwarf Fortress.

This module queries the DF runtime for each stockpile type and returns a JSON‑serialisable dictionary mapping stockpile IDs to a list of item type identifiers (e.g., "food", "metal", "stone"). The implementation follows the pattern used by other probes and does not affect existing public interfaces.
"""

from typing import Dict, List, Optional
from game_runner.episode import _dfhack_run


def _lua_stockpile_contents_snapshot() -> str:
    """Return stockpile contents mapping via Lua.

    The Lua expression iterates ``df.global.world.stockpiles.all`` and builds a map
    from stockpile ID to a list of item types.  The result is printed as JSON so the
    Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local result = {};
        if df.global and df.global.world and df.global.world.stockpiles then
            for _, sp in ipairs(df.global.world.stockpiles.all) do
                local types = {};
                for _, item in ipairs(sp.items) do
                    types[item.tile] = true;
                end
                local list = {};
                for typ,_ in pairs(types) do list[#list+1] = typ; end
                table.sort(list);
                result[sp.id] = list;
            end
        end
        print(json.encode(result));
        """
    )


def probe_stockpile_contents(timeout: int = 20) -> Optional[Dict[int, List[str]]]:
    """Query the live DFHack process for current stockpile item types.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{stockpile_id: [item_type, ...]}`` on success, or ``None`` if the probe
        fails or the DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_stockpile_contents_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
