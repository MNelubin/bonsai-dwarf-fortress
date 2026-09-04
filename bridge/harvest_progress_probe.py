"""Deterministic harvest progress probe for Dwarf Fortress.

Queries the DF runtime for the number of active harvesting jobs (jobs of type
"df.job_type.HarvestFruits" and "df.job_type.HarvestDwarf"). Returns a JSON‑serialisable
dictionary with a single key "harvest_jobs". Follows existing probe patterns and does not
implicitly expose any private API.
"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_harvest_snapshot() -> str:
    """Return active harvesting job count via Lua.

    The Lua expression iterates ``df.global.world.jobs.list`` and counts jobs whose
    type is ``df.job_type.HarvestFruits`` or ``df.job_type.HarvestDwarf``.  The result
    is printed as JSON so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                if job.job_type == df.job_type.HarvestFruits or job.job_type == df.job_type.HarvestDwarf then
                    count = count + 1;
                end
            end
        end
        print(json.encode{{harvest_jobs=count}});
        """
    )


def probe_harvest_progress(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for current harvest job counts.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'harvest_jobs': <int>}`` on success, or ``None`` if the probe fails
        or the DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_harvest_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
