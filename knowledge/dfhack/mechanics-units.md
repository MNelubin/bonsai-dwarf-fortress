# Units Mechanical Notes

## Mechanics-units.md
This note explores the `gui/gm-unit` DFHack tool for unit attribute editing, identified via:

- VERIFIED `dfhack-run help lua` (initial Lua capabilities)
- VERIFIED `dfhack-run ls --dev gui/gm-unit` (dev tool presence)
- VERIFIED `dfhack-run help gui/gm-unit` (tool documentation)
- VERIFIED `grep *.lua gui/gm-unit` (internal Lua modules)

### Proposed Minimal API
Create a thin wrapper `dfhack-unit-get` with signature:

```
unit_get(unit_id: int) -> dict
```

Returns structured JSON dump of unit attributes (skills, needs, positions) from `dfhack-unit.lua`.

### Public Test
Add `tests/unit_api_test.py` to validate:

```
asert unit_get(1)['health_status'] == 'healthy'
```
