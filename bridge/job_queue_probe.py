"""Deterministic job queue probe for Dwarf Fortress.

This module queries the DF runtime for the total number of jobs in the queue
(df.global.world.jobs.list) and returns a JSON‑serialisable dictionary with a
single key "total_jobs".  The implementation follows the pattern used by other
probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_job_queue_snapshot() -> str:
    """Return total job count via Lua.

    The Lua expression counts every entry in ``df.global.world.jobs.list`` and
    prints the result as JSON ``{"total_jobs":<int>}``.
    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.jobs then
            for _, _ in ipairs(df.global.world.jobs.list) do
                count = count + 1;
            end
        end
        print(json.encode{{total_jobs=count}});
        """
    )


def probe_job_queue(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the total number of jobs in the queue.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'total_jobs': <int>}`` on success, or ``None`` if the probe fails
        or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_job_queue_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
