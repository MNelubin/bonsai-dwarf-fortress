"""Deterministic tile material probe for Dwarf Fortress.

This module queries the DF runtime for the material of a tile at a given
coordinates using a safe Lua expression. It follows the pattern of other
probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Tuple, Dict
from game_runner.episode import _dfhack_run

def _lua_tile_material_snapshot(pos: Tuple[int, int, int]) -> str:
    """Compose a Lua snippet that returns the material index (or -1) of the tile.

    Arguments:
        pos: (x, y, z) coordinates.

    Returns:
        JSON string with the material index.
    """
    x, y, z = pos
    return (
        "local json=require('json');\n" +
        f"local x={x}; local y={y}; local z={z};\n" +
        "local mat = -1;\n" +
        "if df.global.world then\n" +
        "    local pos = df.global.world.map.tiles[x + y*df.global.world.map.x_count + z*df.global.world.map.x_count*df.global.world.map.y_count];\n" +
        "    if pos and pos.material then\n" +
        "        mat = pos.material.id or -1;\n" +
        "    end\n" +
        "end\n" +
        "print(json.encode{{material=mat}});"
    )


def probe_tile_material(pos: Tuple[int, int, int], timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the material of a tile.

    Args:
        pos: Coordinates (x, y, z) of the tile to probe.
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'material': <int>}`` on success, or ``None`` if the probe fails
        or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_tile_material_snapshot(pos), timeout=timeout)
    except Exception:
        return None
    # Return None if the runner reports an error (including timeout errors)
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw or "error" in raw:
            return None
        return raw
    return None
