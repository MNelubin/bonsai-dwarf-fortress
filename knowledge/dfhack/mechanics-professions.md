# Mechanic Analysis: Unit Professions

## Evidence
```bash
/srv/df-bonsai/current/dfhack-run tags units

# Output truncated: see full in probe log
```

> `profession` tag exists in units system. `:lua @df.profession` yields JSON list of professions at runtime.
> VERIFIED: `profession` is a public DFHack entity.

> `labors` table maps unit IDs to assigned tasks. `dfhack.run('list-units')` returns professions via API.
> INFERRED: Lua API exists for profession assignment queries without savefile dependency.

## Discovery

Chosen mechanic: **Unit Profession Transition Observer**

## Coding Task

Create `bridge/observe-professions.lua`:
```lua
-- Minimal deterministic API
function list_professions()
  return df.global.world.units.other[U].profession
end
```

Test:
```lua
require 'dfhack-test'
test('list_professions works', function()
  local professions = list_professions()
  assert(type(professions) == 'table')
  assert(#professions == EXPECTED_COUNT, 'Incorrect profession count')
end)
```
