"""
Skill probe for Dwarf Fortress.

Queries the DF runtime for the skills of each unit and returns a mapping from
unit IDs (int) to a list of skill dictionaries. Each skill dictionary contains
the string ``skill`` and an integer ``level``.

The probe safely returns ``None`` when the DFHack subprocess cannot be reached,
making it deterministic for the coding‑graph environment.
"""

from typing import List, Dict, Optional

from game_runner.episode import _dfhack_run


def _lua_skill_snapshot() -> str:
    """Return all unit skills via Lua.

    The Lua expression iterates ``df.global.units.all`` and builds a JSON
    object mapping unit IDs to a list of records with ``skill`` and ``level``
    fields. The JSON string is printed and captured by ``_dfhack_run``.
    """
    return (
        "local json=require('json');"
        "local result={};"
        "    if df.global and df.global.units and df.global.units.all then -- skill_probe edited"
        "    for _,u in ipairs(df.global.units.all) do"
        "        local skills={};"
        "        if u.skills then"
                    "            for _,s in ipairs(u.skills) do"
        "                -- s is a struct with .skill and .level fields"
        "                table.insert(skills,{skill=s.skill, level=s.level});"
        "            end"
        "        end"
        "        result[u.id] = skills;"
        "    end"
        "end"
        "print(json.encode(result));"
    )


def probe_skills(timeout: Optional[int] = 20) -> Optional[Dict[int, List[Dict[str, object]]]]:
    """Query the live DFHack process for unit skill data.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary mapping unit IDs to a list of skill ``{skill, level}`` dictionaries,
        or ``None`` if the underlying DFHack call raises an exception or returns an error.
    """
    try:
        raw = _dfhack_run(_lua_skill_snapshot(), timeout=timeout)
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None
    if "_dfhack_error" in raw or "_raw" in raw:
        return None
    # ``raw`` now contains the JSON‑decoded object from DFHack.
    if not isinstance(raw, dict) or any(not isinstance(k, int) for k in raw):
        return None

    for _unit_id, skills in raw.items():
        if not isinstance(skills, list):
            return None
        for skill in skills:
            if not isinstance(skill, dict):
                return None
            if "skill" not in skill or "level" not in skill:
                return None
            if not isinstance(skill["skill"], str):
                return None
            if not isinstance(skill["level"], int):
                return None

    return raw
