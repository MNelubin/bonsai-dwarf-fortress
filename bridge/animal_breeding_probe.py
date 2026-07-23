"""
Deterministic animal breeding probe for Dwarf Fortress.

This probe returns the count of animal breeding pairs currently active in the
fort's animal economy.  It provides a single‑key JSON‑serialisable result and
conforms to the repository's probe conventions.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run

# Updated docstring to clarify purpose.


def _lua_animal_breeding_snapshot() -> str:
    """Generate a Lua script that counts animal breeding pairs.

    The script walks through ``df.global.world.animalec.animal_stocks.all``
    and increments a counter for each stock containing at least one adult
    male and one adult female.
    """
    return ("""
    local json = require('json');
    local breed_count = 0;
    if df.global and df.global.world and df.global.world.animalec then
        for _, stock in ipairs(df.global.world.animalec.animal_stocks.all) do
            local male_cnt = 0;
            local female_cnt = 0;
            for _, animal in ipairs(stock.animals) do
                if animal.age then
                    if animal.sex == 0 then
                        male_cnt = male_cnt + 1;
                    elseif animal.sex == 1 then
                        female_cnt = female_cnt + 1;
                    end
                end
            end
            if male_cnt > 0 and female_cnt > 0 then
                breed_count = breed_count + 1;
            end
        end
    end
    print(json.encode{{breeding_pairs=breed_count}});
    """
    )


def probe_breeding_pairs(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Return the number of active animal breeding pairs.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'breeding_pairs': <int>}`` on success, or ``None`` if the probe fails.
    """
    try:
        raw = _dfhack_run(_lua_animal_breeding_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict) and "_dfhack_error" not in raw and "_raw" not in raw:
        return raw
    return None
