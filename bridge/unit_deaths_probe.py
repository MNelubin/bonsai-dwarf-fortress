"""Deterministic unit deaths probe for Dwarf Fortress.

This module queries the DF runtime for the number of dead dwarf/elf/gnome
units in the current fort and returns a JSON‑serialisable dictionary with a
single key "unit_deaths".  The implementation follows the pattern used by
other probes and only accesses publicly available DF globals.
"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_unit_deaths_snapshot() -> str:
    """Return count of dead units via Lua.

    The Lua expression iterates ``df.global.world.units.all`` and counts unit
    records whose ``unit_type`` is not ``ANIMAL`` and whose ``status.is_alive``
    flag is false (dead).  The result is printed as JSON so the Python side
    can parse it safely.
    """
    return ("""
    local json = require('json');
    local count = 0;
    if df.global and df.global.world and df.global.world.units then
        for _, unit in ipairs(df.global.world.units.all) do
            if unit.unit_type ~= df.unit_type.ANIMAL and not unit.status.is_alive then
                count = count + 1;
            end
        end
    end
    print(json.encode{{unit_deaths=count}});
    """
    )


def probe_unit_deaths(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for current dead unit count.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'unit_deaths': <int>}`` on success, or ``None`` if the probe fails
        or cannot communicate with the DF runtime.
    """
    try:
        raw = _dfhack_run(_lua_unit_deaths_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
