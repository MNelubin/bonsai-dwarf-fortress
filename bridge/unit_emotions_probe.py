"""Deterministic unit emotions probe for Dwarf Fortress.

Queries the DF runtime for each unit's primary emotion strength and
returns a JSON‑serialisable dictionary mapping unit IDs to a nested
dictionary containing the emotion's type and strength. The implementation
mirrors the pattern used by other probes and respects the coding‑graph
contract.
"""
from typing import Dict, Optional, Any
from game_runner.episode import _dfhack_run


def _lua_unit_emotions_snapshot() -> str:
    """Return unit emotions data via Lua.

The Lua snippet walks ``df.global.units.all`` and for each unit builds a
mapping:
    unit_id -> { emotion_type = <string>, strength = <int> }
using ``unit:getEmotions().emotions`` where the first (index 0) emotion is
the primary one. The result is printed as JSON so the Python side can parse
it safely.
"""
    return (
        """
        local json = require('json');
        local result = {};
        if df.global and df.global.units and df.global.units.all then
            for _, u in ipairs(df.global.units.all) do
                local emotions = {};
                if u.emotions then
                    for _, e in ipairs(u.emotions.emotions) do
                        emotions.emotion = tostring(e.type) or "unknown";
                        emotions.strength = e.strength or 0;
                        break; -- primary emotion only
                    end
                end
                result[u.id] = emotions;
            end
        end
        print(json.encode(result));
        """
    )


def probe_unit_emotions(timeout: int | str = 20) -> Optional[Dict[int, Dict[str, Any]]]:
    """Query the live DFHack process for the primary emotion of each unit.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.
    Returns:
        A dictionary ``{unit_id: {emotion: str, strength: int}}`` on success,
        or ``None`` if the probe fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_unit_emotions_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None


# The public test for this probe has been moved to the dedicated test suite under the
# ``tests`` directory to satisfy the coding‑graph contract.
