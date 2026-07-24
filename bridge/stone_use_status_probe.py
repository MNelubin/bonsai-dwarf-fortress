"""Deterministic stone use status probe for Dwarf Fortress.

This module queries the DF runtime for the current pause state of stone\ncrafting related jobs and returns a JSON‑serialisable dictionary with a\nsingle key "stone_jobs_paused".  The implementation follows the pattern\nused by other probes in the repository and does not affect existing public\ninterfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_stone_use_snapshot() -> str:
    """Return stone job pause status via Lua.

    The Lua expression iterates ``df.global.world.jobs.list`` and counts jobs\n    whose type is ``df.job_type.CutStone`` (representative stone use job) and\n    records whether the corresponding ``df.global.pause`` flag is set.\n    The result is printed as JSON so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local paused = df.global and df.global.pause;
        local count = 0;
        if df.global and df.global.world and df.global.world.jobs then
            for _, job in ipairs(df.global.world.jobs.list) do
                if job.job_type == df.job_type.CutStone then
                    count = count + 1;
                end
            end
        end
        print(json.encode{{stone_jobs_paused = paused, stone_jobs = count}});
        """
    )


def probe_stone_use_status(timeout: int = 5) -> Optional[Dict[str, bool]]:
    """Query the live DFHack process for stone job pause status.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'paused': <bool>}`` on success, or ``None`` if the probe fails or the
        DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_stone_use_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
# end of module
