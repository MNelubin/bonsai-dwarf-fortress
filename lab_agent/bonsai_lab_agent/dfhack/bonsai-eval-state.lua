local json = require('json')

local function safe_string(value)
    if value == nil then return nil end
    return tostring(value)
end

local citizens = 0
local active_units = 0
if df.global.world and df.global.world.units then
    local ok, units = pcall(dfhack.units.getCitizens, true)
    if ok and units then
        citizens = #units
        for _, unit in ipairs(units) do
            if not unit.flags2.killed then active_units = active_units + 1 end
        end
    end
end

local state = {
    schema = 'bonsai-game-state-v1',
    ok = df.global ~= nil,
    gametype = safe_string(df.global.gametype),
    year = tonumber(df.global.cur_year),
    season = tonumber(df.global.cur_season),
    tick = tonumber(df.global.cur_year_tick),
    paused = df.global.pause_state and true or false,
    citizens = citizens,
    active_citizens = active_units,
}

print('BONSAI_GAME_STATE ' .. json.encode(state))
