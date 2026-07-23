"""Deterministic dire‑needs probe for Dwarf Fortress.

Queries the DF runtime for units currently in a dire need (hunger, thirst,
 or sleepiness) and returns a JSON‑serialisable list of unit IDs. The
implementation follows the pattern used by other probes in the repository
and does not affect existing public interfaces.
"""
from typing import List, Optional
import json
from game_runner.episode import _dfhack_run


def _lua_dire_needs_snapshot() -> str:
    """Return dire‑needs data via Lua.

    The Lua expression iterates ``df.global.units.all`` and collects any unit
    where the combined severity of hunger, thirst, or sleepiness exceeds the
    dire thresholds. The result is printed as JSON so the Python side can
    parse it safely.
    """
    return ("""
    local json = require('json');
    local dire = {};
    if df.global and df.global.units then
        for _,u in ipairs(df.global.units.all) do
            if u.needs then
                local severe = 0;
                if (u.needs.hunger_timer or 0) >= (df.global.settings.get_bool('diren_hunger') and 24*60 or 48*60) then severe = severe + 1 end
                if (u.needs.thirst_timer or 0) >= (df.global.settings.get_bool('diren_thirst') and 24*60 or 48*60) then severe = severe + 1 end
                if (u.needs.sleepiness_timer or 0) >= (df.global.settings.get_bool('diren_sleep') and 12*60 or 24*60) then severe = severe + 1 end
                if severe >= 2 then
                    table.insert(dire, {unit_id = u.id});
                end
            end
        end
    end
    print(json.encode(dire));
    """)


def probe_dire_needs(timeout: int = 20) -> Optional[List[int]]:
    """Query the live DFHack process for units in dire need.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``[{unit_id: <int>}, ...]`` on success, or ``None`` if the probe fails
        or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_dire_needs_snapshot(), timeout=timeout)
    except Exception:
        return None
    # `_dfhack_run` may return a dict on error; treat any dict as failure.
    if isinstance(raw, dict):
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    ids = []
    for entry in payload:
        if isinstance(entry, dict) and isinstance(entry.get("unit_id"), int):
            ids.append(entry["unit_id"])
    if ids:
        return ids
    return None
