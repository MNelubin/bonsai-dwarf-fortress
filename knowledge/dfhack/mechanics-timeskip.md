# Timeskip Manipulation

## VERIFIED Mechanic: `set-timeskip-duration`

- **Command**: `set-timeskip-duration --ticks <num>`
- **Conversion**: 50 ticks = 1 hour, 1200 ticks = 1 day, 8400 ticks = 1 week, 33600 ticks = 1 month, 403200 ticks = 1 year
- **Options**: `--years`, `--months`, `--days`, `--hours`, `--ticks`
- **Behavior**: Alters pre-game world update duration; persists until cleared
- **Probing Command**: `dfhack-run help set-timeskip-duration`

## Minimal Deterministic API
```lua
-- set_timeskip.lua
local args = {...}
local totalTicks = 0
for i,arg in ipairs(args) do
  if arg:match("^%d+$") then
    local value = tonumber(arg)
    local multiplier = {
      years = value * 403200,
      months = value * 33600,
      days = value * 8400,
      hours = value * 1200,
      ticks = value * 1
    }
    for key,_ in pairs(multiplier) do
      if args[i-1] == key then
        table.insert(multiplier, value)
        totalTicks = totalTicks + value
      end
    end
  else
    -- handle flag
  end
end
dfhack.run('set-timeskip-duration', totalTicks)
```

## Public Test
```lua
-- test_set_timeskip.lua
local result = dfhack.run('set-timeskip-duration', '--ticks', '60')
assert(result:match("Successfully"))
```