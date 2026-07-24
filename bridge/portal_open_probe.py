"""Deterministic portal open probe for Dwarf Fortress.\n\nThis module queries the DF runtime for whether any portal in the fort is currently\nopen and returns a JSON‑serialisable dictionary with a single key "portal_opened"\n(bool). The implementation follows the pattern used by other probes and does not\naffect existing public interfaces.\n"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_portal_snapshot() -> str:
    """Return portal open state via Lua.\n    The Lua expression iterates ``df.global.world.raws.templates.creature`` to find any\n    portal objects and prints a JSON map with the key ``portal_opened`` set to the boolean\n    value indicating if at least one portal is open.\n    """
    return ("""
    local json = require('json');
    local portal_opened = false;
    if df.global and df.global.world then
        for _, obj in ipairs(df.global.world.raws.templates.creature) do
            if obj.id == "portal" and obj.flags[0] == 1 then
                portal_opened = true;
                break;
            end
        end
    end
    print(json.encode{{portal_opened = portal_opened}});
    """)


def probe_portal_open(timeout: int = 20) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for the portal open state.\n

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'portal_opened': <bool>}`` on success, or ``None`` if the probe fails
        or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_portal_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
