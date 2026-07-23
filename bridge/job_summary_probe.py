"""Deterministic job summary probe for Dwarf Fortress.\n\nQueries the DF runtime for all active job entries and returns a JSON‑serialisable\ndictionary with counts of jobs per state (queued, active, suspended, cancelled)\nand per broad category (construction, food, manufacturing, harvesting, other).\nThe implementation follows the pattern used by other probes in the repository\nand does not affect existing public interfaces.\n"""

from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_job_summary_snapshot() -> str:
    """Return job counts via Lua.\n

    Lua iterates ``df.global.world.jobs.list`` and builds two tables:
    * ``state_counts`` – keys queued, active, suspended, cancelled with integer values.
    * ``category_counts`` – keys construction, food, manufacturing, harvesting, other.
    The combined result is printed as JSON so the Python side can parse it safely.\n    """
    return ("""
    local json = require('json')
    local state_counts = {queued=0, active=0, suspended=0, cancelled=0}
    local category_counts = {construction=0, food=0, manufacturing=0, harvesting=0, other=0}
    local cat_map = {
        [df.job_type.ConstructBed] = "construction",
        [df.job_type.ConstructChest] = "construction",
        [df.job_type.PrepareMeal] = "food",
        [df.job_type.ButcherAnimal] = "food",
        [df.job_type.MakeBarrel] = "manufacturing",
        [df.job_type.SmeltOre] = "manufacturing",
        [df.job_type.CutGems] = "manufacturing",
        [df.job_type.CollectSand] = "harvesting",
        [df.job_type.HarvestFruits] = "harvesting",
    }
    if df.global and df.global.world and df.global.world.jobs then
        for _, job in ipairs(df.global.world.jobs.list) do
            -- state
            if job.cancelled then
                state_counts.cancelled = state_counts.cancelled + 1
            elseif job.suspended then
                state_counts.suspended = state_counts.suspended + 1
            elseif job.next_job_idx == nil and job.active_job_idx == nil and not job.cancelled then
                state_counts.queued = state_counts.queued + 1
            else
                state_counts.active = state_counts.active + 1
            end
            -- category fallback to "other"
            local cat = cat_map[job.job_type] or "other"
            category_counts[cat] = category_counts[cat] + 1
        end
    end
    local result = {state_counts=state_counts, category_counts=category_counts}
    print(json.encode(result));
    """)


def probe_job_summary(timeout: int = 20) -> Optional[Dict[str, Dict[str, int]]]:
    """Query the live DFHack process for a summary of jobs.\n

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'state_counts': {...}, 'category_counts': {...}}`` on success, or ``None``
        if the probe fails or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_job_summary_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
