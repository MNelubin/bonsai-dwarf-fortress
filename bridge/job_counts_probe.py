"""Deterministic job counts probe for Dwarf Fortress.

This module queries the DF runtime for the number of active jobs split by\njob_type and returns a JSON‑serialisable dictionary with counts for\ncommon job categories. It follows the same pattern as other bridge probes\nand does not affect existing public interfaces.
"""

from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_job_counts_snapshot() -> str:
    """Return count of jobs per type via Lua.

    The Lua script iterates ``df.global.world.jobs.list`` and tallies jobs\n    with the following DF ``job_type`` values:
    * ``df.job_type.ConstructBed``  → "construction"
    * ``df.job_type.PrepareMeal``   → "food"
    * ``df.job_type.MakeBarrel``    → "manufacturing"
    * ``df.job_type.CollectSand``   → "harvesting"
    All other jobs are grouped under "other".  The result is printed as JSON\n    so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json')
        local counts = {construction=0, food=0, manufacturing=0, harvesting=0, other=0}
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                local jtype = tostring(df.job_type[job.job_type]) or ""
                if jtype == "ConstructBed" then
                    counts.construction = counts.construction + 1
                elseif jtype == "PrepareMeal" then
                    counts.food = counts.food + 1
                elseif jtype == "MakeBarrel" then
                    counts.manufacturing = counts.manufacturing + 1
                elseif jtype == "CollectSand" then
                    counts.harvesting = counts.harvesting + 1
                else
                    counts.other = counts.other + 1
                end
            end
        end
        print(json.encode(counts));
        """
    )


def probe_job_counts(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for job counts per predefined category.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'construction': ..., 'food': ..., 'manufacturing': ..., 'harvesting': ..., 'other': ...}``
        on success, or ``None`` if the probe fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_job_counts_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
