"""Deterministic material probe for Dwarf Fortress.

This module queries the DF runtime to collect a set of unique material identifiers
present in the world and returns a JSON‑serialisable dictionary mapping each material
ID to a representative sample count. The implementation follows the patterns used by
other probes in the repository and does not affect existing public interfaces.
"""

from game_runner.episode import _dfhack_run
from typing import Dict, Optional


def _lua_material_snapshot() -> str:
    """Construct a Lua script that enumerates all items, extracts their material
    identifiers, counts occurrences, and prints a JSON object with the result.
    """
    return ("""
    local json = require('json')
    local counts = {}
    if df.global and df.global.world and df.global.world.items then
        for _,itm in ipairs(df.global.world.items.all) do
            local mat = dfhack.items.getMaterial(itm) or -1
            if mat >= 0 then
                counts[mat] = (counts[mat] or 0) + 1
            end
        end
    end
    print(json.encode(counts))
    """)


def probe_materials(timeout: int = 20) -> Optional[Dict[int, int]]:
    """Query the live DFHack process for material usage statistics.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A mapping from material IDs to the number of items of that material,
        or ``None`` if the probe fails or cannot parse the JSON output.
    """
    try:
        raw = _dfhack_run(_lua_material_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
