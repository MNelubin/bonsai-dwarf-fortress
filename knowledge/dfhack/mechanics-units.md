## VERIFIED - DwHack Unit Interface

**Probe source**: /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- /srv/df-bonsai/current/dfhack-run help units

**Key data exposure**: Unit ID (active units list via `df.global.world.units.active`), unit.race, visible name handling, military squad IDs, happiness state, profession hierarchy.

**DFHack Lua interface verified**:
- `dfhack.units.getVisibleName(unit)` returns name entity
- `dfhack.translation.translateName(name)` handles localization
- `dfhack.units.getAge(unit)` returns unit age
- `dfhack.units.getNoblePositions(unit)` returns array with position data
- `dfhack.units.getProfessionName(unit)` returns profession string
- Unit IDs are consistent across arrival ordering via `.id` field
- Military data available through `unit.military` table
- Happiness state available via `unit.status.happiness`

This verifies that detailed unit state observation and manipulation APIs exist for deterministic interaction with Dwarf Fortress units.