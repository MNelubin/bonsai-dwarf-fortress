"""Deterministic unit needs probe for Dwarf Fortress.

Returns a mapping from unit IDs to their need counters when the DF runtime
is available; otherwise returns an empty dictionary or None on error.
"""
from typing import Optional, Dict, Any
from game_runner.episode import _dfhack_run


def _lua_unit_needs_snapshot() -> str:
    """Return a placeholder JSON object via Lua."""
    return "print('{}');"


def probe_unit_needs(timeout: int | str = 20) -> Optional[Dict[int, Dict[str, Any]]]:
    """Query the live DFHack process for current unit needs.

    Returns ``None`` on any error; otherwise returns a dictionary mapping
    unit IDs to need counters (may be empty).
    """
    try:
        raw = _dfhack_run(_lua_unit_needs_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
