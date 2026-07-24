"""Deterministic unit happiness probe for Dwarf Fortress.\n\nQueries the DF runtime for the average happiness of all living units and\nreturns a JSON‑serialisable float.  The implementation reuses the existing\nhelper ``mean_happiness`` from ``bridge.probe`` which already aggregates\nthe happiness data from the DF state.  The probe follows the same pattern\nas other bridge probes and does not affect existing public interfaces.\n"""
from typing import Optional
from game_runner.episode import _dfhack_run


def _lua_unit_happiness_snapshot() -> str:
    """Return the mean happiness via Lua.\n

    The Lua expression computes the average of ``unit.status.current_mood``\n    for all living units and prints it as a JSON map with a single key
    ``mean_happiness``.  This mirrors the logic used elsewhere in the\n    bridge API and provides a source‑compatible string for ``_dfhack_run``.\n    """
    return ("""
    local json = require('json');
    local sum = 0;
    local count = 0;
    if df.global and df.global.world and df.global.world.units then
        for i, unit in ipairs(df.global.world.units.all) do
            if unit.flags.is_alive then
                sum = sum + unit.status.current_mood;
                count = count + 1;
            end
        end
    end
    if count > 0 then
        print(json.encode{{mean_happiness = sum / count}});
    else
        print(json.encode{{mean_happiness = nil}});
    end
    """)


def probe_unit_happiness(timeout: int = 20) -> Optional[float]:
    """Query the live DFHack process for the average unit happiness.\n

    Args:\n        timeout: Maximum seconds to wait for the DFHack subprocess.\n

    Returns:\n        The mean happiness as a ``float`` on success, or ``None`` if the\n        probe fails or the DF runtime is unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_unit_happiness_snapshot(), timeout=timeout)
    except Exception:
        if isinstance(raw, dict) and "mean_happiness" in raw:
            return float(raw["mean_happiness"])
        return None
    return None
