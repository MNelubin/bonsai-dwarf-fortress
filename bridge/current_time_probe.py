"""Deterministic current time probe for Dwarf Fortress.

This module queries the DF runtime for the in‑game timestamp and returns a JSON‑serialisable
dictionary with a single key "time" containing the system time value. The implementation follows
the pattern used by other probes in the repository and does not affect existing public interfaces.
"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_current_time_snapshot() -> str:
    """Return the current DF time via Lua.

    The Lua expression uses ``df.global.time.to_system_time()`` which yields the raw time
    number as a 64‑bit integer. The result is printed as JSON so the Python side can parse it
    safely.
    """
    return (
        """
        local json = require('json');
        print(json.encode({time = df.global.time.to_system_time()}));
        """
    )


def probe_current_time(timeout: int = 5) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current in‑game time.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'time': <int>}`` on success, or ``None`` if the probe cannot communicate with the DF
        runtime.
    """
    try:
        raw = _dfhack_run(_lua_current_time_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
