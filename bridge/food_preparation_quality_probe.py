"""Deterministic food preparation quality probe for Dwarf Fortress.\n\nQueries the DF runtime for the quality level of all active cooking jobs (jobs of type "df.job_type.CookFood") and returns a JSON‑serialisable dictionary mapping job IDs to their quality enum value.  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.\n"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_food_quality_snapshot() -> str:
    """Return active cooking job quality data via Lua.\n\n    The Lua expression iterates ``df.global.world.jobs.list`` and builds a
    map from job ID to the integer value of ``job.flags.quality``
    (0 = raw, 1 = basic, 2 = refined, 3 = advanced).  The result is printed as
    JSON so the Python side can parse it safely.\n    """
    return (
        """
        local json = require('json');
        local result = {};
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                if job.job_type == df.job_type.CookFood then
                    local q = job.flags and job.flags.quality or 0;
                    result[job.id] = {quality = q};
                end
            end
        end
        print(json.encode(result));
        """
    )


def probe_food_preparation_quality(timeout: int = 20) -> Optional[Dict[int, Dict[str, int]]]:
    """Query the live DFHack process for current food preparation job qualities.\n\n    Args:\n        timeout: Maximum seconds to wait for the DFHack subprocess.\n\n    Returns:\n        ``{job_id: {'quality': <int>}}`` on success, or ``None`` if the probe
        fails or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_food_quality_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
