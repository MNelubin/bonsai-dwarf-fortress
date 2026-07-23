"""Deterministic pause state probe for Dwarf Fortress.

This module queries the DF runtime for whether the game is currently paused and returns a JSON‑serialisable dictionary with a single key "paused" and a boolean value.  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.
"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_pause_snapshot() -> str:
    """Return current pause state via Lua.

    The Lua expression checks the global ``df.global.instant_mode`` flag, which is true when the game
    is paused, and prints a JSON object ``{"paused": <bool>}``.  The result can be parsed safely by the
    Python side.
    """
    return (
        """
        local json = require('json');
        local paused = (df.global and df.global.instant_mode ~= 0);
        print(json.encode{{paused=paused}});
        """
    )


def probe_pause_state(timeout: int = 20) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for the current pause state.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'paused': <bool>}`` on success, or ``None`` if the probe fails or the DF runtime is
        unavailable.
    """
    try:
        raw = _dfhack_run(_lua_pause_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
