-- Where does DF state a room's quality tier, and at what value does each rung start?
--
-- Asked because the shipped tier table was DFHack's PRE-v50 `dfhack_room_quality_level`
-- constants, and the binary's own strings refuse them: the four ladders have 7, 8, 8 and
-- 6 rungs, not a uniform 8, and every one ends in a `No X` rung DFHack has never had.
--
-- Three questions, one pass:
--   1. what numbers does DF itself demand of a noble's rooms (entity_position)
--   2. does anything in view_sheets carry the tier NAME, not just the value
--   3. does a civzone expose a description vmethod at all in this build

local out = {}
local function say(fmt, ...) out[#out + 1] = string.format(fmt, ...) end

-- ---------------------------------------------------------------- 1. noble demands
-- DF's own numbers for "this rank needs a room this good". In classic DF these land
-- exactly on the ladder cutoffs, which is what makes them worth reading.
say('== entity_position room requirements ==')
local seen = {}
for _, ent in ipairs(df.global.world.entities.all) do
    local ok = pcall(function()
        for _, p in ipairs(ent.positions.own) do
            local name = p.name[0]
            if name and name ~= '' and not seen[name] then
                local o = p.required_office or -1
                local b = p.required_bedroom or -1
                local d = p.required_dining or -1
                local t = p.required_tomb or -1
                if o > 0 or b > 0 or d > 0 or t > 0 then
                    seen[name] = true
                    say('%-24s office=%-6d bedroom=%-6d dining=%-6d tomb=%-6d',
                        name, o, b, d, t)
                end
            end
        end
    end)
    if not ok then say('  (entity %d unreadable)', ent.id) end
end

-- ---------------------------------------------------------------- 2. the name, if any
say('')
say('== view_sheets fields mentioning room ==')
pcall(function()
    local vs = df.global.game.main_interface.view_sheets
    for k, v in pairs(vs) do
        local ks = tostring(k):lower()
        if ks:find('room') or ks:find('qual') or ks:find('demand') then
            say('  %s = %s', tostring(k), tostring(v))
        end
    end
end)

-- ---------------------------------------------------------------- 3. civzone vmethods
say('')
say('== civzone methods mentioning room/value/descri ==')
local zone
for _, b in ipairs(df.global.world.buildings.all) do
    if b:getType() == df.building_type.Civzone then zone = b; break end
end
if not zone then
    say('  (no civzone on this fort)')
else
    say('  probing zone %d', zone.id)
    local names = {}
    local mt = getmetatable(zone)
    pcall(function()
        for k in pairs(df.building_civzonest) do names[#names + 1] = tostring(k) end
    end)
    pcall(function()
        local st = df.building_civzonest
        for k in pairs(st) do names[#names + 1] = tostring(k) end
    end)
    -- the reliable enumeration in dfhack lua is over the type's method table
    pcall(function()
        for k in pairs(df.building_civzonest._identity and
                       df.building_civzonest._identity or {}) do
            names[#names + 1] = 'id:' .. tostring(k)
        end
    end)
    local uniq, hits = {}, {}
    for _, n in ipairs(names) do
        if not uniq[n] then
            uniq[n] = true
            local l = n:lower()
            if l:find('room') or l:find('value') or l:find('descri') or l:find('qual') then
                hits[#hits + 1] = n
            end
        end
    end
    table.sort(hits)
    say('  %s', #hits > 0 and table.concat(hits, ', ') or '(none)')
end

local path = '/tmp/tierprobe.' .. (os.getenv('DFHACK_PORT') or 'x') .. '.txt'
local f = io.open(path, 'w')
if f then f:write(table.concat(out, '\n') .. '\n'); f:close() end
print(table.concat(out, '\n'))
print('-- wrote ' .. path)
