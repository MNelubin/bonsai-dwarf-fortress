"""Deterministic labour probe for Dwarf Fortress.

This module queries the DF runtime for the count of each labour that is currently assigned to any unit and returns a JSON‑serialisable dictionary mapping labour enum names to integer counts. The implementation follows the pattern used by other probes and does not affect existing public interfaces.
"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_labour_counts_snapshot() -> str:
    """Return labour assignment counts via Lua.

    The Lua expression iterates ``df.global.world.units.all`` and for each unit
    inspects ``unit.labors.active`` (a vector of ``df.unit_labor`` values). For each
    labour it increments a counter and finally prints a JSON object with the counts.
    """
    return (
        "local json = require('json');\n"
        "local counts = {};\n"
        "if df.global and df.global.world and df.global.world.units then\n"
        "    for i, u in ipairs(df.global.world.units.all) do\n"
        "        if u.labors and u.labors.active then\n"
        "            for _, l in ipairs(u.labors.active) do\n"
        "                local name = tostring(df.unit_labor[l]) or 'unknown';\n"
        "                counts[name] = (counts[name] or 0) + 1;\n"
        "            end\n"
        "        end\n"
        "    end\n"
        "end\n"
        "print(json.encode(counts));\n"
    )


def probe_labour_counts(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for current labour assignment counts.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'<labour>': <int>}`` on success, or ``None`` if the probe fails or the
        result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_labour_counts_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
