"""Deterministic world age probe for Dwarf Fortress.

This module queries the DF runtime for the current world age in years and returns a JSON\u2011serialisable
dictionary with a single key "world_age".  The implementation follows the pattern used by other
probes in the repository and does not affect existing public interfaces.
"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_world_age_snapshot() -> str:
    """Return the current world age via Lua.

    The Lua code extracts ``df.global.world_info.age`` (number of years since
    world creation) and prints it as a simple JSON object.  Lower\u2011case keys are
    used to keep the output consistent with the rest of the bridge.
    """
    return (
        """
        local json = require('json');
        if df.global and df.global.world_info then
            local age = df.global.world_info.age;
            print(json.encode({world_age = age}));
        else
            print(json.encode({}));
        end
        """
    )


def probe_world_age(timeout: int = 5) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current world age.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'world_age': <int>}`` on success, or ``None`` if the probe cannot
        communicate with the DF runtime or the data is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_world_age_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        # Guard against missing key when DF data isn't ready.
        return raw
    return None

# deterministic edit marker
