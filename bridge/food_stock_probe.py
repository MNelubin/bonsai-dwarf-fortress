"""Deterministic food stock probe for Dwarf Fortress.\n\nQueries the DF runtime for the number of food items currently in the world and\nreturns a JSON‑serialisable dictionary with a single key "food_stock".  The\nimplementation follows the pattern used by other probes and does not affect\nexisting public interfaces.\n"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_food_stock_snapshot() -> str:
    """Return total number of food items via Lua.\n

The Lua expression iterates ``df.global.world.items.all`` and counts items whose\ntype is FOOD.  The result is printed as JSON so the Python side can parse it\nsafely.\n"""
    return ("""
    local json=require('json');\n    local count=0;\n    if df.global and df.global.world and df.global.world.items then\n        for _,itm in ipairs(df.global.world.items.all) do\n            if df.item_type[itm:getType()] == 'FOOD' then\n                count = count + 1;\n            end\n        end\n    end\n    print(json.encode{{food_stock=count}});\n    """
    )


def probe_food_stock(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current food stock count.\n

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.\n

    Returns:\n        {'food_stock': <int>} on success, or None if the probe fails or the\n        result cannot be parsed as JSON.\n    """
    try:
        raw = _dfhack_run(_lua_food_stock_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
