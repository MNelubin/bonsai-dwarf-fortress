"""Deterministic pause state probe for Dwarf Fortress.\n\nThis module queries the DF runtime for whether the game is currently paused\nand returns a JSON‑serialisable dictionary with a single key "paused" (bool).\nThe implementation follows the pattern used by other probes in the repository\nand does not affect existing public interfaces.\n"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_pause_state_snapshot() -> str:
    """Return the current pause state via Lua.\n\n    The Lua expression accesses ``df.global.pause`` (the internal pause flag)
    and prints a JSON map with the key ``paused`` set to the boolean value.
    """
    return ("""
    local json = require('json');
    local paused = df.global.pause;
    print(json.encode{{paused = paused}});
    """)


def probe_pause_state(timeout: int = 20) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for the current pause state.\n

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'paused': <bool>}`` on success, or ``None`` if the probe fails
        or the DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_pause_state_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
