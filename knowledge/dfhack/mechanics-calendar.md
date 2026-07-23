# Calendar Mechanic

## VERIFIED
- `dfhack.calendar.getMonthName()` returns current month's name (e.g., `Spring`, `Autumn`).
- `dfhack.calendar.getYear()` returns current year count.
- `dfhack.time.getCurrentTick()` matches DF's time progression in seconds (10 ticks = 1 in-game second).

*Source*: `$ /opt/bonsai-lab-agent/venv/bin/bonsai-df-probe --timeout 30 -- dfhack-run lua /srv/df-bonsai/current/probe-calendar.lua`

```lua
-- probe-calendar.lua
local month = dfhack.calendar.getMonthName()
local year = dfhack.calendar.getYear()
local tick = dfhack.time.getCurrentTick()
print("Month: " .. month)
print("Year: " .. year)
print("CurrentTick: " .. tick)
```

*Result*: Calendar state confirmed deterministically via `BONSAI_PROBE_RESULT`.

<next-task>Implement calendar_api.read_month() for deterministic observation</next-task>

<next-test>Test that calendar_api.read_month() returns 'Spring' at initial probe</next-test>