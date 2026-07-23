"""Deterministic room temperature probe for Dwarf Fortress.\n\nReturns the current average room temperature in the fortress as a JSON‑serialisable\ndictionary with a single key "room_temperature" and an integer value (degrees in Kelvin).\nThe implementation follows the pattern used by other probes in the repository and does\nnot affect existing public interfaces.\n"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_room_temperature_snapshot() -> str:
    """Return the average room temperature via Lua.\n

    The Lua code accesses ``df.global.world.env.stats.global_stats`` and reads the\n    ``average_temperature`` field, printing it as a JSON map so the Python side can\n    parse it safely.\n    """
    return ("""
    local json = require('json');
    local temp = df.global.world.env.stats.global_stats.average_temperature;
    print(json.encode{{room_temperature=temp}});
    """)


def probe_room_temperature(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current average room temperature.\n

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.\n

    Returns:
        ``{'room_temperature': <int>}`` on success, or ``None`` if the probe fails
        or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_room_temperature_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
