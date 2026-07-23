"""Deterministic pause/advancement status probe for Dwarf Fortress.

Queries the DF runtime for the current pause state and whether units are allowed to advance, and returns a JSON‑serialisable dictionary with keys "paused" (bool) and "advancement_allowed" (bool). This implementation is currently a placeholder and returns a synthetic advancement_allowed value based on terrain; replace with real logic when DF data is available. It follows the pattern used by other probes in the repository and does not affect existing public interfaces.
"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_pause_advancement_snapshot() -> str:
    """Return the DF pause and advancement state via Lua.

    The Lua code checks ``df.global.world pauses`` and the advancement mode.  It prints a JSON object
    ``{'paused': <bool>, 'advancement_allowed': <bool>}`` which the Python side can parse safely.
    """
    return (
        """
    local json = require('json');
    local paused = not df.global.pause_state or df.global.pause_state == df.pause_state.UNPAUSED;
    -- In DF 0.47+, the game is paused when pause_state == df.pause_state.PAUSED
    if(df.global.pause_state and df.global.pause_state == df.pause_state.PAUSED) then
        paused = true;
    end
    local advancement_allowed = df.global.map.sq[0].tile_type == df.tile_type.WATER; -- placeholder boolean
    print(json.encode{{paused=paused, advancement_allowed=advancement_allowed}});
    """
    )


def probe_pause_advancement_state(timeout: int = 20) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for current pause and advancement state.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.
    Returns:
        ``{'paused': <bool>, 'advancement_allowed': <bool>}`` on success,
        or ``None`` if the probe fails or the DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_pause_advancement_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if '_dfhack_error' in raw or '_raw' in raw:
            return None
        return raw
    return None

# deterministic edit marker
