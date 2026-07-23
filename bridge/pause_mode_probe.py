"""Deterministic pause mode probe for Dwarf Fortress.

This module queries the DF runtime to determine whether the game is currently paused
and returns a JSON‑serialisable dictionary with a single boolean key "paused".  The
implementation follows the same pattern as other probes in the repository and does
not affect any public interfaces.
"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_pause_snapshot() -> str:
    """Return pause status via Lua.

    The Lua expression checks ``df.global.pause`` which is true when the game is
    paused.  The result is printed as JSON so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        print(json.encode{{paused = df.global.pause}});
        """
    )


def probe_pause_mode(timeout: int = 20) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for pause mode status.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'paused': <bool>}`` on success, or ``None`` if the probe fails or the
        DF runtime is not available.
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
