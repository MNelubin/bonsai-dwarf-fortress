"""Deterministic pause status probe for Dwarf Fortress.

This module queries the DF runtime for the current pause state and returns a JSON‑serialisable
dictionary with a single key "paused".  The implementation follows the pattern used by other
probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_pause_snapshot() -> str:
    """Return the pause state via Lua.

    The Lua expression evaluates ``df.global.pause`` (true when the game is paused) and prints a
    JSON object with the "paused" key.
    """
    return (
        """
        local json = require('json');
        local paused = false;
        if df.global and df.global.pause then
            paused = df.global.pause;
        end
        print(json.encode{{paused = paused}});
        """
    )


def probe_pause_status(timeout: int = 5) -> Optional[Dict[str, bool]]:
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
