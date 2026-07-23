"""
Deterministic animal breeding probe for Dwarf Fortress.

Queries the DF runtime for information about animal breeding pairs and
returns a JSON‑serialisable dictionary with a single key "breeding_pairs".
The implementation follows the pattern used by other probes in the repository
and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_animal_breeding_snapshot() -> str:
    """Return animal breeding data via Lua.

The Lua expression iterates ``df.global.world.animalec.animal_stocks.all`` and
counts each breeding pair (two adult animals of opposite sex sharing the same
stock ID).  The result is printed as JSON so the Python side can parse it safely.
"""
    return ("""
    local json = require('json');
    local breed_count = 0;
    if df.global and df.global.world and df.global.world.animalec then
        for _, stock in ipairs(df.global.world.animalec.animal_stocks.all) do
            local adults = {};
            for _, animal in ipairs(stock.animals) do
                if animal.age then
                    adults[animal.sex] = adults[animal.sex] or 0;
                    adults[animal.sex] = adults[animal.sex] + 1;
                end
            end
            -- A breeding pair requires at least one male and one female adult.
            if adults[0] and adults[1] and adults[0] > 0 and adults[1] > 0 then
                breed_count = breed_count + 1;
            end
        end
    end
    print(json.encode{{breeding_pairs=breed_count}});
    """
    )


def probe_breeding_pairs(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of active breeding pairs.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'breeding_pairs': <int>}`` on success, or ``None`` if the probe fails
        or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_animal_breeding_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
