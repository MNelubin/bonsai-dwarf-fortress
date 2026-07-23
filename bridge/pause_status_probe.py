"""Deterministic pause status probe for Dwarf Fortress.

This module queries the DF runtime for the current pause state and returns a JSON‑serialisable
dictionary with a single key "paused".  The implementation follows the pattern used by other
probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_pause_snapshot() -> str:
    """Return the pause state via Lua.

    This version uses a ternary expression for readability and ensures the JSON output uses lower‑case
    keys.
    """
    return (
        """
        local json = require('json');
        local paused = df.global and df.global.pause;
        print(json.encode({paused = paused}));
        """
    )


def probe_pause_status(timeout: int = 5) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for the current pause state.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        {'paused': <bool>} on success, or None if the probe cannot communicate with the DF
        runtime.
    """
    try:
        raw = _dfhack_run(_lua_pause_snapshot(), timeout=timeout)
    except Exception:
        return None
    # Accept raw JSON dict or stringified JSON that can be parsed by the internal helper
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
