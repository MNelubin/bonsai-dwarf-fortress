"""Deterministic advancement commands probe for Dwarf Fortress.

This module queries the DF runtime for the status of the "advancement command" mechanic and returns a JSON‑serialisable dictionary with a single key "advancement_commands_enabled".  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_advancement_commands_snapshot() -> str:
    """Return whether the advancement command mechanic is enabled via Lua.

    The Lua code checks `global.settings_advancement_commands` which is set to true when the
    mechanic is active.  The result is printed as lower‑case JSON so the Python side can parse it
    safely.
    """
    return (
        """
        local json = require('json');
        local enabled = false;
        if df.global and df.global.settings_advancement_commands then
            enabled = df.global.settings_advancement_commands;
        end
        print(json.encode({advancement_commands_enabled = enabled}));
        """
    )


def probe_advancement_commands(timeout: int = 5) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for the current advancement command state.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        {'advancement_commands_enabled': <bool>} on success, or None if the probe cannot communicate
        with the DF runtime.
    """
    try:
        raw = _dfhack_run(_lua_advancement_commands_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
# end of module
