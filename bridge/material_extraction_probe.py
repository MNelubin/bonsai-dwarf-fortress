"""Deterministic material extraction probe for Dwarf Fortress.\n\nQueries the DF runtime for the number of active material extraction jobs (jobs of type "df.job_type.Extract") and returns a JSON‑serialisable dictionary with a single key "extraction_jobs".  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.\n"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_extraction_snapshot() -> str:
    """Return active extraction job count via Lua.\n\n    The Lua expression iterates ``df.global.world.jobs.list`` and counts jobs
    whose type is ``df.job_type.Extract``.  The result is printed as JSON so the
    Python side can parse it safely.\n    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                if job.job_type == df.job_type.Extract then
                    count = count + 1;
                end
            end
        end
        print(json.encode{{extraction_jobs=count}});
        """
    )


def probe_material_extraction(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of active material extraction jobs.\n\n    Args:\n        timeout: Maximum seconds to wait for the DFHack subprocess.\n\n    Returns:\n        ``{'extraction_jobs': <int>}`` on success, or ``None`` if the probe
        fails or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_extraction_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
