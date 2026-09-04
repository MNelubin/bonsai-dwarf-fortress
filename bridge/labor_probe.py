"""Deterministic labor probe for Dwarf Fortress.

Queries the DF runtime for the list of active unit labors and returns a JSON-serialisable
mapping from unit ID to a set of labor names. The implementation follows the pattern used
by other probes in the repository and does not affect existing public interfaces.
"""
from typing import Set, Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_labor_snapshot():
    """Return unit id -> list of labor names via Lua.

    The Lua expression extracts ``unit.flags.labors`` for each unit that exists in the
    DF world and prints a JSON object with the collected data. This mirrors the approach
    taken in existing probe implementations.
    """
    return (
        "local json = require('json');"
        "local result = {};"
        "if df.global and df.global.units then"
        "    for _,u in ipairs(df.global.units_units) do"
        "        local labors = {};"
        "        if u.flags and u.flags.labors then"
        "            for _,l in ipairs(u.flags.labors) do"
        "                table.insert(labors, tostring(l));"
        "            end"
        "        end"
        "        result[u.id] = labors;"
        "    end"
        "end"
        "print(json.encode(result));"
    )


def probe_labor(timeout: int = 25) -> Optional[Dict[int, Set[str]]]:
    """Query the live DFHack process for the current labor state of all units.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary mapping unit IDs to a set of labor names, or ``None`` if the
        call fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_labor_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        # Convert Lua list strings to Python set.
        return {int(k): set(v) for k, v in raw.items()}
    return None
