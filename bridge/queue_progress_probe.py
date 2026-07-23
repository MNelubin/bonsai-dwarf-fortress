"""Deterministic probe for the total number of active jobs awaiting processing.

This module queries the DF runtime for the job queue length and returns a JSON‑serialisable
dictionary with a single key "queue_length".  The implementation follows the pattern used by
other probes in the repository and does not affect existing public interfaces.
"""


from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_queue_snapshot() -> str:
    """Return job queue length via Lua.

    The Lua expression accesses ``df.global.world.jobs.list`` and counts job objects that
    are currently in the queue.  The result is printed as JSON so the Python side can parse
    it safely.
    """
    return (
        """
        local json = require('json');
        local queue = 0;
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                if job.state == df.job_state.QUEUED then
                    queue = queue + 1;
                end
            end
        end
        print(json.encode{{queue_length=queue}});
        """
    )


def probe_queue_length(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current job queue length.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'queue_length': <int>}`` on success, or ``None`` if the probe fails or the
        DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_queue_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
