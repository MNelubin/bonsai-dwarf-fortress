"""Deterministic building construction progress probe for Dwarf Fortress.

This module queries the DF runtime for the number of active construction jobs
(jobs of type "df.job_type.ConstructBed") and returns a JSON‑serialisable
dictionary with a single key "construction_jobs".  The implementation follows
the pattern used by other probes in the repository and does not affect existing
public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_construction_snapshot() -> str:
    """Return active construction job count via Lua.

    The Lua expression iterates ``df.global.world.jobs.list`` and counts jobs
    whose type is ``df.job_type.ConstructBed``.  The result is printed as JSON
    so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                if job.job_type == df.job_type.ConstructBed then
                    count = count + 1;
                end
            end
        end
        print(json.encode{{construction_jobs=count}});
        """
    )


def probe_construction_jobs(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of active construction jobs.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'construction_jobs': <int>}`` on success, or ``None`` if the probe
        fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_construction_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
