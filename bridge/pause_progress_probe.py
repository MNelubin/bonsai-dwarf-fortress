"""Deterministic pause progress probe for Dwarf Fortress.

This module queries the DF runtime for the number of active pause jobs (jobs of type "df.job_type.Pause") and returns a JSON‑serialisable dictionary with a single key "pause_jobs".  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.
"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_pause_snapshot() -> str:
    """Return active pause job count via Lua.

    The Lua expression iterates ``df.global.world.jobs.list`` and counts jobs
    whose type is ``df.job_type.Pause``.  The result is printed as JSON so the
    Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                if job.job_type == df.job_type.Pause then
                    count = count + 1;
                end
            end
        end
        print(json.encode{{pause_jobs=count}});
        """
    )


def probe_pause_jobs(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of active pause jobs.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'pause_jobs': <int>}`` on success, or ``None`` if the probe fails
        or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_pause_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw or "pause_jobs" not in raw:
            return None
        return raw
    return None

# deterministic edit marker
