"""Deterministic tile map probe for Dwarf Fortress.\n\nQueries the DF runtime for the dimensions of the map (width, height, depth) and returns a JSON‑serialisable dictionary with keys "width", "height" and "depth".  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.\n"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run

def _lua_tile_map_snapshot() -> str:
    """Return map dimensions via Lua.\n
    The Lua expression extracts ``df.global.world.map`` fields and prints a JSON object:\n    ``print(json.encode{{width=df.global.world.map.xsize+1,\n                     height=df.global.world.map.ysize+1,\n                     depth=df.global.world.map.zsize}})``\n    (The +1 matches the coordinate system used by other bridge code.)\n    """
    return (
        "local json = require('json');\n"
        "local map = df.global.world.map or {};\n"
        "local width  = (map.xsize  or 0) + 1;\n"
        "local height = (map.ysize  or 0) + 1;\n"
        "local depth  = (map.zsize  or 0);\n"
        "print(json.encode{{width=width, height=height, depth=depth}});"
    )


def probe_tile_map(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for map dimensions.\n
    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'width': <int>, 'height': <int>, 'depth': <int>}`` on success,
        or ``None`` if the probe fails or the result cannot be parsed as JSON.\n    """
    try:
        raw = _dfhack_run(_lua_tile_map_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
