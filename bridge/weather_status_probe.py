"""Deterministic weather status probe for Dwarf Fortress.\n\nQueries the DF runtime for the current weather condition and returns a JSON‑serialisable\ndictionary with a single key "weather" mapping to a string description (e.g., "clear", "rain",\n"snow", "storm"). The implementation follows the pattern used by other probes in the repository\nand does not affect existing public interfaces.\n"""

from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_weather_snapshot() -> str:
    """Return current weather description via Lua.\n\n    The Lua expression checks ``df.global.world.weather.cur_state`` and prints a JSON object\n    with the "weather" key. It safely handles missing globals.
    """
    return (
        """
        local json = require('json');
        local weather_desc = "unknown";
        if df.global and df.global.world and df.global.world.weather then
            local state = df.global.world.weather.cur_state;
            if state == df.weather_state.Foggy then
                weather_desc = "foggy";
            elseif state == df.weather_state.Raining then
                weather_desc = "rain";
            elseif state == df.weather_state.Snowing then
                weather_desc = "snow";
            elseif state == df.weather_state.Storm then
                weather_desc = "storm";
            else
                weather_desc = "clear";
            end
        end
        print(json.encode{{weather = weather_desc}});
        """
    )


def probe_weather_status(timeout: int = 5) -> Optional[Dict[str, str]]:
    """Query the live DFHack process for the current weather state.\n\n    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.\n\n    Returns:\n        {"weather": <str>} on success, or ``None`` if the probe fails or the DF runtime is\n        unavailable.\n    """
    try:
        raw = _dfhack_run(_lua_weather_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
