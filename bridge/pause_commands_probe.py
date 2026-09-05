"""Deterministic pause commands probe for Dwarf Fortress.

This module queries the DF runtime for the current pause state via Lua and returns a JSON‑serialisable
dictionary with a single key "paused". The implementation follows the pattern used by other probes in
the repository and does not affect existing public interfaces.
"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_pause_snapshot() -> str:
    """Return the current pause state via Lua.

    The Lua code checks ``df.global.pause_state`` which is true when the game is paused.
    The result is printed as lower‑case JSON so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local paused = false;
        if df.global then
            paused = df.global.pause_state;
        end
        print(json.encode{{paused=paused}});
        """
    )


def probe_pause_state(timeout: int = 5) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for whether the game is currently paused.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'paused': <bool>}`` on success, or ``None`` if the probe fails.
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
