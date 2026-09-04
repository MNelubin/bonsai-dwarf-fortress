VERIFIED: Strangemood command found in /srv/df-bonsai/current/
```
/srv/df-bonsai/current/dfhack-run help strangemood
strangemood  Trigger a strange mood
```

VERIFIED: Strangemood Lua probe available under units tag
```
/srv/df-bonsai/current/dfhack-run ls units | grep strangemood
strangemood          Trigger a strange mood.
```

OPEN: Strangemood trigger API not mapped in knowledge base

STRANGEMOOD STATE API DESIGN
```
lua
function triggerStrangemood(unitId)
    return dfhack.script.run('trigger-strangemood', unitId)
end

function getStrangemoodStatus(unitId)
    return dfhack.units.getStrangeness(unitId)
end

function observeStrangemoodEffects(unitId)
    return dfhack.units.getSyndromes(unitId)
end
```

SMALLEST TEST
```lua
--- @testcase test_strangemood_trigger
--- @description Verify strangemood can be triggered on a unit
--- @setup Create test save with at least one dwarf
function test_strangemood_trigger()
    local unit = dfhack.units.getUnitsInView()['dwarf'][0]
    assert(unit ~= nil, "No dwarf in view")
    strangemood.triggerStrangemood(unit.id)
    local status = strangemood.getStrangemoodStatus(unit.id)
    assert(status.strangeness > 0, "Strangemood not triggered")
end
```

Next task: Implement strangemood.trigger function in /dev/null/bridge/mechanics/strangemood.ts
