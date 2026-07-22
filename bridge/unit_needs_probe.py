"""Deterministic unit needs probe for Dwarf Fortress.

Queries the DF runtime for the needs status (hunger, thirst, sleep, etc.) of each unit
and returns a JSON‑serialisable dictionary mapping unit IDs to a sub‑dictionary of
need counters. The implementation follows the pattern used by other probes in the
repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict, Any
from game_runner.episode import _dfhack_run


def _lua_unit_needs_snapshot() -> str:
    """Return per‑unit need counters via Lua.\n

The Lua expression iterates ``df.global.units.units`` and extracts the fields from
``unit.needs`` (hunger, thirst, sleep, exhaustion, etc.) as well as the second set
of counters ``unit.needs2``. Each need is printed as a JSON object mapping the
unit ID to its counters. This mirrors how other probes produce JSON output.
"""
    return ("""
    local json = require('json');
    local result = {};
    if df.global and df.global.units and df.global.units.units then
        for _,u in ipairs(df.global.units.units) do
            local needs = {};
            -- needs counters (needs)
            needs.hunger = u.needs and u.needs.hunger or 0;
            needs.thirst = u.needs and u.needs.thirst or 0;
            needs.sleep = u.needs and u.needs.sleep or 0;
            needs.exhaustion = u.needs and u.needs.exhaustion or 0;
            needs.mixed_debris = u.needs and u.needs.mixed_debris or 0;
            -- needs2 counters (needs2)
            needs.stomach_content = u.needs2 and u.needs2.stomach_content or 0;
            needs.stored_fat = u.needs2 and u.needs2.stored_fat or 0;
            needs.sickness = u.needs2 and u.needs2.sickness or 0;
            needs.hunger_threshold = u.needs2 and u.needs2.hunger_threshold or 0;
            result[u.id] = needs;
        end
    end
    print(json.encode(result));
    """)


def probe_unit_needs(timeout: int = 20) -> Optional[Dict[int, Dict[str, Any]]]:
    """Query the live DFHack process for current unit needs.\n

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary mapping unit IDs to a dictionary of need counters, or ``None``
        if the probe fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_unit_needs_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
