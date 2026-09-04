"""
Deterministic profession morale probe for Dwarf Fortress.

Queries the DF runtime for the current happiness rating of each profession and
returns a JSON‑serialisable mapping from profession identifier to a numeric
happiness score (0‑100). The implementation follows the pattern used by other
probes and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_profession_morale_snapshot():
    """Return profession happiness data via Lua.

    The Lua expression walks ``df.global.world.units.all`` and extracts each
    unit's profession happiness using ``unit.profession`` and the ``unit.counters2``
    fields that DFHack exposes. A JSON object mapping profession IDs to the
    average happiness (0‑100) is printed.
    """
    return (
        "local json = require('json');"
        "local result = {};"
        "if df.global and df.global.world and df.global.world.units then"
        "    for _,u in ipairs(df.global.world.units.all) do"
        "        local prof = u.profession or 0;"
        "        local hap = 0;"
        "        if u.counters2 and u.counters2.happiness then"
        "            hap = u.counters2.happiness;"
        "        end"
        "        result[prof] = (result[prof] or 0) + hap;"
        "    end"
        "    -- Compute average"
        "    local count = 0;"
        "    for p,_ in pairs(result) do"
        "        count = count + 1;"
        "        result[p] = result[p] / count;"
        "    end"
        "end"
        "print(json.encode(result));"
    )


def probe_profession_morale(timeout: int = 20) -> Optional[Dict[int, int]]:
    """Query the live DFHack process for the current profession morale.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary mapping profession IDs to an integer happiness value
        between 0 and 100, or ``None`` if the probe fails or the result cannot
        be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_profession_morale_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        # Ensure integer conversion.
        return {int(k): int(v) for k, v in raw.items()}
    return None
