"""Deterministic training progress probe for Dwarf Fortress.

This module queries the DF runtime for the number of active training jobs (jobs of type \"df.job_type.TrainItem\") and returns a JSON‑serialisable dictionary with a single key "training_jobs".  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.
"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run

def _lua_training_snapshot() -> str:
    """Return active training job count via Lua.

    The Lua expression iterates ``df.global.world.jobs.list`` and counts jobs whose
    type is ``df.job_type.TrainItem``.  The result is printed as JSON so the
    Python side can parse it safely.
    """
    return ("""
    local json = require('json');
    local count = 0;
    if df.global and df.global.world and df.global.world.jobs then
        for _, job in ipairs(df.global.world.jobs.list) do
            if job.job_type == df.job_type.TrainItem then
                count = count + 1;
            end
        end
    end
    print(json.encode{{training_jobs=count}});
    """)

def probe_training_jobs(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of active training jobs.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        {'training_jobs': <int>} on success, or None if the probe fails or the DF
        runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_training_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
# end of module
