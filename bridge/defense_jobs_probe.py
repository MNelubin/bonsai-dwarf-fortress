"""Deterministic defense jobs probe for Dwarf Fortress.\n\nQueries the DF runtime for the number of active defense jobs (jobs of type\n"df.job_type.Defend") and returns a JSON‑serialisable dictionary with a single\nkey "defense_jobs". The implementation follows the pattern used by other\nprobes in the repository and does not affect existing public interfaces.\n"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_defense_snapshot() -> str:
    """Return active defense job count via Lua.\n\n    The Lua expression iterates ``df.global.world.jobs.list`` and counts jobs\n    whose type is ``df.job_type.Defend``.  The result is printed as JSON so the\n    Python side can parse it safely.\n    """
    return ("""
    local json = require('json');
    local count = 0;
    if df.global and df.global.world and df.global.world.jobs then
        for _, job in ipairs(df.global.world.jobs.list) do
            if job.job_type == df.job_type.Defend then
                count = count + 1;
            end
        end
    end
    print(json.encode{{defense_jobs=count}});
    """)


def probe_defense_jobs(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of active defense jobs.\n

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.\n

    Returns:
        ``{'defense_jobs': <int>}`` on success, or ``None`` if the probe fails\n        or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_defense_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
