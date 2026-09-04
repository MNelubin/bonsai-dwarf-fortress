"""Deterministic animal care probe for Dwarf Fortress.\n\nQueries the DF runtime for the current health status of all animal units in the fort and returns a JSON‑serialisable dictionary mapping unit IDs to a string health level ("healthy", "injured", "ill", "dead").  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.\n"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_animal_care_snapshot() -> str:
    """Return animal health data via Lua.\n\n    The Lua expression iterates ``df.global.world.units.all`` and builds a
    map from unit ID to the current health condition.  The result is printed as
    JSON so the Python side can parse it safely.\n    """
    return (
        """
        local json = require('json');
        local result = {};
        if df.global and df.global.world and df.global.world.units then
            for _, unit in ipairs(df.global.world.units.all) do
                if unit.unit_type == df.unit_type.ANIMAL then
                    local health_str;
                    if unit.health.hps == unit.health.max_hps then
                        health_str = "healthy";
                    elseif unit.health.hps < unit.health.max_hps and unit.health.hps > 0 then
                        health_str = "injured";
                    elseif unit.status.in_mortuary then
                        health_str = "dead";
                    else
                        health_str = "ill";
                    end
                    result[unit.id] = {health = health_str};
                end
            end
        end
        print(json.encode(result));
        """
    )


def probe_animal_care(timeout: int = 20) -> Optional[Dict[int, Dict[str, str]]]:
    """Query the live DFHack process for current animal health statuses.\n\n    Args:\n        timeout: Maximum seconds to wait for the DFHack subprocess.\n\n    Returns:\n        ``{unit_id: {'health': <str>}}`` on success, or ``None`` if the probe
        fails or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_animal_care_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
